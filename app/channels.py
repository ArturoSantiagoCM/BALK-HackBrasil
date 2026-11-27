"""Canais trocáveis: ConsoleChannel (simulador), SmsChannel (Twilio), WhatsAppChannel (Meta Cloud API) e, para a
demonstração com celulares de verdade, OpenWAChannel (gateway de WhatsApp auto-hospedado) e SmsGateChannel (um Android
com chip enviando SMS pelo app "SMS Gateway for Android").

Todos implementam send(phone, text, media_url, proactive) e devolvem o id da mensagem no provedor (ou None).
Os oficiais (Meta e Twilio) NÃO foram testados com contas de verdade (sem chaves). Em produção, canal sem credencial
LEVANTA ERRO: nunca se "envia" para um console que ninguém lê.

Escolha (get_channel): OPENWA_URL liga o OpenWA para o WhatsApp e SMSGATE_URL liga o Android para o SMS, em QUALQUER modo
de dados (o modo de dados decide de onde vêm satélite e clima; o canal decide para onde vai a mensagem). Sem eles, o
modo simulado usa o console, e o real usa Meta e Twilio quando há chave.
"""
import base64
import itertools
import logging
import os
from typing import Optional

import requests

from app import config

log = logging.getLogger("balk.channels")
OUTBOX: list[dict] = []  # mensagens "enviadas" pelo ConsoleChannel (o simulador web lê daqui)
_seq = itertools.count(int(__import__("time").time() * 1000))  # cresce sempre, mesmo se o servidor reiniciar (o simulador pede "depois de N")


class ChannelNotConfigured(RuntimeError):
    pass


class ConsoleChannel:
    """Provedor de mentira da demonstração: guarda o que "chegaria" no celular (o simulador lê de /outbox).
    `via` = o canal pedido (whatsapp ou sms), para o simulador mostrar a mensagem no aparelho certo."""
    name = "console"

    def __init__(self, via: str = "whatsapp"):
        self.via = via

    def send(self, phone: str, text: str, media_url: Optional[str] = None, proactive: bool = False,
             purpose: Optional[str] = None) -> Optional[str]:
        from datetime import datetime
        from app.db import norm_phone
        seq = next(_seq)
        OUTBOX.append({"seq": seq, "to": norm_phone(phone), "text": text, "media_url": media_url, "canal": self.via,
                       "proativa": proactive, "finalidade": purpose, "em": datetime.now().isoformat(timespec="seconds")})
        del OUTBOX[:-500]  # só as 500 últimas ficam na memória
        return f"console-{seq}"


class SmsChannel:
    name = "sms"

    def send(self, phone: str, text: str, media_url: Optional[str] = None, proactive: bool = False,
             purpose: Optional[str] = None) -> Optional[str]:
        sid, token = os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]
        r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", timeout=10,
                          auth=(sid, token), data={"To": phone, "From": os.environ["TWILIO_FROM"], "Body": text})
        r.raise_for_status()
        return r.json().get("sid")


class WhatsAppChannel:
    name = "whatsapp"

    def _post(self, payload: dict) -> Optional[str]:
        r = requests.post(f"https://graph.facebook.com/v21.0/{os.environ['WHATSAPP_PHONE_ID']}/messages", timeout=10,
                          headers={"Authorization": f"Bearer {os.environ['WHATSAPP_TOKEN']}"},
                          json={"messaging_product": "whatsapp", "to": phone_digits(payload.pop("to")), **payload})
        r.raise_for_status()
        msgs = r.json().get("messages") or [{}]
        return msgs[0].get("id")

    def send(self, phone: str, text: str, media_url: Optional[str] = None, proactive: bool = False,
             purpose: Optional[str] = None) -> Optional[str]:
        """Resposta dentro da janela de 24 h: texto livre. Alerta proativo (fora da janela): precisa de TEMPLATE aprovado
        pela Meta, com 1 variável no corpo; o nome vem de WHATSAPP_TEMPLATE_NAME (código de verificação:
        WHATSAPP_CODE_TEMPLATE_NAME; convite: WHATSAPP_INVITE_TEMPLATE_NAME; sem eles cai no geral). Variável não aceita
        quebra de linha."""
        by_purpose = {"code": "WHATSAPP_CODE_TEMPLATE_NAME", "invite": "WHATSAPP_INVITE_TEMPLATE_NAME"}.get(purpose or "")
        tpl = (os.getenv(by_purpose) if by_purpose else None) or os.getenv("WHATSAPP_TEMPLATE_NAME")
        if proactive and tpl:
            flat = " | ".join(x.strip() for x in text.splitlines() if x.strip())
            return self._post({"to": phone, "type": "template", "template": {
                "name": tpl, "language": {"code": os.getenv("WHATSAPP_TEMPLATE_LANG", "pt_BR")},
                "components": [{"type": "body", "parameters": [{"type": "text", "text": flat[:1000]}]}]}})
        mid = self._post({"to": phone, "type": "text", "text": {"body": text, "preview_url": True}})
        if media_url:
            self._post({"to": phone, "type": "image", "image": {"link": media_url}})
        return mid


