"""Canais da demonstração com celulares de verdade: OpenWA (WhatsApp) e SMS Gateway for Android (SMS por um chip).

Tudo offline: as chamadas HTTP aos gateways são trocadas por respostas no formato documentado de cada um
(OpenWA docs/06-api-specification.md, seção 6.6; SMS Gateway README, "Webhooks"). NÃO substitui o teste com o
gateway rodando e um número pareado (docs/CANAIS_REAIS.md).
"""
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import channels, db, security, webhooks
from app.main import app

client = TestClient(app)


class _Resp:
    def __init__(self, data=None, status=200, content=b"", ctype="application/json"):
        self._data, self.status_code, self.content = data or {}, status, content
        self.headers = {"content-type": ctype}
        self.ok = status < 400

    def json(self):
        return self._data

    def raise_for_status(self):
        if not self.ok:
            raise channels.requests.HTTPError(str(self.status_code))


@pytest.fixture
def openwa_env(monkeypatch):
    monkeypatch.setenv("OPENWA_URL", "http://gw.test:2785/")
    monkeypatch.setenv("OPENWA_SESSION", "s1")
    monkeypatch.setenv("OPENWA_API_KEY", "k" * 20)
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(("GET", url, None))
        if "/contacts/check/" in url:
            return _Resp({"number": url.rsplit("/", 1)[1], "exists": True, "whatsappId": "556599990001@c.us"})
        return _Resp(content=b"\x89PNG....", ctype="image/png")

    def fake_post(url, headers=None, json=None, timeout=None, auth=None, data=None):
        calls.append(("POST", url, json))
        assert headers == {"X-API-Key": "k" * 20}
        return _Resp({"messageId": "true_556599990001@c.us_ABC", "timestamp": 1})

    monkeypatch.setattr(channels.requests, "get", fake_get)
    monkeypatch.setattr(channels.requests, "post", fake_post)
    return calls


def test_openwa_escolhido_em_qualquer_modo_de_dados(openwa_env, monkeypatch):
    monkeypatch.setenv("DATA_MODE", "simulado")
    assert isinstance(channels.get_channel("whatsapp"), channels.OpenWAChannel)
    assert isinstance(channels.get_channel("sms"), channels.ConsoleChannel)  # o SMS continua no simulador


def test_openwa_envia_texto_ao_id_canonico_e_a_imagem_em_base64(openwa_env):
    mid = channels.OpenWAChannel().send("+5565999990001", "Olá", "http://localhost:8000/r/x/img/mapa.png")
    assert mid == "true_556599990001@c.us_ABC"
    posts = [c for c in openwa_env if c[0] == "POST"]
    assert posts[0][1] == "http://gw.test:2785/api/sessions/s1/messages/send-text"
    assert posts[0][2] == {"chatId": "556599990001@c.us", "text": "Olá"}  # o id que o WhatsApp devolveu, sem o 9
    assert posts[1][1].endswith("/messages/send-image")
    assert posts[1][2]["mimetype"] == "image/png" and posts[1][2]["base64"] and "url" not in posts[1][2]


def test_openwa_numero_sem_whatsapp_falha_para_a_entrega_cair_no_sms(openwa_env, monkeypatch):
    monkeypatch.setattr(channels.requests, "get", lambda *a, **k: _Resp({"exists": False, "whatsappId": None}))
    with pytest.raises(channels.ChannelNotConfigured):
        channels.OpenWAChannel().send("+5565999990001", "Olá")


def test_br_mobile_poe_o_nono_digito_so_em_celular():
    assert webhooks.br_mobile("556599990001") == "5565999990001"
    assert webhooks.br_mobile("5565999990001") == "5565999990001"
    assert webhooks.br_mobile("556533221100") == "556533221100"  # fixo
    assert webhooks.br_mobile("14155550100") == "14155550100"  # fora do Brasil


def test_parse_openwa_texto_pin_ack_e_ignorados():
    base = {"event": "message.received", "data": {"id": "m1", "from": "556599990001@c.us", "body": "Oi", "type": "chat",
                                                   "fromMe": False, "isGroup": False, "kind": "individual"}}
    msgs, st = webhooks.parse_openwa(base)
    assert msgs[0].phone == "5565999990001" and msgs[0].text == "Oi" and not st
    pin = json.loads(json.dumps(base))
    pin["data"].update(type="location", body="", location={"latitude": -12.5, "longitude": -55.7})
    assert webhooks.parse_openwa(pin)[0][0].location == (-12.5, -55.7)
    for change in ({"fromMe": True}, {"isGroup": True, "kind": "group"}, {"from": "1234@lid"}):
        other = json.loads(json.dumps(base))
        other["data"].update(change)
        assert webhooks.parse_openwa(other) == ([], [])
    lid = json.loads(json.dumps(base))
    lid["data"].update({"from": "1234@lid", "senderPhone": "5565999990001"})
    assert webhooks.parse_openwa(lid)[0][0].phone == "5565999990001"
    ack = {"event": "message.ack", "data": {"messageId": "true_x", "status": "read"}}
    assert webhooks.parse_openwa(ack) == ([], [("true_x", "read", None)])


