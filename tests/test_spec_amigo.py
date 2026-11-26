"""Ganhos trazidos da comparação com a SPEC do amigo: dado real nunca vira simulado, estado 'sem imagem adequada', mensagens sem
sigla, consentimentos versionados, opt-in de cooperativa, log de mensagens com reserva por SMS, sucessor somente leitura,
histórico, limite diário e exclusão (LGPD)."""
import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import config, db, delivery
from app.alerts.silence import filter_by_silence
from app.channels import OUTBOX, ChannelNotConfigured, get_channel
from app.ingest.conversation import grant, handle_message
from app.ingest.csv_import import ingest_rows, parse_csv_text
from app.main import app, create_app
from app.message import render
from app.message.polish import ACRONYMS, validate_polished
from app.models import Alert, Producer
from app.service import analyze_producer, run_daily
from tests.conftest import NOW

client = TestClient(app)


def _ativo(phone="+5500900001001", channel="whatsapp", **kw):
    base = dict(phone=phone, lat=-23.5874, lon=-46.6576, crop="soja", planting_date="2026-07-25", consent=True,
                state="ATIVO", source="t", channel=channel)
    base.update(kw)
    p = db.create_producer(Producer(**base))
    grant(p.phone, p.id, "teste")
    return p


# ---------- princípio: dado real nunca é trocado por simulado ----------
def test_em_producao_auto_vale_como_real_e_nao_cai_para_simulado(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "auto")
    assert config.data_mode() == "auto"
    monkeypatch.setenv("BALK_ENV", "production")
    assert config.data_mode() == "real"


