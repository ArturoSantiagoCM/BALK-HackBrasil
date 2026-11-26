"""M7: previsão de recebimento da cooperativa (toneladas e caminhões por dia, próximos 7 dias)."""
import math
from datetime import date, datetime, timedelta
from typing import Optional

from app import config, db
from app.alerts.rules import evaluate_harvest
from app.data.weather import get_weather
from app.viability import load_crops

DEFAULT_AREA_HA = 7.0  # círculo de análise; trocar pela área real do talhão quando houver


def aggregate(items: list[dict], today: date, days: int = 7, truck_t: float = 30.0) -> list[dict]:
    """items: [{"dia": date, "t": toneladas, "produtor": id}] -> linha por dia com toneladas e caminhões."""
    rows = []
    for d in range(days):
        day = today + timedelta(days=d)
        sel = [i for i in items if i["dia"] == day]
        tons = sum(i["t"] for i in sel)
        rows.append({"data": day.isoformat(), "toneladas": round(tons, 1), "caminhoes": math.ceil(tons / truck_t) if tons else 0,
                     "produtores": len(sel)})
    return rows


def coop_forecast(coop_id: str, now: Optional[datetime] = None, days: int = 7) -> dict:
    now = now or datetime.now()
    today = now.date()
    crops = load_crops()
    cfg = config.rules()["logistica"]
    items = []
    for p in db.list_by_source(coop_id):
        if not p.crop or not p.planting_date or p.crop not in crops:
            continue
        crop = crops[p.crop]
        ready = datetime.fromisoformat(p.planting_date).date() + timedelta(days=crop["ciclo_dias"])
        if ready > today + timedelta(days=days - 1):
            continue
        if ready > today:
            day = ready
        else:  # já pronta: usa a primeira janela seca prevista
            a = evaluate_harvest(p, get_weather(p.lat, p.lon, now), now=now, crops=crops)
            if not a or a.evidence.get("modo") != "janela":
                continue
            day = today + timedelta(days=a.evidence["dia_offset"])
        last = db.last_analysis(p.id) or {}
        area = (last.get("stats") or {}).get("area_ha") or DEFAULT_AREA_HA
        items.append({"dia": day, "t": area * crop["produtividade_t_ha"], "produtor": p.id})
    rows = aggregate(items, today, days, cfg["capacidade_caminhao_t"])
    return {"cooperativa": coop_id, "dias": rows, "total_toneladas": round(sum(r["toneladas"] for r in rows), 1),
            "premissas": f"produtividade média por cultura (crops.yaml, premissa) e caminhão de {cfg['capacidade_caminhao_t']} t; "
                         "janela de colheita prevista com clima das próximas 72 h"}
