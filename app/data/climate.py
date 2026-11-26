"""M2: histórico climático (5 anos) e agregação para a época de cada cultura."""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

import requests

from app import config, db
from app.data import simulated

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def monthly_from_daily(times: list[str], temps: list, rains: list, tmins: Optional[list] = None,
                       frost_c: float = 3.0) -> dict:
    """Média de temperatura por mês, chuva mensal média entre os anos (mm) e, se houver mínimas diárias,
    dias de geada por mês (média entre os anos: dias com mínima <= frost_c)."""
    t_by_m = defaultdict(list)
    r_by_ym = defaultdict(float)
    years_of_m = defaultdict(set)
    frost_by_m = defaultdict(int)
    for i, (t, tm, r) in enumerate(zip(times, temps, rains)):
        y, m = int(t[:4]), int(t[5:7])
        if tm is not None:
            t_by_m[m].append(tm)
        if r is not None:
            r_by_ym[(y, m)] += r
        years_of_m[m].add(y)
        if tmins is not None and tmins[i] is not None and tmins[i] <= frost_c:
            frost_by_m[m] += 1
    out = {}
    for m in range(1, 13):
        if not t_by_m[m]:
            continue
        n_years = max(len(years_of_m[m]), 1)
        rain = sum(v for (y, mm), v in r_by_ym.items() if mm == m) / n_years
        out[m] = {"temp": round(sum(t_by_m[m]) / len(t_by_m[m]), 1), "rain": round(rain, 1)}
        if tmins is not None:
            out[m]["frost_days"] = round(frost_by_m[m] / n_years, 1)
    return out


def get_climate_history(lat: float, lon: float, years: int = 5, today: Optional[datetime] = None) -> dict:
    """Devolve {"monthly": {1..12: {temp, rain}}, "years", "source"}."""
    today = today or datetime.now()
    mode = config.data_mode()
    if mode == "simulado":
        return simulated.simulated_climate(lat)
    key = f"clim:{lat:.2f}:{lon:.2f}:{years}"
    cached = db.cache_get(key, max_age_s=30 * 86400)
    if cached:
        return {**cached, "source": "cache"}
    try:
        end = today - timedelta(days=7)  # o arquivo tem alguns dias de atraso
        start = end - timedelta(days=365 * years)
        r = requests.get(ARCHIVE_URL, params={
            "latitude": lat, "longitude": lon, "start_date": start.strftime("%Y-%m-%d"),
            "end_date": end.strftime("%Y-%m-%d"),
            "daily": "temperature_2m_mean,precipitation_sum,temperature_2m_min", "timezone": "auto"}, timeout=10)
        r.raise_for_status()
        d = r.json()["daily"]
        res = {"monthly": monthly_from_daily(d["time"], d["temperature_2m_mean"], d["precipitation_sum"],
                                             d.get("temperature_2m_min"), config.rules()["geada"]["tmin"]),
               "years": years, "source": "open-meteo-archive"}
        db.cache_set(key, res)
        return res
    except Exception:
        if mode == "auto":
            return simulated.simulated_climate(lat)
        raise


def season_stats(climate: dict, start_month: int, months: int) -> tuple[Optional[float], Optional[float]]:
    """Temperatura média e chuva total do ciclo (meses a partir de start_month). None se faltar dado."""
    monthly = {int(k): v for k, v in climate["monthly"].items()}
    temps, rain = [], 0.0
    for i in range(months):
        m = (start_month - 1 + i) % 12 + 1
        if m not in monthly:
            return None, None
        temps.append(monthly[m]["temp"])
        rain += monthly[m]["rain"]
    return sum(temps) / len(temps), rain


def season_frost_days(climate: dict, start_month: int, months: int) -> Optional[float]:
    """Dias de geada esperados no ciclo (histórico). None se o histórico não trouxe as mínimas diárias."""
    monthly = {int(k): v for k, v in climate["monthly"].items()}
    total = 0.0
    for i in range(months):
        m = (start_month - 1 + i) % 12 + 1
        if m not in monthly or "frost_days" not in monthly[m]:
            return None
        total += monthly[m]["frost_days"]
    return total


def mean_monthly_rain(climate: Optional[dict]) -> Optional[float]:
    """Chuva mensal média do ano (mm), usada como referência de erosividade."""
    if not climate or not climate.get("monthly"):
        return None
    v = [m["rain"] for m in climate["monthly"].values()]
    return sum(v) / len(v)
