"""Chave de API, modo production, assinatura dos webhooks da Meta e da Twilio, idempotência e LGPD."""
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app import config, db, security, webhooks
from app.channels import OUTBOX
from app.main import create_app
from app.models import Producer

CHAVE = "k" * 32


def _app(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return TestClient(create_app())


def _meta_body(msgs):
    return json.dumps({"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {"messages": msgs}}]}]}).encode()


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ---- chave de API ----
def test_com_chave_definida_as_rotas_internas_exigem_a_chave(monkeypatch):
    c = _app(monkeypatch, BALK_API_KEY=CHAVE)
    assert c.post("/analyze/1").status_code == 401
    assert c.post("/analyze/1", headers={"X-API-Key": "errada"}).status_code == 401
    assert c.post("/analyze/1", headers={"X-API-Key": CHAVE}).status_code == 404  # passou na auth; produtor não existe
    assert c.post("/analyze/1", headers={"Authorization": f"Bearer {CHAVE}"}).status_code == 404
    assert c.get("/health").status_code == 200  # pública


def test_production_recusa_subir_com_pendencias(monkeypatch):
    monkeypatch.setenv("BALK_ENV", "production")
    with pytest.raises(RuntimeError, match="BALK_API_KEY"):
        create_app()


def test_production_pronto_nao_expoe_simulador_nem_docs_e_exige_chave(monkeypatch):
    c = _app(monkeypatch, BALK_ENV="production", BALK_API_KEY=CHAVE, PUBLIC_BASE_URL="https://balk.exemplo.com.br",
             DATA_MODE="auto", BALK_AUTH_SECRET="s" * 32)
    assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404
    assert c.get("/").status_code == 200 and c.get("/app/cadastro.html").status_code == 200  # o site é público
    assert c.get("/demo/index.html").status_code == 404  # o simulador não
    assert c.post("/simulate", json={"phone": "1"}).status_code == 404
    assert c.get("/maps/1.png").status_code == 404
    assert c.get("/producers").status_code == 401  # lista de telefones: só com chave
    assert c.get("/producers", headers={"X-API-Key": CHAVE}).status_code == 200
    assert c.get("/health").json() == {"ok": True}  # sem configuração à mostra
    ready = c.get("/ready", headers={"X-API-Key": CHAVE}).json()
    assert ready["ok"] and ready["pendencias"] == [] and ready["env"] == "production"


def test_pendencias_de_producao_listadas(monkeypatch):
    monkeypatch.setenv("WHATSAPP_TOKEN", "x")
    monkeypatch.setenv("DATA_MODE", "simulado")
    p = " ".join(config.production_problems())
    assert "BALK_API_KEY" in p and "PUBLIC_BASE_URL" in p and "simulado" in p and "WHATSAPP_APP_SECRET" in p


def test_erro_interno_nao_vaza_detalhe(monkeypatch):
    c = _app(monkeypatch)
    c2 = TestClient(c.app, raise_server_exceptions=False)
    monkeypatch.setattr("app.main.db.list_all", lambda: (_ for _ in ()).throw(RuntimeError("segredo interno")))
    r = c2.get("/producers")
    assert r.status_code == 500 and "segredo" not in r.text and r.json()["id"]


# ---- WhatsApp (Meta) ----
def test_verificacao_do_webhook_da_meta(monkeypatch):
    c = _app(monkeypatch, WHATSAPP_VERIFY_TOKEN="meu-token")
    ok = c.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "meu-token", "hub.challenge": "12345"})
    assert ok.status_code == 200 and ok.text == "12345"
    assert c.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "errado", "hub.challenge": "1"}).status_code == 403


def test_assinatura_da_meta_valida_e_invalida():
    body = b'{"a":1}'
    assert security.verify_meta_signature(body, _sign(body, "segredo"), "segredo")
    assert not security.verify_meta_signature(body, _sign(body, "outro"), "segredo")
    assert not security.verify_meta_signature(body, None, "segredo")
    assert not security.verify_meta_signature(body, "sha256=abc", "segredo")
    assert not security.verify_meta_signature(body + b" ", _sign(body, "segredo"), "segredo")  # corpo adulterado


def test_webhook_da_meta_rejeita_sem_assinatura_e_processa_com(monkeypatch):
    c = _app(monkeypatch, WHATSAPP_APP_SECRET="segredo")
    body = _meta_body([{"from": "5500900001234", "id": "wamid.1", "type": "text", "text": {"body": "oi"}}])
    assert c.post("/webhooks/whatsapp", content=body).status_code == 401
    assert c.post("/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": "sha256=00"}).status_code == 401
    OUTBOX.clear()
    r = c.post("/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": _sign(body, "segredo")})
    assert r.status_code == 200 and r.json()["recebidas"] == 1
    assert OUTBOX and "Responda SIM" in OUTBOX[-1]["text"]  # a resposta de consentimento saiu pelo canal
    assert db.get_producer_by_phone("5500900001234").state == "INICIO"