class OpenWAChannel:
    """WhatsApp por um gateway OpenWA (MIT, github.com/rmyndharis/OpenWA) com um número dedicado pareado pelo QR.
    NÃO é a API oficial: serve para a demonstração e para a avaliação, com quem já mandou mensagem ao número. Não há
    template: o aviso proativo sai como texto (o risco de bloqueio do número é do gateway; veja docs/CANAIS_REAIS.md)."""
    name = "whatsapp"

    def __init__(self):
        self.base = os.environ["OPENWA_URL"].rstrip("/")
        self.session = os.environ["OPENWA_SESSION"]
        self.headers = {"X-API-Key": os.environ["OPENWA_API_KEY"]}

    def _url(self, path: str) -> str:
        return f"{self.base}/api/sessions/{self.session}/{path}"

    def chat_id(self, phone: str) -> str:
        """Id do chat no WhatsApp. Pergunta ao gateway o id canônico (celular do Brasil pode estar com ou sem o 9);
        se a consulta falhar, usa os dígitos como estão."""
        digits = phone_digits(phone)
        try:
            r = requests.get(self._url(f"contacts/check/{digits}"), headers=self.headers, timeout=10)
            if r.ok:
                wid = r.json().get("whatsappId")
                if wid:
                    return wid
                raise ChannelNotConfigured(f"o número ...{digits[-4:]} não tem WhatsApp")
        except requests.RequestException:
            pass
        return f"{digits}@c.us"

    def send(self, phone: str, text: str, media_url: Optional[str] = None, proactive: bool = False,
             purpose: Optional[str] = None) -> Optional[str]:
        chat = self.chat_id(phone)
        r = requests.post(self._url("messages/send-text"), headers=self.headers, timeout=20,
                          json={"chatId": chat, "text": text[:4096]})
        r.raise_for_status()
        mid = r.json().get("messageId")
        if media_url:  # a imagem vai em base64: o gateway não precisa alcançar o BALK (nem localhost, que ele bloqueia)
            try:
                img = requests.get(media_url, timeout=15)
                img.raise_for_status()
                requests.post(self._url("messages/send-image"), headers=self.headers, timeout=30,
                              json={"chatId": chat, "base64": base64.b64encode(img.content).decode(),
                                    "mimetype": img.headers.get("content-type", "image/png").split(";")[0],
                                    "filename": "mapa.png"}).raise_for_status()
            except requests.RequestException as e:  # o texto (com o link) já foi: a imagem é um extra
                log.warning("imagem não enviada pelo OpenWA: %s", type(e).__name__)
        return mid


class SmsGateChannel:
    """SMS por um Android com chip, com o app "SMS Gateway for Android" (Apache-2.0, github.com/capcom6/android-sms-gateway).
    SMSGATE_URL: servidor na nuvem do app (https://api.sms-gate.app/3rdparty/v1) ou o servidor local do aparelho
    (http://IP-do-celular:8080). Usuário e senha aparecem no app. Cada SMS custa o que a operadora do chip cobra."""
    name = "sms"

    def send(self, phone: str, text: str, media_url: Optional[str] = None, proactive: bool = False,
             purpose: Optional[str] = None) -> Optional[str]:
        base = os.environ["SMSGATE_URL"].rstrip("/")
        r = requests.post(f"{base}/message", timeout=20, auth=(os.environ["SMSGATE_USER"], os.environ["SMSGATE_PASSWORD"]),
                          json={"textMessage": {"text": text}, "phoneNumbers": ["+" + phone_digits(phone)]})
        r.raise_for_status()
        return (r.json() or {}).get("id")


def phone_digits(phone: str) -> str:
    """A Meta quer o número só com dígitos (sem +, espaços ou traços)."""
    return "".join(c for c in phone if c.isdigit())


def get_channel(name: str):
    if name == "whatsapp" and os.getenv("OPENWA_URL"):
        return OpenWAChannel()
    if name == "sms" and os.getenv("SMSGATE_URL"):
        return SmsGateChannel()
    if config.data_mode() == "simulado":
        return ConsoleChannel(name)
    if name == "sms" and os.getenv("TWILIO_ACCOUNT_SID"):
        return SmsChannel()
    if name == "whatsapp" and os.getenv("WHATSAPP_TOKEN"):
        return WhatsAppChannel()
    if config.is_production():
        raise ChannelNotConfigured(f"canal '{name}' sem credenciais em produção")
    return ConsoleChannel(name)
