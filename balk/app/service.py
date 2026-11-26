"""Orquestra M2..M6 para um produtor: análise espacial, viabilidade, alertas e mensagens prontas."""
import os
from datetime import datetime
from typing import Optional

from app import db
from app.alerts import evaluate
from app.channels import get_channel
from app.data.climate import get_climate_history
from app.data.package import build_local_package
from app.data.weather import get_weather
from app.engine import analyze
from app.engine.mapa import render_map
from app.message import render
from app.message.templates import Report
from app.viability import rank_crops


def _use_ai() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY")) and os.getenv("USE_AI_POLISH", "1") == "1"


def analyze_producer(pid: int, full: bool = True, now: Optional[datetime] = None) -> dict:
    """Roda M3 e M4 (se o local é um ponto), M5 e M6. Não registra alertas: quem envia chama /alerts/log."""
    now = now or datetime.now()
    p = db.get_producer(pid)
    if p is None:
        raise KeyError(pid)
    weather = get_weather(p.lat, p.lon, now)
    stats, ranking, map_url = None, [], None
    if p.location_precision == "ponto":
        stats = analyze(p)
        climate = get_climate_history(p.lat, p.lon, today=now)
        month = int(p.planting_date[5:7]) if p.planting_date else None
        ranking = rank_crops(stats, climate, crop_pref=p.crop, planting_month=month, today=now)
        if full:
            render_map(build_local_package(p), p.lat, p.lon, ranking)
            map_url = f"/maps/{p.id}.png"
    alerts = evaluate(p, weather, stats, now=now)
    messages = []
    if full:
        rep = Report(ranking=ranking, stats=stats, crop_pref=p.crop, map_url=map_url, only_weather=stats is None)
        messages.append({"kind": "report", "type": "relatorio", "text": render(rep, p.channel, p.lang),
                         "media_url": map_url if p.channel == "whatsapp" else None})
    for a in alerts:
        messages.append({"kind": "alert", "type": a.type, "text": render(a, p.channel, p.lang, use_ai=_use_ai())})
    result = {"producer_id": p.id, "phone": p.phone, "channel": p.channel, "lang": p.lang,
              "location_precision": p.location_precision, "weather_source": weather.source,
              "stats": stats.model_dump() if stats else None, "ranking": [v.model_dump() for v in ranking],
              "alerts": [a.model_dump() for a in alerts], "map_url": map_url, "messages": messages}
    db.save_analysis(p.id, result)
    return result


def run_daily(now: Optional[datetime] = None) -> list[dict]:
    """O que o WF2 (n8n, 06:05) faz: para cada produtor ativo, analisa, envia pelo canal e registra o alerta."""
    now = now or datetime.now()
    sent = []
    for p in db.list_active():
        res = analyze_producer(p.id, full=False, now=now)
        for a, m in zip(res["alerts"], [m for m in res["messages"] if m["kind"] == "alert"]):
            get_channel(p.channel).send(p.phone, m["text"])
            db.log_alert(p.id, a["type"], now.isoformat(timespec="seconds"))
            sent.append({"producer_id": p.id, "phone": p.phone, "channel": p.channel, "type": a["type"],
                         "text": m["text"], "confidence": a["confidence"]})
    return sent