def test_webhook_da_meta_e_idempotente(monkeypatch):
    c = _app(monkeypatch, WHATSAPP_APP_SECRET="segredo")
    body = _meta_body([{"from": "5500900001235", "id": "wamid.2", "type": "text", "text": {"body": "oi"}}])
    h = {"X-Hub-Signature-256": _sign(body, "segredo")}
    OUTBOX.clear()
    c.post("/webhooks/whatsapp", content=body, headers=h)
    c.post("/webhooks/whatsapp", content=body, headers=h)  # a Meta reenvia: não pode responder duas vezes
    assert len(OUTBOX) == 1


def test_conversa_completa_pelo_webhook_com_pin_de_localizacao(monkeypatch):
    c = _app(monkeypatch, WHATSAPP_APP_SECRET="s")
    OUTBOX.clear()
    seq = [{"type": "text", "text": {"body": "oi"}}, {"type": "text", "text": {"body": "SIM"}},
           {"type": "location", "location": {"latitude": -23.5874, "longitude": -46.6576}},
           {"type": "text", "text": {"body": "soja"}}, {"type": "text", "text": {"body": "20/07"}}]
    for i, m in enumerate(seq):
        body = _meta_body([{"from": "5500900001236", "id": f"wamid.c{i}", **m}])
        assert c.post("/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": _sign(body, "s")}).status_code == 200
    assert db.get_producer_by_phone("5500900001236").state == "ATIVO"
    textos = [m["text"] for m in OUTBOX]
    assert any("Cadastro pronto" in t for t in textos)
    rel = next(m for m in OUTBOX if "viabilidade" in m["text"])
    assert "/r/" in rel["text"] and rel["media_url"].endswith("/img/mapa.png")  # relatório com link e o mapa como imagem


def test_leitura_dos_formatos_de_mensagem_da_meta():
    payload = json.loads(_meta_body([
        {"from": "55", "id": "1", "type": "text", "text": {"body": "oi"}},
        {"from": "55", "id": "2", "type": "location", "location": {"latitude": -1.5, "longitude": -50.0}},
        {"from": "55", "id": "3", "type": "button", "button": {"text": "SIM"}},
        {"from": "55", "id": "4", "type": "interactive", "interactive": {"button_reply": {"title": "2"}}},
        {"from": "55", "id": "5", "type": "image", "image": {}}, {"id": "6", "type": "text", "text": {"body": "sem remetente"}}]))
    got = webhooks.parse_meta_payload(payload)
    assert [(g.id, g.text) for g in got] == [("1", "oi"), ("2", ""), ("3", "SIM"), ("4", "2")]
    assert got[1].location == (-1.5, -50.0)
    assert webhooks.parse_meta_payload({"entry": [{"changes": [{"value": {"statuses": [{}]}}]}]}) == []


def test_corpo_invalido_no_webhook(monkeypatch):
    c = _app(monkeypatch, WHATSAPP_APP_SECRET="s")
    body = b"isto nao e json"
    assert c.post("/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": _sign(body, "s")}).status_code == 400


# ---- SMS (Twilio) ----
def test_assinatura_da_twilio_confere_com_o_exemplo_publico():
    # exemplo da documentação da Twilio (validação de requisição)
    url = "https://mycompany.com/myapp.php?foo=1&bar=2"
    params = {"CallSid": "CA1234567890ABCDE", "Caller": "+12349013030", "Digits": "1234", "From": "+12349013030", "To": "+18005551212"}
    assert security.twilio_signature(url, params, "12345") == "0/KCTR6DLpKmkAf8muzZqo1nDgQ="
    assert security.verify_twilio_signature(url, params, "0/KCTR6DLpKmkAf8muzZqo1nDgQ=", "12345")
    assert not security.verify_twilio_signature(url, {**params, "Digits": "9"}, "0/KCTR6DLpKmkAf8muzZqo1nDgQ=", "12345")


def test_sms_inbound_da_twilio_exige_assinatura_e_responde_twiml(monkeypatch):
    c = _app(monkeypatch, TWILIO_AUTH_TOKEN="tok", PUBLIC_BASE_URL="https://balk.exemplo.com.br")
    form = {"From": "+5500900002222", "Body": "BALK soja 20/10 Sorriso MT"}
    assert c.post("/sms/inbound", data=form).status_code == 401
    assert c.post("/sms/inbound", data=form, headers={"X-Twilio-Signature": "errada"}).status_code == 401
    sig = security.twilio_signature("https://balk.exemplo.com.br/sms/inbound", form, "tok")
    r = c.post("/sms/inbound", data=form, headers={"X-Twilio-Signature": sig})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert "<Response><Message>" in r.text and "SIM" in r.text


def test_sms_inbound_json_nao_vale_em_producao(monkeypatch):
    c = _app(monkeypatch, BALK_ENV="production", BALK_API_KEY=CHAVE, PUBLIC_BASE_URL="https://balk.exemplo.com.br", DATA_MODE="auto",
             BALK_AUTH_SECRET="s" * 32)
    assert c.post("/sms/inbound", json={"from": "+5511", "body": "oi"}).status_code == 401


def test_telefone_mascarado_nos_logs():
    assert security.mask_phone("+55 11 90000-1234") == "***1234" and security.mask_phone("") == "***"


