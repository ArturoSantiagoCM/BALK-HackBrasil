"""M7: colheita e escoamento. Melhor hora de saída com menos chuva na rota, e frete estimado."""
import json
import math
from datetime import datetime, timedelta
from typing import Optional

import requests

from app import config
from app.data.weather import get_weather
from app.models import Producer, Weather

OSRM = "https://router.project-osrm.org/route/v1/driving"  # servidor de demonstração: não é para produção


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def sample_route(coords: list, step_km: float = 20.0) -> list[tuple[float, float, float]]:
    """coords = [[lon, lat], ...] (GeoJSON). Devolve (lat, lon, km_acumulado) a cada step_km, mais o fim."""
    pts = [(c[1], c[0]) for c in coords]
    out = [(pts[0][0], pts[0][1], 0.0)]
    acc, next_mark = 0.0, step_km
    for (la1, lo1), (la2, lo2) in zip(pts, pts[1:]):
        seg = haversine_km(la1, lo1, la2, lo2)
        while seg > 0 and acc + seg >= next_mark:
            f = (next_mark - acc) / seg
            out.append((la1 + (la2 - la1) * f, lo1 + (lo2 - lo1) * f, next_mark))
            next_mark += step_km
        acc += seg
    if acc - out[-1][2] > 0.5:  # inclui o destino, sem duplicar se já caiu num marco
        out.append((pts[-1][0], pts[-1][1], acc))
    return out


def best_departure(route_points: list, weather_by_point: list[Weather], hours_ahead: int = 48,
                   speed_kmh: float = 60.0) -> dict:
    """Hora de saída com menor chuva acumulada ao longo da rota (chuva na hora em que o caminhão passa)."""
    n = min(len(w.hours) for w in weather_by_point)
    results = []
    for i in range(min(hours_ahead, n)):
        total, missing = 0.0, False
        for (lat, lon, km), w in zip(route_points, weather_by_point):
            idx = i + int(round(km / speed_kmh))
            if idx >= len(w.hours):
                missing = True
                break
            total += w.hours[idx]["rain_mm"]
        if not missing:
            results.append((total, i))
    if not results:  # previsão curta demais: usa a saída imediata
        results = [(0.0, 0)]
    best = min(results, key=lambda r: (r[0], r[1]))
    worst = max(results, key=lambda r: (r[0], -r[1]))
    t0 = weather_by_point[0].hours[best[1]]["time"]
    return {"saida": t0, "chuva_mm": round(best[0], 1), "pior_saida": weather_by_point[0].hours[worst[1]]["time"],
            "pior_mm": round(worst[0], 1)}


def load_destinations() -> list[dict]:
    return json.loads((config.ROOT / "demo" / "destinos.json").read_text(encoding="utf-8"))


def fetch_route(lat1, lon1, lat2, lon2) -> dict:
    """Rota por estrada (OSRM). Em modo simulado ou sem rede: linha reta x fator (estimativa)."""
    cfg = config.rules()["logistica"]
    if config.data_mode() != "simulado":
        try:
            r = requests.get(f"{OSRM}/{lon1},{lat1};{lon2},{lat2}", params={"overview": "full", "geometries": "geojson"},
                             timeout=10)
            r.raise_for_status()
            route = r.json()["routes"][0]
            return {"coords": route["geometry"]["coordinates"], "dist_km": route["distance"] / 1000,
                    "fonte": "osrm"}
        except Exception:  # noqa: BLE001
            if config.data_mode() == "real":
                raise
    n = 12
    coords = [[lon1 + (lon2 - lon1) * k / n, lat1 + (lat2 - lat1) * k / n] for k in range(n + 1)]
    return {"coords": coords, "dist_km": haversine_km(lat1, lon1, lat2, lon2) * cfg["fator_linha_reta"],
            "fonte": "linha_reta"}


def plan_route(producer: Producer, destination: dict, now: Optional[datetime] = None) -> dict:
    """Melhor saída, chuva na rota e frete estimado."""
    cfg = config.rules()["logistica"]
    now = now or datetime.now()
    route = fetch_route(producer.lat, producer.lon, destination["lat"], destination["lon"])
    pts = sample_route(route["coords"], cfg["passo_km"])
    # a distância por estrada pode passar da soma das amostras: reescala os km para a distância real
    geo = pts[-1][2] or 1.0
    pts = [(la, lo, km * route["dist_km"] / geo) for la, lo, km in pts]
    wx = [get_weather(la, lo, now) for la, lo, _ in pts]
    best = best_departure(pts, wx, 48, cfg["velocidade_kmh"])
    dep = datetime.fromisoformat(best["saida"])
    return {"destino": destination["nome"], "dist_km": round(route["dist_km"]), "duracao_h": round(route["dist_km"] / cfg["velocidade_kmh"], 1),
            "melhor_saida": best["saida"], "hora": dep.hour, "dia_offset": (dep.date() - now.date()).days,
            "weekday": dep.weekday(), "chuva_mm": best["chuva_mm"], "pior_mm": best["pior_mm"],
            "frete_rs": round(route["dist_km"] * cfg["frete_rs_por_km"] + cfg.get("frete_fixo_rs", 0.0)), "rota_fonte": route["fonte"],
            "pontos_amostrados": len(pts),
            "premissas": f"{cfg['velocidade_kmh']} km/h e R$ {cfg['frete_rs_por_km']}/km (a confirmar com a ANTT)"}
