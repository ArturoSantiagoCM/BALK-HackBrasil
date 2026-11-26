"""Entrada de mensagens reais: WhatsApp Cloud API (Meta) e SMS (Twilio). Valida a assinatura antes de qualquer coisa.

STATUS: a lógica de assinatura e de leitura do corpo é testada com cargas de exemplo no formato documentado da Meta e da
Twilio; NUNCA foi exercitada contra as plataformas de verdade (sem conta/chaves neste ambiente). Teste com o número de
teste da Meta e com a conta de teste da Twilio antes de qualquer uso.
"""
import logging
from dataclasses import dataclass
from typing import Optional
from xml.sax.saxutils import escape

from app import db
from app.delivery import deliver
from app.ingest.conversation import handle_message
from app.security import mask_phone
from app.service import analyze_producer

log = logging.getLogger("balk.webhooks")


@dataclass
class Incoming:
    id: str
    phone: str
    text: str
    location: Optional[tuple[float, float]] = None


def parse_meta_payload(payload: dict) -> list[Incoming]:
    """entry[].changes[].value.messages[]: texto, pin de localização e resposta de botão. Ignora status e mídia."""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for m in change.get("value", {}).get("messages", []) or []:
                phone, mid, kind = m.get("from", ""), m.get("id", ""), m.get("type")
                if not phone or not mid:
                    continue
                if kind == "text":
                    out.append(Incoming(mid, phone, m.get("text", {}).get("body", "")))
                elif kind == "location":
                    loc = m.get("location", {})
                    if "latitude" in loc and "longitude" in loc:
                        out.append(Incoming(mid, phone, "", (float(loc["latitude"]), float(loc["longitude"]))))
                elif kind == "button":
                    out.append(Incoming(mid, phone, m.get("button", {}).get("text", "")))
                elif kind == "interactive":
                    it = m.get("interactive", {})
                    reply = it.get("button_reply") or it.get("list_reply") or {}
                    out.append(Incoming(mid, phone, reply.get("title", "")))
    return out


def process_whatsapp(msg: Incoming) -> list[dict]:
    """Uma mensagem recebida -> resposta (e relatório, se o cadastro fechou) enviados pelo canal do WhatsApp."""
    if db.seen_message(msg.id):  # a Meta reenvia o mesmo webhook se demorarmos: processa uma vez só
        return []
    reply = handle_message(msg.phone, msg.text, "whatsapp", location=msg.location)
    db.log_message(reply.producer_id, msg.phone, "in", "whatsapp", "texto" if msg.text else "localizacao",
                   msg.text or "(pin de localização)", provider_id=msg.id, state="received")  # o que chegou, sem o pin exato
    out = [{"text": reply.text, "media_url": None, "kind": "reply", "token": None}]
    if reply.became_active:
        try:
            res = analyze_producer(reply.producer_id, full=True)
            out += [{"text": m["text"], "media_url": m.get("media_url"), "kind": "report", "token": res["report_token"],
                     "sms_text": m.get("sms_text")} for m in res["messages"] if m["kind"] == "report"]
        except Exception:  # noqa: BLE001  (clima fora do ar etc.: o cadastro vale; o relatório vem no próximo ciclo)
            log.exception("primeira análise falhou para %s", mask_phone(msg.phone))
            out.append({"text": "Tive um problema para buscar os dados agora. Seu cadastro está feito e eu aviso assim que conseguir.",
                        "media_url": None, "kind": "reply", "token": None})
    for m in out:
        deliver(reply.producer_id, msg.phone, "whatsapp", m["text"], kind=m["kind"], report_token=m["token"],
                media_url=m["media_url"], sms_text=m.get("sms_text"))
    for phone, text, channel in reply.notify:  # convite ao sucessor: mensagem para OUTRA pessoa, proativa (template)
        deliver(reply.producer_id, phone, channel, text, kind="convite", proactive=True)
    return out


def parse_meta_statuses(payload: dict) -> list[tuple[str, str, Optional[str]]]:
    """entry[].changes[].value.statuses[]: (id da mensagem, estado, erro). Estados da Meta: sent, delivered, read, failed."""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for s in change.get("value", {}).get("statuses", []) or []:
                if s.get("id") and s.get("status"):
                    errs = s.get("errors") or [{}]
                    out.append((s["id"], s["status"], errs[0].get("title") if s["status"] == "failed" else None))
    return out


def twiml(texts: list[str]) -> str:
    """Resposta que a Twilio entrega ao produtor como SMS."""
    return '<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(f"<Message>{escape(t)}</Message>" for t in texts) + "</Response>"
