"""M2: clima. get_weather devolve Weather (72 h) do Open-Meteo, com cache e reserva."""
import time
from datetime import datetime
from typing import Optional

import requests

from app import config, db
from app.data import simulated
from app.models import Weather

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY = ("temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,"
          "wind_speed_10m,et0_fao_evapotranspiration")


def parse_open_meteo(payload: dict, now: Optional[datetime] = None, n_hours: int = 72) -> list[dict]:
    """Converte a resposta JSON do Open-Meteo em linhas do contrato Weather.

    Horários vêm no fuso do ponto (timezone=auto); vento em km/h (pedido explicitamente).
    """
    h = payload["hourly"]
    now = now or datetime.now()
    floor = now.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00")
    rows = []
    for i, t in enumerate(h["time"]):
        if t < floor:
            continue
        temp, rh = h["temperature_2m"][i], h["relative_humidity_2m"][i]
        if temp is None or rh is None:
            continue
        g = lambda k: (h.get(k) or [None] * len(h["time"]))[i] or 0.0  # noqa: E731
        rows.append({"time": t, "temp": temp, "rh": rh, "rain_prob": g("precipitation_probability"),
                     "rain_mm": g("precipitation"), "wind_kmh": g("wind_speed_10m"),
                     "et0": g("et0_fao_evapotranspiration")})
        if len(rows) == n_hours:
            break
    return rows


def _fetch(lat: float, lon: float, now: datetime) -> list[dict]:
    params = {"latitude": lat, "longitude": lon, "hourly": HOURLY, "forecast_days": 4,  # 4 dias: garante 72 h à frente em qualquer hora do dia
              "timezone": "auto", "wind_speed_unit": "kmh"}
    last_err: Exception | None = None
    for attempt in range(2):  # uma nova tentativa
        try:
            r = requests.get(FORECAST_URL, params=params, timeout=10)
            r.raise_for_status()
            rows = parse_open_meteo(r.json(), now)
            if rows:
                return rows
            raise ValueError("resposta sem horas")
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(0.5)
    raise RuntimeError(f"Open-Meteo falhou: {last_err}")


def get_weather(lat: float, lon: float, now: Optional[datetime] = None) -> Weather:
    now = now or datetime.now()
    mode = config.data_mode()
    sim = lambda: Weather(hours=simulated.scenario_weather(simulated.scenario_for(lat, lon), now),  # noqa: E731
                          source="simulado")
    if mode == "simulado":
        return sim()
    key = f"wx:{lat:.2f}:{lon:.2f}"
    hour_key = f"{key}:{now:%Y-%m-%dT%H}"
    cached = db.cache_get(hour_key, max_age_s=3600)  # cache de 1 hora por ponto
    if cached:
        return Weather(hours=cached["hours"], source="cache")
    try:
        rows = _fetch(lat, lon, now)
        db.cache_set(hour_key, {"hours": rows})
        db.cache_set(key + ":last", {"hours": rows})
        return Weather(hours=rows, source="open-meteo")
    except Exception:
        last = db.cache_get(key + ":last")  # último valor salvo como reserva
        if last:
            return Weather(hours=last["hours"], source="cache")
        if mode == "auto":
            return sim()
        raise
