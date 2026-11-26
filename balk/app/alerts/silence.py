"""M5: silêncio. Alerta raro vale mais que alerta frequente."""
from datetime import datetime, timedelta
from typing import Optional

from app import config
from app.models import Alert, Producer

PRIORITY = {"geada": 0, "colheita": 1, "estresse": 2, "pulverizacao": 3}
EMERGENCY = {"geada"}  # exceção à cota semanal e ao horário quieto


def filter_by_silence(alerts: list[Alert], producer: Producer, log: list[dict], now: Optional[datetime] = None,
                      cfg: Optional[dict] = None) -> list[Alert]:
    """Corta: mesmo tipo nas últimas 72 h; mais de 2 por semana; horário quieto (20h-6h); duplicados do dia."""
    c = cfg or config.rules()["silencio"]
    now = now or datetime.now()
    sent = [(e["type"], datetime.fromisoformat(e["sent_at"])) for e in log]
    week = sum(1 for _, dt in sent if now - dt <= timedelta(days=7))
    quiet = now.hour >= c["quieto_das"] or now.hour < c["quieto_ate"]
    out, seen = [], set()
    for a in sorted(alerts, key=lambda x: PRIORITY[x.type]):
        if a.type in seen:  # alertas parecidos no mesmo dia viram um só
            continue
        seen.add(a.type)
        if any(t == a.type and now - dt < timedelta(hours=c["pausa_horas"]) for t, dt in sent):
            continue
        if a.type not in EMERGENCY:
            if week + len(out) >= c["max_por_semana"]:
                continue
            if quiet:
                continue
        out.append(a)
    return out
