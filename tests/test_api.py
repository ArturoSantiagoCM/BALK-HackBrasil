"""Testes ponta a ponta da API com dados simulados (o que o n8n e o simulador web chamam)."""
from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)
CSV = (config.ROOT / "demo" / "coop.csv").read_text(encoding="utf-8")


def _importar():
    r = client.post("/ingest/producers", content=CSV, headers={"content-type": "text/csv"})
    assert r.status_code == 200
    return r.json()


def test_health_e_pagina_do_simulador():
    assert client.get("/health").json()["ok"] is True
    r = client.get("/")
    assert r.status_code == 200 and "BALK" in r.text


def test_conversa_pelo_simulador_gera_relatorio_ao_ficar_ativo():
    def say(text, **kw):
        return client.post("/simulate", json={"phone": "+5500900009999", "text": text, **kw}).json()
    assert "SIM" in say("oi")["reply"]
    say("SIM")
    say("", lat=-23.5874, lon=-46.6576)
    say("soja")
    r = say("20/07")
    assert r["became_active"]
    rel = [m for m in r["messages"] if m["kind"] == "report"][0]
    assert "Não substitui um engenheiro agrônomo" in rel["text"] and "soja" in rel["text"]
    assert rel["media_url"].endswith("/img/mapa.png") and "/r/" in rel["media_url"]
    assert "http" in rel["text"].rstrip().split("\n")[-1]  # a mensagem termina com o link do relatório
    png = client.get(rel["media_url"].replace("http://localhost:8000", ""))
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    assert client.post("/simulate", json={"phone": "+5500900009999", "text": "2"}).json()["reply"].startswith("Certo")
    assert len(client.get("/producers/active").json()) == 1


def test_csv_da_cooperativa_gera_5_relatorios():
    out = _importar()
    assert out["aceitos"] == 5 and out["erros"] == [] and len(out["relatorios"]) == 5
    for rel in out["relatorios"]:
        rep = [m for m in rel["messages"] if m["kind"] == "report"][0]["text"]
        assert rep.strip()
        if rel["channel"] == "sms":
            assert len(rep) <= 160 and rep.isascii()
        else:
            assert "Não substitui" in rep and "Indicadas" not in rep.replace("Mais indicadas", "")


def test_json_e_csv_com_erro_por_linha():
    r = client.post("/ingest/producers", json={"producers": [
        {"telefone": "+5511999990001", "lat": -12.5, "lon": -55.7, "cultura": "milho"},
        {"telefone": "", "lat": 0, "lon": 0}]}, params={"analisar": "false"}).json()
    assert r["aceitos"] == 1 and r["erros"][0]["linha"] == 2


def test_ciclo_diario_envia_geada_por_sms_e_depois_fica_em_silencio():
    _importar()
    d1 = client.post("/simulate/daily").json()["enviados"]
    tipos = {(e["phone"], e["type"]) for e in d1}
    assert ("+5500900000003", "geada") in tipos  # Aparados da Serra (cenário de geada), canal SMS
    geada = next(e for e in d1 if e["type"] == "geada")
    assert geada["channel"] == "sms" and len(geada["text"]) <= 160 and geada["text"].startswith("BALK: GEADA")
    assert geada["text"].isascii() and geada["text"].endswith("Resp 1=ok 2=ajuda")
    assert any(e["type"] == "pulverizacao" for e in d1) and any(e["type"] == "colheita" for e in d1)
    d2 = client.post("/simulate/daily").json()["enviados"]  # logo depois: silêncio
    assert d2 == []


def test_analyze_nao_registra_alertas_e_log_manual_silencia():
    pid = _importar()["ids"][2]  # produtor da geada
    a = client.post(f"/analyze/{pid}", params={"now": "2026-11-27T10:00:00"}).json()
    assert [x["type"] for x in a["alerts"]][0] == "geada"
    assert client.post(f"/analyze/{pid}", params={"now": "2026-11-27T10:00:00"}).json()["alerts"] == a["alerts"]
    client.post("/alerts/log", json={"producer_id": pid, "type": "geada", "sent_at": "2026-11-27T09:00:00"})
    again = client.post(f"/analyze/{pid}", params={"now": "2026-11-27T10:00:00"}).json()
    assert "geada" not in [x["type"] for x in again["alerts"]]
    assert client.post("/analyze/9999").status_code == 404


def test_logistica_e_previsao_da_cooperativa():
    ids = _importar()["ids"]
    plan = client.post("/logistics/plan", json={"producer_id": ids[1], "destination_id": "coop",
                                                "now": "2026-11-27T10:00:00"}).json()
    assert plan["dist_km"] >= 50 and plan["frete_rs"] > 0 and "Saia" in plan["text"] and plan["chuva_mm"] <= plan["pior_mm"]
    assert client.post("/logistics/plan", json={"producer_id": ids[1]}).status_code == 422
    f = client.get("/cooperative/coop_demo/forecast", params={"now": "2026-11-27T10:00:00"}).json()
    assert len(f["dias"]) == 7 and f["total_toneladas"] > 0
    assert any(r["caminhoes"] > 0 for r in f["dias"])


def test_sms_inbound_cadastro_e_resposta_1_ou_2():
    def sms(body):
        return client.post("/sms/inbound", json={"from": "+5500900008888", "body": body}).json()  # JSON = dev/n8n; Twilio = formulário assinado
    assert "SIM" in sms("BALK soja 20/10 Sorriso MT")["reply"]
    r = sms("SIM")
    assert r["became_active"] and r["messages"][0]["text"].startswith("BALK:")
    assert sms("1")["reply"] == "Registrado, obrigado."
    assert client.post("/sms/inbound", json={"body": "x"}).status_code == 422
    twiml = client.post("/sms/inbound", data={"From": "+5500900008889", "Body": "oi"})  # formulário (sem token Twilio em dev)
    assert twiml.headers["content-type"].startswith("application/xml") and "<Message>" in twiml.text
