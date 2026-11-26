"""Entrega de mensagens: registra, tenta de novo com recuo e, se o WhatsApp falhar, cai para SMS.

Toda mensagem enviada fica na tabela `messages` (conteúdo, estado, id do provedor, erro). O estado final é:
sent (aceita pelo provedor), failed (todas as tentativas falharam), e depois o provedor avisa delivered/read por webhook.
"""
import logging
import time
from typing import Optional

from app import db
from app.channels import get_channel
from app.security import mask_phone

log = logging.getLogger("balk.delivery")
RETRIES = 2
BACKOFF_S = 1.0


def deliver(producer_id: Optional[int], phone: str, channel: str, text: str, *, kind: str, type_: Optional[str] = None,
            confidence: Optional[str] = None, evidence: Optional[dict] = None, report_token: Optional[str] = None,
            media_url: Optional[str] = None, proactive: bool = False, sms_text: Optional[str] = None,
            log_text: Optional[str] = None, purpose: Optional[str] = None) -> dict:
    """Envia `text` pelo `channel`. Devolve {ok, channel (o que de fato foi usado), message_id, error}.

    `log_text`: o que fica gravado em `messages` quando o texto enviado tem segredo (ex.: o código de verificação).
    `purpose`: "code" ou "invite" escolhe o template do WhatsApp próprio da finalidade (fora da janela de 24 h)."""
    mid = db.log_message(producer_id, phone, "out", channel, kind, log_text or text, type_, confidence, evidence, report_token)
    extra = {"purpose": purpose} if purpose else {}
    err = ""
    for attempt in range(RETRIES):
        try:
            pid = get_channel(channel).send(phone, text, media_url, proactive=proactive, **extra)
            db.update_message(mid, state="sent", provider_id=pid)
            return {"ok": True, "channel": channel, "message_id": mid, "error": ""}
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:300]
            log.warning("falha de envio (%s, tentativa %d) para %s: %s", channel, attempt + 1, mask_phone(phone), err)
            if attempt + 1 < RETRIES:
                time.sleep(BACKOFF_S * (2 ** attempt))
    if channel == "whatsapp" and sms_text:  # reserva: o aviso importante não pode morrer só porque o WhatsApp falhou
        try:
            pid = get_channel("sms").send(phone, sms_text, None, proactive=True, **extra)
            db.update_message(mid, state="sent", provider_id=pid, channel="sms", error=f"whatsapp falhou ({err}); enviado por SMS")
            return {"ok": True, "channel": "sms", "message_id": mid, "error": err}
        except Exception as e:  # noqa: BLE001
            err += f" | SMS: {type(e).__name__}: {e}"[:200]
    db.update_message(mid, state="failed", error=err)
    return {"ok": False, "channel": channel, "message_id": mid, "error": err}