def test_canal_sem_credencial_em_producao_levanta_erro_em_vez_de_fingir(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("BALK_ENV", "production")
    for k in ("WHATSAPP_TOKEN", "TWILIO_ACCOUNT_SID"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ChannelNotConfigured):
        get_channel("whatsapp")
    monkeypatch.setenv("BALK_ENV", "dev")
    assert get_channel("whatsapp").name == "console"  # em desenvolvimento o console é o esperado


def test_satelite_fora_do_ar_vira_sem_imagem_e_so_ha_clima(monkeypatch):
    p = _ativo()
    monkeypatch.setattr("app.service.analyze", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Earth Search fora do ar")))
    res = analyze_producer(p.id, full=True, now=NOW)
    assert res["sem_imagem"] is True and res["stats"] is None and res["ranking"] == []
    rel = next(m for m in res["messages"] if m["kind"] == "report")
    assert "imagem de satélite recente e boa" in rel["text"] and "Mapa" not in rel["text"] and rel["media_url"] is None
    assert all(a["type"] != "estresse" for a in res["alerts"])  # sem satélite, nada de alerta de vigor


def test_imagem_muito_velha_e_descartada_e_a_velhinha_ganha_aviso(monkeypatch):
    from app.models import SpatialStats
    p = _ativo()
    velho = (NOW - timedelta(days=70)).strftime("%Y-%m-%d")
    stats = SpatialStats(ndvi_mean=0.7, area_ha=7, scene_date=velho, slope_mean_pct=3.0, clay_pct=40, ph=6.0, ndvi_std=0.05)
    monkeypatch.setattr("app.service.analyze", lambda *a, **k: stats)
    assert analyze_producer(p.id, full=True, now=NOW)["sem_imagem"] is True
    stats2 = stats.model_copy(update={"scene_date": (NOW - timedelta(days=40)).strftime("%Y-%m-%d")})
    monkeypatch.setattr("app.service.analyze", lambda *a, **k: stats2)
    res = analyze_producer(p.id, full=True, now=NOW)
    assert res["sem_imagem"] is False
    assert "40 dias atrás" in next(m for m in res["messages"] if m["kind"] == "report")["text"]


def test_ciclo_diario_pula_quem_falha_e_nao_gera_alerta_sem_dado(monkeypatch):
    a, b = _ativo("+5500900001002"), _ativo("+5500900001003", lat=-29.17, lon=-50.09)
    import app.service as svc
    real = svc.get_weather

    def clima(lat, lon, now=None):
        if abs(lat - (-29.17)) < 0.01:
            raise RuntimeError("Open-Meteo fora do ar")
        return real(lat, lon, now)
    monkeypatch.setattr(svc, "get_weather", clima)
    erros: list = []
    enviados = run_daily(NOW, errors=erros)
    assert {e["producer_id"] for e in erros} == {b.id}
    assert enviados and all(e["producer_id"] == a.id for e in enviados)
    assert db.get_alert_log(b.id) == [] and db.list_messages(b.id) == []


# ---------- mensagens sem sigla ----------
def test_mensagens_do_produtor_nao_trazem_sigla_tecnica_nos_3_idiomas():
    from tests.test_message import todos_os_alertas
    from app.message.templates import Report
    from app.models import SpatialStats, Viability
    st = SpatialStats(area_ha=7, scene_date="2026-11-22", ndvi_mean=0.7, slope_mean_pct=6, aspect_label="S", erosion_class="baixo",
                      moisture_class="baixa", frost_relief_offset_c=-0.8,
                      zones=[{"id": 1, "share_pct": 30.0, "ndvi_mean": 0.5}, {"id": 2, "share_pct": 70.0, "ndvi_mean": 0.7}])
    v = Viability(crop="soja", score=80, factors={"chuva_mm": 0.5}, limiting_factor="chuva_mm", orientation="x", confidence="media")
    rep = Report(ranking=[v], stats=st, relations={"saldo_mm": -8.0, "atencao_agua": True, "idade_cena_dias": 40, "cena_antiga": True})
    for lang in ("pt", "es", "en"):
        textos = [render(a, ch, lang) for a in todos_os_alertas() for ch in ("whatsapp", "sms")]
        textos += [render(rep, ch, lang) for ch in ("whatsapp", "sms")]
        for t in textos:
            achou = [s for s in ACRONYMS if re.search(rf"\b{re.escape(s)}\b", t)]
            assert not achou, (lang, achou, t)


def test_validador_reprova_sigla_tecnica_na_saida_da_ia():
    ok, motivo = validate_polished("Pulverize das 11h às 14h.", "Pulverize das 11h às 14h com NDVI bom.", {"window": "11h-14h", "action": "Pulverize"})
    assert not ok and "sigla" in motivo


# ---------- consentimento versionado ----------
def test_aceite_grava_finalidades_versao_origem_e_sair_revoga():
    handle_message("5500900002001", "oi"), handle_message("5500900002001", "SIM")
    cs = db.list_consents("+5500900002001")
    assert {c["purpose"] for c in cs} == {"dados_localizacao", "mensagens"}
    assert all(c["text_version"] == config.consent()["versao"] and c["origin"] == "whatsapp" and c["granted_at"] and not c["revoked_at"]
               for c in cs)
    assert db.has_consent("+5500900002001")
    handle_message("5500900002001", "SAIR")
    assert not db.has_consent("+5500900002001") and all(c["revoked_at"] for c in db.list_consents("+5500900002001"))


def test_telefone_e_normalizado_entre_whatsapp_e_cooperativa():
    assert db.norm_phone("5565999990000") == db.norm_phone("+55 65 99999-0000") == "+5565999990000"
    p = db.create_producer(Producer(phone="+55 65 99999-0001", consent=True, state="ATIVO"))
    assert db.get_producer_by_phone("5565999990001").id == p.id


# ---------- opt-in de cooperativa ----------
CSV = ("telefone,lat,lon,cultura,data_plantio,canal,origem\n"
       "+5500900003001,-23.58,-46.65,soja,2026-07-25,whatsapp,coopx\n")


def test_csv_em_producao_so_convida_e_nada_e_enviado_antes_do_sim(monkeypatch):
    monkeypatch.setenv("CSV_REQUIRES_OPTIN", "1")
    out = ingest_rows(parse_csv_text(CSV))
    assert out["aceitos"] == 1 and len(out["optin_pendentes"]) == 1 and out["ids_ativos"] == []
    p = db.get_producer_by_phone("+5500900003001")
    assert p.state == "AGUARDA_SIM" and not p.consent and p not in db.list_active()
    assert "coopx cadastrou você" in out["optin_pendentes"][0]["text"] and db.list_consents(p.phone) == []
    r = handle_message("5500900003001", "talvez")
    assert not r.became_active and "Responda SIM" in r.text
    r = handle_message("5500900003001", "SIM")
    assert r.became_active and db.get_producer_by_phone(p.phone).state == "ATIVO"
    assert db.list_consents(p.phone)[0]["origin"] == "optin:coopx"
    assert ingest_rows(parse_csv_text(CSV))["optin_pendentes"] == []  # reimportar não rebaixa quem já aceitou


def test_csv_no_modo_demo_segue_ativo_com_consentimento_declarado_pela_cooperativa(monkeypatch):
    monkeypatch.setenv("CSV_REQUIRES_OPTIN", "0")
    out = ingest_rows(parse_csv_text(CSV))
    assert out["optin_pendentes"] == [] and len(out["ids_ativos"]) == 1
    assert db.list_consents("+5500900003001")[0]["origin"] == "cooperativa:coopx"


def test_api_do_csv_envia_convite_e_nao_gera_relatorio_antes_do_aceite(monkeypatch):
    monkeypatch.setenv("CSV_REQUIRES_OPTIN", "1")
    OUTBOX.clear()
    r = client.post("/ingest/producers", content=CSV, headers={"content-type": "text/csv"}).json()
    assert r["convites_enviados"] == 1 and r["relatorios"] == []
    assert len(OUTBOX) == 1 and "Responda SIM" in OUTBOX[0]["text"]
    assert db.list_messages(r["ids"][0], kind="optin")


# ---------- log de mensagens, repetição e reserva por SMS ----------
def test_entrega_registra_mensagem_e_guarda_id_do_provedor():
    p = _ativo()
    r = delivery.deliver(p.id, p.phone, "whatsapp", "oi", kind="alert", type_="geada", confidence="alta", evidence={"tmin": 2})
    m = db.list_messages(p.id)[0]
    assert r["ok"] and m["state"] == "sent" and m["provider_id"].startswith("console-") and m["evidence"] == {"tmin": 2}


class _Quebrado:
    def __init__(self, vezes):
        self.vezes, self.chamadas = vezes, 0

    def send(self, phone, text, media_url=None, proactive=False):
        self.chamadas += 1
        if self.chamadas <= self.vezes:
            raise ConnectionError("timeout")
        return "wamid.OK"


def test_repete_com_recuo_e_depois_cai_para_sms(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    p = _ativo()
    wa, sms = _Quebrado(99), _Quebrado(0)
    monkeypatch.setattr(delivery, "get_channel", lambda name: wa if name == "whatsapp" else sms)
    r = delivery.deliver(p.id, p.phone, "whatsapp", "texto longo", kind="alert", sms_text="BALK curto")
    assert wa.chamadas == delivery.RETRIES and sms.chamadas == 1
    assert r["ok"] and r["channel"] == "sms"
    m = db.list_messages(p.id)[0]
    assert m["state"] == "sent" and m["channel"] == "sms" and "whatsapp falhou" in m["error"]


def test_segunda_tentativa_resolve_e_falha_total_fica_registrada(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    p = _ativo()
    wa = _Quebrado(1)
    monkeypatch.setattr(delivery, "get_channel", lambda name: wa)
    assert delivery.deliver(p.id, p.phone, "whatsapp", "x", kind="alert")["ok"] and wa.chamadas == 2
    tudo = _Quebrado(99)
    monkeypatch.setattr(delivery, "get_channel", lambda name: tudo)
    r = delivery.deliver(p.id, p.phone, "whatsapp", "y", kind="alert", sms_text="z")
    assert not r["ok"] and db.list_messages(p.id)[0]["state"] == "failed" and "timeout" in db.list_messages(p.id)[0]["error"]


def test_alerta_que_falhou_na_entrega_nao_entra_no_silencio(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    p = _ativo()
    monkeypatch.setattr(delivery, "get_channel", lambda name: _Quebrado(99))
    enviados = run_daily(NOW)
    assert enviados and not any(e["ok"] for e in enviados) and db.get_alert_log(p.id) == []  # amanhã tenta de novo


def test_status_do_provedor_so_avanca():
    p = _ativo()
    mid = db.log_message(p.id, p.phone, "out", "whatsapp", "alert", "x", provider_id="wamid.1", state="sent")
    assert db.update_message_state_by_provider("wamid.1", "delivered") == 1
    assert db.update_message_state_by_provider("wamid.1", "read") == 1
    assert db.update_message_state_by_provider("wamid.1", "delivered") == 0  # "lida" não volta a "entregue"
    assert db.update_message_state_by_provider("wamid.1", "failed", "fora da janela") == 1
    assert db.update_message_state_by_provider("naoexiste", "sent") == 0


# ---------- limite diário ----------
def _al(t):
    return Alert(type=t, action="x", evidence={}, confidence="alta", why="y")


def test_limite_diario_corta_o_terceiro_mas_nao_a_geada():
    p = Producer(id=1, phone="1")
    hoje = [{"type": "colheita", "sent_at": NOW.replace(hour=7).isoformat()},
            {"type": "estresse", "sent_at": NOW.replace(hour=8).isoformat()}]
    out = filter_by_silence([_al("pulverizacao"), _al("geada")], p, hoje, NOW, {**config.rules()["silencio"], "max_por_semana": 9})
    assert [a.type for a in out] == ["geada"]


# ---------- sucessor (somente leitura) e histórico ----------
def test_produtor_convida_sucessor_que_aceita_sozinho_e_recebe_copia_dos_alertas():
    p = _ativo("+5500900004001", channel="whatsapp")
    r = handle_message(p.phone, "SUCESSOR 5500900004002")
    assert "Enviei o convite" in r.text and r.notify[0][0] == "+5500900004002" and "Responda SIM" in r.notify[0][1]
    assert db.list_contacts(p.id, only_active=True) == []  # só ativa quando a PRÓPRIA pessoa aceita
    assert "SIM" in handle_message("5500900004002", "oi").text
    assert "vai receber os avisos" in handle_message("5500900004002", "SIM").text
    assert db.list_contacts(p.id, only_active=True)[0]["phone"] == "+5500900004002"
    assert {c["origin"] for c in db.list_consents("+5500900004002")} == {"sucessor"}
    OUTBOX.clear()
    enviados = run_daily(NOW)
    para = {m["to"] for m in OUTBOX}
    assert "+5500900004001" in para and "+5500900004002" in para
    assert any(m["kind"] == "alert_copia" for m in db.list_messages(p.id, limit=50))
    assert enviados


def test_sucessor_nao_altera_dados_e_pode_sair():
    p = _ativo("+5500900004011")
    handle_message(p.phone, "SUCESSOR 5500900004012")
    handle_message("5500900004012", "SIM")
    antes = db.get_producer(p.id)
    for texto in ("soja", "mudar cultura milho", "2", "SUCESSOR 5500900004099", "20/10", "-12.5,-55.7"):
        r = handle_message("5500900004012", texto)
        assert "Só o produtor altera dados" in r.text and not r.notify
    assert db.get_producer(p.id) == antes and db.get_contact_by_phone("5500900004099") is None
    assert db.list_escalations() == []  # a resposta 2 do sucessor não escala nada em nome do produtor
    handle_message("5500900004012", "SAIR")
    assert db.list_contacts(p.id, only_active=True) == [] and not db.has_consent("+5500900004012")


def test_historico_somente_leitura_por_link_e_do_produtor_certo():
    a, b = _ativo("+5500900004021"), _ativo("+5500900004022", lat=-29.17, lon=-50.09)
    db.log_message(a.id, a.phone, "out", "whatsapp", "alert", "Proteja a lavoura sensível.\n\nDetalhes, mapas e o porquê: http://x/r/abc",
                   type_="geada", confidence="alta", report_token="TOKENDOPRODUTORA12345", state="sent")
    db.log_message(b.id, b.phone, "out", "whatsapp", "alert", "SEGREDO DO OUTRO PRODUTOR", type_="colheita", state="sent")
    r = handle_message(a.phone, "histórico")
    link = re.search(r"/h/([A-Za-z0-9_-]+)", r.text).group(1)
    pag = client.get(f"/h/{link}")
    assert pag.status_code == 200 and "Proteja a lavoura" in pag.text and "SEGREDO" not in pag.text
    assert "/r/TOKENDOPRODUTORA12345" in pag.text and "noindex" in pag.headers["x-robots-tag"]
    assert "http://x/r/abc" not in pag.text  # o link velho sai do texto
    assert client.get("/h/" + "z" * 22).status_code == 404 and client.get("/h/curto").status_code == 404
    # o sucessor usa o mesmo caminho, com poder só de leitura
    handle_message(a.phone, "SUCESSOR 5500900004023")
    handle_message("5500900004023", "SIM")
    assert "/h/" in handle_message("5500900004023", "HISTORICO").text


def test_link_de_historico_nao_serve_como_relatorio_e_expira():
    p = _ativo("+5500900004031")
    tok = db.create_link(p.id, "history")
    assert client.get(f"/r/{tok}").status_code == 404  # escopos diferentes
    with db.connect() as con:
        con.execute("UPDATE links SET expires_at=?", ((datetime.now() - timedelta(days=1)).isoformat(),))
    assert client.get(f"/h/{tok}").status_code == 404


# ---------- exclusão (LGPD): tudo some, sobra só o mínimo ----------
def test_exclusao_remove_todas_as_tabelas_e_deixa_so_registro_sem_dado_pessoal():
    p = _ativo("+5500900004041")
    handle_message(p.phone, "SUCESSOR 5500900004042")
    handle_message("5500900004042", "SIM")
    res = analyze_producer(p.id, full=True, now=NOW)
    db.log_alert(p.id, "geada")
    db.log_message(p.id, p.phone, "in", "whatsapp", "texto", "oi", state="received")
    db.create_link(p.id, "history")
    contagem = db.delete_producer(p.id)
    assert contagem["producers"] == 1 and contagem["contacts"] == 1 and contagem["consents"] >= 4 and contagem["reports"] >= 1
    with db.connect() as con:
        for tabela in ("analyses", "alert_log", "reports", "messages", "links", "contacts", "escalations"):
            assert con.execute(f"SELECT COUNT(*) FROM {tabela} WHERE producer_id=?", (p.id,)).fetchone()[0] == 0, tabela
        assert con.execute("SELECT COUNT(*) FROM consents WHERE phone IN (?,?)", ("+5500900004041", "+5500900004042")).fetchone()[0] == 0
        audit = con.execute("SELECT * FROM audit_log").fetchall()
    assert len(audit) == 1 and audit[0]["event"] == "produtor_excluido"
    assert "5500900004041" not in str(dict(audit[0])) and len(audit[0]["subject_hash"]) == 16  # só um hash, nenhum telefone
    assert db.get_report(res["report_token"]) is None


def test_exportacao_inclui_consentimentos_com_data_e_versao(capsys):
    from app import cli
    p = _ativo("+5500900004051")
    assert cli.main(["export-producer", p.phone]) == 0
    out = capsys.readouterr().out
    assert '"consentimentos"' in out and config.consent()["versao"] in out and "dados_localizacao" in out and '"mensagens_enviadas"' in out
