"""Canais trocáveis: ConsoleChannel (simulador), SmsChannel (Twilio) e WhatsAppChannel (Meta Cloud API).

Todos implementam send(phone, text, media_url, proactive) e devolvem o id da mensagem no provedor (ou None).
Os dois reais NÃO foram testados com contas de verdade (sem chaves). Em produção, canal sem credencial LEVANTA ERRO:
nunca se "envia" para um console que ninguém lê.
"""
import itertools
import os
from typing import Optional

import requests

from app import config

OUTBOX: list[dict] = []  # mensagens "enviadas" pelo ConsoleChannel (o simulador web lê daqui)
_seq = itertools.count(1)


class ChannelNotConfigured(RuntimeError):
    pass


class ConsoleChannel:
    name = "console"

    def send(self, phone: str, text: str, media_url: Optional[str] = None, proactive: bool = False,
             purpose: Optional[str] = None) -> Optional[str]:
        OUTBOX.append({"to": phone, "text": text, "media_url": media_url})
        return f"console-{next(_seq)}"


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


def phone_digits(phone: str) -> str:
    """A Meta quer o número só com dígitos (sem +, espaços ou traços)."""
    return "".join(c for c in phone if c.isdigit())


def get_channel(name: str):
    if config.data_mode() == "simulado":
        return ConsoleChannel()
    if name == "sms" and os.getenv("TWILIO_ACCOUNT_SID"):
        return SmsChannel()
    if name == "whatsapp" and os.getenv("WHATSAPP_TOKEN"):
        return WhatsAppChannel()
    if config.is_production():
        raise ChannelNotConfigured(f"canal '{name}' sem credenciais em produção")
    return ConsoleChannel()
