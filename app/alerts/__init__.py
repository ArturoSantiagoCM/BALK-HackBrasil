"""M5: evaluate(producer, weather, stats) -> list[Alert] já filtrados pelo silêncio."""
from datetime import datetime
from typing import Optional

from app import db
from app.alerts.rules import evaluate_frost, evaluate_harvest, evaluate_spraying, evaluate_stress
from app.alerts.silence import filter_by_silence
from app.models import Alert, Producer, SpatialStats, Weather


def evaluate(producer: Producer, weather: Weather, stats: Optional[SpatialStats], now: Optional[datetime] = None,
             log: Optional[list[dict]] = None, ndvi_history: Optional[dict] = None) -> list[Alert]:
    now = now or datetime.now()
    offset = (stats.frost_relief_offset_c if stats and stats.frost_relief_offset_c is not None else 0.0)
    candidates = [evaluate_spraying(weather, now=now), evaluate_frost(weather, now=now, relief_offset_c=offset),
                  evaluate_harvest(producer, weather, now=now)]
    if producer.location_precision == "ponto":  # NDVI só faz sentido com o ponto da lavoura
        candidates.append(evaluate_stress(stats, ndvi_history))
    if log is None:
        log = db.get_alert_log(producer.id) if producer.id else []
    return filter_by_silence([a for a in candidates if a], producer, log, now)
