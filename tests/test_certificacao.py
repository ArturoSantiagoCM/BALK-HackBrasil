"""Certificação do MVP: as partes conversam entre si (nada isolado). Cada teste percorre um caminho inteiro."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.channels import OUTBOX
from app.main import app
from app.service import run_daily
from tests.conftest import NOW

client = TestClient(app)
ROOT = Path(__file__).resolve().parent.parent
TEL = "+5565999993333"


def _cadastrar_por_whatsapp(tel=TEL):
    say = lambda t, **kw: client.post("/simulate", json={"phone": tel, "text": t, **kw}).json()  # noqa: E731
    say("oi"), say("SIM"), say("", lat=-12.62, lon=-55.85), say("soja")
    return say("20/10")


def test_whatsapp_cadastro_relatorio_alerta_resposta_e_pedido_de_agronomo_ficam_ligados():
    r = _cadastrar_por_whatsapp()
    rel = [m for m in r["messages"] if m["kind"] == "report"]
    assert r["became_active"] and rel and "/r/" in rel[0]["text"] and len(rel[0]["text"].splitlines()) <= 8  # curto + link
    OUTBOX.clear()
    enviados = run_daily(NOW)
    meus = [e for e in enviados if e["phone"] == TEL]
    assert meus, "o ciclo do dia precisa gerar ao menos um aviso para o produtor novo"
    chegou = [m for m in OUTBOX if m["to"] == TEL and m["canal"] == "whatsapp"]
    assert chegou and "Responda 1" in chegou[0]["text"] and "/r/" in chegou[0]["text"]  # o aviso chega no celular com o link
    client.post("/simulate", json={"phone": TEL, "text": "1"})
    assert client.post("/simulate", json={"phone": TEL, "text": "2"}).json()["reply"].startswith("Certo")
    ped = client.get("/escalations").json()[0]
    assert ped["phone"] == TEL and "aviso de" in ped["note"] and "/r/" in ped["note"]  # a equipe sabe sobre o quê e abre o relatório
    m = client.get("/metricas").json()
    assert m["avisos_enviados"] >= 1 and m["respostas_vou_fazer"] == 1 and m["pedidos_de_agronomo"] == 1 and m["taxa_de_resposta_pct"] > 0
    tok = ped["note"].split("/r/")[1].strip()
    assert client.get(f"/r/{tok}").status_code == 200


def test_celular_simulado_le_o_provedor_por_numero_e_por_sequencia():
    OUTBOX.clear()
    _cadastrar_por_whatsapp("+5565999994444")
    client.post("/simulate", json={"phone": "+5565999994444", "text": "SUCESSOR 65 99999-4545"})
    convite = client.get("/outbox", params={"para": "+5565999994545"}).json()
    assert len(convite) == 1 and "SIM" in convite[0]["text"] and convite[0]["finalidade"] == "invite" and convite[0]["canal"] == "whatsapp"
    seq = convite[0]["seq"]
    assert client.get("/outbox", params={"para": "+5565999994545", "depois": seq}).json() == []  # nada repetido
    est = client.get("/demo/estado").json()
    p = next(x for x in est["produtores"] if x["phone"] == "+5565999994444")
    assert p["state"] == "ATIVO" and p["crop"] == "soja" and "metricas" in est and "pedidos_agronomo" in est


def test_sms_por_municipio_nao_repete_a_explicacao():
    tel = "+5500900007777"
    client.post("/simulate", json={"phone": tel, "text": "BALK soja 20/10 Sorriso MT", "channel": "sms"})
    r = client.post("/simulate", json={"phone": tel, "text": "SIM", "channel": "sms"}).json()
    textos = [m["text"] for m in r["messages"]]
    assert len(textos) == 1 and "cadastro ok" in textos[0] and all(len(t) <= 160 and t.isascii() for t in textos)


def test_previsao_da_cooperativa_mostra_o_que_espera_tempo_seco():
    csv = (ROOT / "demo" / "coop.csv").read_text(encoding="utf-8")
    client.post("/ingest/producers?analisar=false", content=csv, headers={"content-type": "text/csv"})
    f = client.get("/cooperative/coop_demo/forecast").json()
    assert len(f["dias"]) == 7 and "aguardando_janela" in f and "aguardando_toneladas" in f


def test_fluxos_do_n8n_sao_validos_e_usam_o_ciclo_do_balk():
    for arq in sorted((ROOT / "n8n").glob("*.json")):
        d = json.loads(arq.read_text(encoding="utf-8"))
        nomes = {n["name"] for n in d["nodes"]}
        for src, v in d["connections"].items():
            assert src in nomes, (arq.name, src)
            for saida in v["main"]:
                for alvo in saida:
                    assert alvo["node"] in nomes, (arq.name, alvo)
        assert all("BALK_API_KEY" not in json.dumps(n) and "token" not in json.dumps(n.get("credentials", {})).lower() for n in d["nodes"])
    wf2 = json.loads((ROOT / "n8n" / "wf2_diario.json").read_text(encoding="utf-8"))
    assert any(n["parameters"].get("url", "").endswith("/jobs/daily") for n in wf2["nodes"])  # silêncio por talhão, template e SMS ficam no BALK
    wf1 = json.dumps(json.loads((ROOT / "n8n" / "wf1_entrada.json").read_text(encoding="utf-8")))
    assert "kind === 'report'" in wf1  # o primeiro relatório também sai pelo n8n


def test_relatorio_de_cada_aviso_tem_conclusoes_e_dados_para_o_tecnico():
    _cadastrar_por_whatsapp("+5565999995555")
    p = db.get_producer_by_phone("+5565999995555")
    enviados = [e for e in run_daily(NOW) if e["producer_id"] == p.id]
    tok = enviados[0]["text"].split("/r/")[1].split()[0]
    d = client.get(f"/r/{tok}/dados.json").json()
    assert d["conclusoes"] and any("Alerta de" in c for c in d["conclusoes"]) and d["alertas"][0]["criterios"]
    assert d["clima_horas"] and d["metodo"]
