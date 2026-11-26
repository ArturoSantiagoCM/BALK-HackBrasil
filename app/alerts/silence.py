"""M5: silêncio. Alerta raro vale mais que alerta frequente."""
from datetime import datetime, timedelta
from typing import Optional

from app import config
from app.models import Alert, Producer

PRIORITY = {"geada": 0, "colheita": 1, "estresse": 2, "pulverizacao": 3}
EMERGENCY = {"geada"}  # exceção à cota semanal, à cota diária e ao horário quieto


def filter_by_silence(alerts: list[Alert], producer: Producer, log: list[dict], now: Optional[datetime] = None,
                      cfg: Optional[dict] = None, cap_log: Optional[list[dict]] = None, already: int = 0) -> list[Alert]:
    """Corta: mesmo tipo nas últimas 72 h NO MESMO TALHÃO (`log`); mais de 2 por semana e mais de N por dia POR CONTATO, somando
    todos os talhões (`cap_log`; padrão = `log`); horário quieto (20h-6h); duplicados do dia. `already` = alertas não urgentes
    já aceitos nesta rodada para outros talhões do mesmo produtor."""
    c = cfg or config.rules()["silencio"]
    now = now or datetime.now()
    sent = [(e["type"], datetime.fromisoformat(e["sent_at"])) for e in log]
    cap = [(e["type"], datetime.fromisoformat(e["sent_at"])) for e in (cap_log if cap_log is not None else log)]
    week = sum(1 for _, dt in cap if now - dt <= timedelta(days=7))
    day = sum(1 for _, dt in cap if dt.date() == now.date())
    quiet = now.hour >= c["quieto_das"] or now.hour < c["quieto_ate"]
    out, seen = [], set()
    for a in sorted(alerts, key=lambda x: PRIORITY[x.type]):
        if a.type in seen:  # alertas parecidos no mesmo dia viram um só
            continue
        seen.add(a.type)
        if any(t == a.type and now - dt < timedelta(hours=c["pausa_horas"]) for t, dt in sent):
            continue
        if a.type not in EMERGENCY:
            if week + already + len(out) >= c["max_por_semana"]:
                continue
            if day + already + len(out) >= c.get("max_por_dia", 99):  # limite diário por contato
                continue
            if quiet:
                continue
        out.append(a)
    return out