# ---- LGPD ----
def test_apagar_produtor_remove_tudo_inclusive_arquivos(monkeypatch, tmp_path):
    from app.service import analyze_producer
    p = db.create_producer(Producer(phone="+5500900003333", lat=-23.58, lon=-46.65, crop="soja", planting_date="2026-07-25",
                                    consent=True, state="ATIVO"))
    res = analyze_producer(p.id, full=True)
    assert res["report_url"] and (config.work_root() / str(p.id)).exists()
    db.log_alert(p.id, "geada")
    c = _app(monkeypatch, BALK_API_KEY=CHAVE)
    assert c.delete(f"/producers/{p.id}").status_code == 401
    r = c.delete(f"/producers/{p.id}", headers={"X-API-Key": CHAVE})
    assert r.status_code == 200 and r.json()["producers"] == 1 and r.json()["reports"] >= 1
    assert db.get_producer(p.id) is None and not (config.work_root() / str(p.id)).exists()
    assert db.get_report(res["report_url"].rsplit("/", 1)[1]) is None and db.get_alert_log(p.id) == []
    assert c.delete(f"/producers/{p.id}", headers={"X-API-Key": CHAVE}).status_code == 404


def test_cli_backup_exporta_e_apaga(tmp_path, capsys):
    from app import cli
    db.create_producer(Producer(phone="+5500900004444", lat=-1, lon=-50, consent=True, state="ATIVO"))
    assert cli.main(["backup", str(tmp_path / "b.db")]) == 0 and (tmp_path / "b.db").stat().st_size > 0
    assert cli.main(["export-producer", "+5500900004444"]) == 0
    assert "+5500900004444" in capsys.readouterr().out
    assert cli.main(["delete-producer", "+5500900004444"]) == 0
    assert cli.main(["delete-producer", "+5500900004444"]) == 1
    assert cli.main([]) == 2

# ---- modo demo (demonstração pública para os avaliadores) ----
DEMO_ENV = dict(BALK_ENV="demo", BALK_API_KEY=CHAVE, BALK_AUTH_SECRET="s" * 32,
                PUBLIC_BASE_URL="https://balk-demo.exemplo.com.br", DATA_MODE="simulado")


def test_demo_abre_o_simulador_sem_chave(monkeypatch):
    c = _app(monkeypatch, **DEMO_ENV)
    assert c.get("/demo/index.html").status_code == 200
    assert c.get("/destinos").status_code == 200
    assert c.get("/outbox").status_code == 200


def test_demo_nao_apaga_o_banco_sem_chave(monkeypatch):
    c = _app(monkeypatch, **DEMO_ENV)
    assert c.post("/simulate/reset").status_code == 401
    assert c.post("/simulate/reset", headers={"X-API-Key": CHAVE}).status_code == 200


def test_demo_mantem_as_rotas_internas_com_chave(monkeypatch):
    c = _app(monkeypatch, **DEMO_ENV)
    assert c.post("/jobs/daily").status_code == 401


@pytest.mark.parametrize("extra", [dict(BALK_API_KEY=""), dict(PUBLIC_BASE_URL="http://localhost:8000"),
                                   dict(BALK_AUTH_SECRET=""), dict(DATA_MODE="real"), dict(WHATSAPP_TOKEN="x")])
def test_demo_recusa_subir_com_pendencias(monkeypatch, extra):
    with pytest.raises(RuntimeError, match="BALK_ENV=demo com pendências"):
        _app(monkeypatch, **{**DEMO_ENV, **extra})

# ---- produtores fictícios da demo pública ----
def test_demo_importar_csv_sem_chave_usa_so_o_csv_ficticio(monkeypatch):
    c = _app(monkeypatch, **DEMO_ENV)
    r = c.post("/ingest/producers", content="telefone,lat,lon\n+5511999999999,-23.5,-46.6\n",
               headers={"content-type": "text/csv"})
    assert r.status_code == 200 and r.json()["aceitos"] == 5
    phones = {p["phone"] for p in c.get("/producers").json()}
    assert "+5511999999999" not in phones and all(x.startswith("+55009") for x in phones)


def test_demo_carrega_os_produtores_ficticios_uma_vez(monkeypatch):
    for k, v in DEMO_ENV.items():
        monkeypatch.setenv(k, v)
    from app import db, main
    assert main.seed_demo_if_empty() is True
    assert len(db.list_all()) == 5
    assert main.seed_demo_if_empty() is False  # já carregado: não repete
    assert len(db.list_all()) == 5


def test_fora_da_demo_importar_csv_continua_aceitando_o_corpo(monkeypatch):
    c = _app(monkeypatch, BALK_ENV="dev")
    r = c.post("/ingest/producers?analisar=false", content="telefone,lat,lon,cultura,data_plantio,canal,origem,consentimento\n"
               "+5500900009999,-23.5874,-46.6576,soja,2026-07-25,whatsapp,teste,sim\n", headers={"content-type": "text/csv"})
    assert r.status_code == 200 and r.json()["aceitos"] == 1