def _sign_openwa(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_openwa_exige_assinatura_e_processa(monkeypatch):
    monkeypatch.setenv("OPENWA_WEBHOOK_SECRET", "s" * 20)
    seen = []
    monkeypatch.setattr(webhooks, "process_whatsapp", lambda m: seen.append(m))
    body = json.dumps({"event": "message.received", "data": {"id": "w1", "from": "5565999990002@c.us", "body": "Oi",
                                                               "type": "chat", "fromMe": False, "isGroup": False}}).encode()
    assert client.post("/webhooks/openwa", content=body).status_code == 401
    assert client.post("/webhooks/openwa", content=body, headers={"X-OpenWA-Signature": _sign_openwa(body, "x" * 20)}).status_code == 401
    r = client.post("/webhooks/openwa", content=body, headers={"X-OpenWA-Signature": _sign_openwa(body, "s" * 20)})
    assert r.status_code == 200 and r.json()["recebidas"] == 1 and seen[0].text == "Oi"


def test_webhook_openwa_em_producao_sem_segredo_recusa(monkeypatch):
    monkeypatch.delenv("OPENWA_WEBHOOK_SECRET", raising=False)
    monkeypatch.setattr("app.config.is_production", lambda: True)
    assert client.post("/webhooks/openwa", content=b"{}").status_code == 503


def test_conversa_inteira_pelo_openwa_responde_pelo_gateway(openwa_env, monkeypatch):
    monkeypatch.setenv("DATA_MODE", "simulado")
    phone = "556599990003"
    for i, text in enumerate(["oi", "SIM"]):
        webhooks.process_whatsapp(webhooks.Incoming(f"conv-{i}", webhooks.br_mobile(phone), text))
    textos = [c[2]["text"] for c in openwa_env if c[0] == "POST" and c[1].endswith("send-text")]
    assert len(textos) == 2 and "SIM" in textos[0]
    assert db.get_producer_by_phone("+5565999990003") is not None


def _sign_sms(body: bytes, key: str, ts: str) -> str:
    return hmac.new(key.encode(), body + ts.encode(), hashlib.sha256).hexdigest()


def test_assinatura_do_sms_gateway():
    body, ts = b'{"a":1}', str(int(time.time()))
    assert security.verify_smsgate_signature(body, _sign_sms(body, "chave", ts), ts, "chave")
    assert not security.verify_smsgate_signature(body, _sign_sms(body, "outra", ts), ts, "chave")
    old = str(int(time.time()) - 3600)
    assert not security.verify_smsgate_signature(body, _sign_sms(body, "chave", old), old, "chave")  # reenvio antigo
    assert not security.verify_smsgate_signature(body, None, ts, "chave")


def test_sms_gateway_envia_e_recebe(monkeypatch):
    monkeypatch.setenv("SMSGATE_URL", "https://api.sms-gate.app/3rdparty/v1")
    monkeypatch.setenv("SMSGATE_USER", "u")
    monkeypatch.setenv("SMSGATE_PASSWORD", "p")
    monkeypatch.setenv("SMSGATE_WEBHOOK_KEY", "chave")
    sent = []

    def fake_post(url, json=None, auth=None, timeout=None, **kw):
        sent.append((url, json, auth))
        return _Resp({"id": "sg-1", "state": "Pending"})

    monkeypatch.setattr(channels.requests, "post", fake_post)
    assert isinstance(channels.get_channel("sms"), channels.SmsGateChannel)
    body = json.dumps({"event": "sms:received", "payload": {"messageId": "x9", "message": "BALK soja 20/10 Sorriso MT",
                                                             "phoneNumber": "+5566999990004", "simNumber": 1}}).encode()
    ts = str(int(time.time()))
    assert client.post("/webhooks/smsgate", content=body, headers={"X-Timestamp": ts, "X-Signature": "0" * 64}).status_code == 401
    r = client.post("/webhooks/smsgate", content=body, headers={"X-Timestamp": ts, "X-Signature": _sign_sms(body, "chave", ts)})
    assert r.status_code == 200 and r.json()["recebidas"] == 1
    assert sent and sent[0][0] == "https://api.sms-gate.app/3rdparty/v1/message" and sent[0][2] == ("u", "p")
    assert sent[0][1]["phoneNumbers"] == ["+5566999990004"] and sent[0][1]["textMessage"]["text"]
    # o mesmo SMS reenviado pelo celular não é processado de novo
    n = len(sent)
    client.post("/webhooks/smsgate", content=body, headers={"X-Timestamp": ts, "X-Signature": _sign_sms(body, "chave", ts)})
    assert len(sent) == n
