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


def _area(p) -> float:
    """Área do produtor: soma dos talhões desenhados; senão a da última análise; senão o círculo padrão (premissa)."""
    plots = db.list_plots(p.id)
    if plots:
        return sum(x["area_ha"] for x in plots)
    last = db.last_analysis(p.id) or {}
    return (last.get("stats") or {}).get("area_ha") or DEFAULT_AREA_HA


def coop_forecast(coop_id: str, now: Optional[datetime] = None, days: int = 7) -> dict:
    now = now or datetime.now()
    today = now.date()
    crops = load_crops()
    cfg = config.rules()["logistica"]
    items, waiting = [], []
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
                waiting.append({"produtor": p.id, "cultura": p.crop, "t": round(_area(p) * crop["produtividade_t_ha"], 1)})
                continue  # pronta, mas sem janela seca nas próximas 72 h: entra quando a janela aparecer
            day = today + timedelta(days=a.evidence["dia_offset"])
        items.append({"dia": day, "t": _area(p) * crop["produtividade_t_ha"], "produtor": p.id})
    rows = aggregate(items, today, days, cfg["capacidade_caminhao_t"])
    return {"cooperativa": coop_id, "dias": rows, "total_toneladas": round(sum(r["toneladas"] for r in rows), 1),
            "aguardando_janela": waiting, "aguardando_toneladas": round(sum(w["t"] for w in waiting), 1),
            "premissas": f"produtividade média por cultura (crops.yaml, premissa) e caminhão de {cfg['capacidade_caminhao_t']} t; "
                         "janela de colheita prevista com clima das próximas 72 h"}
