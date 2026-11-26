"""Canais trocáveis: ConsoleChannel (simulador), SmsChannel (Twilio) e WhatsAppChannel (Meta Cloud API).

Todos implementam send(phone, text). Os dois reais NÃO foram testados com contas de verdade (sem chaves);
só são usados quando as variáveis do .env existem e DATA_MODE != simulado.
"""
import os
from typing import Optional

import requests

from app import config

OUTBOX: list[dict] = []  # mensagens "enviadas" pelo ConsoleChannel (o simulador web lê daqui)


class ConsoleChannel:
    name = "console"

    def send(self, phone: str, text: str, media_url: Optional[str] = None) -> None:
        OUTBOX.append({"to": phone, "text": text, "media_url": media_url})


class SmsChannel:
    name = "sms"

    def send(self, phone: str, text: str, media_url: Optional[str] = None) -> None:
        sid, token = os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]
        r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", timeout=10,
                          auth=(sid, token), data={"To": phone, "From": os.environ["TWILIO_FROM"], "Body": text})
        r.raise_for_status()


class WhatsAppChannel:
    name = "whatsapp"

    def send(self, phone: str, text: str, media_url: Optional[str] = None) -> None:
        # Fora da janela de 24 h só vale template aprovado pela Meta; aqui vai texto livre (resposta ao produtor).
        r = requests.post(f"https://graph.facebook.com/v21.0/{os.environ['WHATSAPP_PHONE_ID']}/messages", timeout=10,
                          headers={"Authorization": f"Bearer {os.environ['WHATSAPP_TOKEN']}"},
                          json={"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"body": text}})
        r.raise_for_status()


def get_channel(name: str):
    if config.data_mode() == "simulado":
        return ConsoleChannel()
    if name == "sms" and os.getenv("TWILIO_ACCOUNT_SID"):
        return SmsChannel()
    if name == "whatsapp" and os.getenv("WHATSAPP_TOKEN"):
        return WhatsAppChannel()
    return ConsoleChannel()
