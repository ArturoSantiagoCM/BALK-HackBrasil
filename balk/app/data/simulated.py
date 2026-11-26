"""Dados fixos (source="simulado") para os módulos integrarem sem esperar a internet.

Os 3 pontos de demo são áreas verdes públicas, sem proprietário (coordenadas aproximadas).
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import Affine

DEMO_POINTS = {
    "ibirapuera": {"nome": "Parque Ibirapuera (SP)", "lat": -23.5874, "lon": -46.6576, "cenario": "bom"},
    "pnb": {"nome": "Parque Nacional de Brasília (DF)", "lat": -15.7347, "lon": -48.0152, "cenario": "chuva_vento"},
    "aparados": {"nome": "Parque Nacional de Aparados da Serra (RS/SC)", "lat": -29.1739, "lon": -50.0967,
                 "cenario": "geada"},
}


def scenario_for(lat: float, lon: float) -> str:
    """Cenário do ponto de demo mais próximo (< ~5 km); senão 'bom'."""
    for p in DEMO_POINTS.values():
        if abs(p["lat"] - lat) < 0.05 and abs(p["lon"] - lon) < 0.05:
            return p["cenario"]
    return "bom"


def _hour(base: datetime, i: int) -> str:
    return (base + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00")


def scenario_weather(scenario: str, now: datetime) -> list[dict]:
    """72 horas de clima fixo. Unidades: °C, %, %, mm, km/h, mm."""
    base = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    rows = []
    for i in range(72):
        t = base + timedelta(hours=i)
        h = t.hour
        day = i // 24  # 0 = hoje (a partir da próxima hora)
        temp = 18 + 8 * np.sin((h - 9) / 24 * 2 * np.pi)  # mín ~14 às 3h, máx ~22-26 às 15h
        rh, rain_p, rain, wind = 70.0, 10.0, 0.0, 6.0
        if scenario == "geada":
            temp = temp - 4  # clima frio geral
            if 12 <= i < 36 and 3 <= h <= 7:  # a próxima madrugada (normalmente "amanhã")
                temp = 2.0
        if scenario == "chuva_vento":
            if i < 48:
                rain_p, wind, rh = 80.0, 22.0, 90.0
                if 12 <= h <= 20:
                    rain = 4.0
            else:  # a partir do 3º dia o tempo abre
                rain_p, wind, rh = 10.0, 6.0, 65.0
        rows.append({"time": t.strftime("%Y-%m-%dT%H:00"), "temp": round(float(temp), 1), "rh": rh,
                     "rain_prob": rain_p, "rain_mm": rain, "wind_kmh": wind,
                     "et0": round(float(max(0.0, 0.25 * np.sin((h - 6) / 12 * np.pi))), 2)})
    return rows


def simulated_climate(lat: float) -> dict:
    """Climatologia mensal fixa (média de 5 anos) em função da latitude."""
    monthly = {}
    for m in range(1, 13):
        season = np.cos((m - 1) / 12 * 2 * np.pi)  # 1 em jan (verão no hemisfério sul)
        temp = 22 - abs(lat) * 0.15 + 3 * season * (-1 if lat > 0 else 1) - 0.0
        rain = 130 + 90 * season * (-1 if lat > 0 else 1)
        monthly[m] = {"temp": round(float(temp), 1), "rain": round(float(max(rain, 5.0)), 1)}
    return {"monthly": monthly, "years": 5, "source": "simulado"}


def utm_epsg(lat: float, lon: float) -> int:
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


def make_synthetic_package(out: Path, lat: float, lon: float, seed: int = 0, clay: bool = True,
                           slope_pct: float = 6.0, today: datetime | None = None) -> Path:
    """Gera red/nir/scl (UTM, 10 m, 1 km), dem (EPSG:4326, ~30 m) e clay.tif + meta.json."""
    today = today or datetime.now()
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed + int(abs(lat * 1000)))
    epsg = utm_epsg(lat, lon)
    x, y = Transformer.from_crs(4326, epsg, always_xy=True).transform(lon, lat)
    n = 100
    tr = Affine(10, 0, x - 500, 0, -10, y + 500)
    base = dict(driver="GTiff", height=n, width=n, count=1, crs=f"EPSG:{epsg}", transform=tr)

    veg = 0.55 + 0.25 * np.exp(-(((np.arange(n)[:, None] - 50) ** 2 + (np.arange(n)[None, :] - 50) ** 2) / 1800))
    ndvi = np.clip(veg + rng.normal(0, 0.03, (n, n)), 0.1, 0.92)
    red = np.clip(0.2 * (1 - ndvi) / (1 + ndvi) * 2, 0.01, 0.5).astype("float32")
    nir = (red * (1 + ndvi) / (1 - ndvi)).astype("float32")
    scl = np.full((n // 2, n // 2), 4, dtype="uint8")  # SCL em 20 m (50x50)
    scl[:6, :6] = 9  # canto com nuvem
    with rasterio.open(out / "red.tif", "w", dtype="float32", **base) as d:
        d.write(red, 1)
    with rasterio.open(out / "nir.tif", "w", dtype="float32", **base) as d:
        d.write(nir, 1)
    scl_tr = Affine(20, 0, x - 500, 0, -20, y + 500)
    with rasterio.open(out / "scl.tif", "w", driver="GTiff", height=n // 2, width=n // 2, count=1, dtype="uint8",
                       crs=f"EPSG:{epsg}", transform=scl_tr) as d:
        d.write(scl, 1)

    # DEM ~30 m em graus: plano inclinado para o norte com a declividade pedida
    step = 30 / 111320.0
    m = 44
    dem_tr = Affine(step, 0, lon - m / 2 * step, 0, -step, lat + m / 2 * step)
    rows = np.arange(m)[:, None] * np.ones((1, m))
    dem = (700 + (m - rows) * 30 * slope_pct / 100).astype("float32")
    with rasterio.open(out / "dem.tif", "w", driver="GTiff", height=m, width=m, count=1, dtype="float32",
                       crs="EPSG:4326", transform=dem_tr) as d:
        d.write(dem, 1)

    has_clay = False
    if clay:
        cstep = 250 / 111320.0
        c_tr = Affine(cstep, 0, lon - 4 * cstep, 0, -cstep, lat + 4 * cstep)
        with rasterio.open(out / "clay.tif", "w", driver="GTiff", height=8, width=8, count=1, dtype="float32",
                           crs="EPSG:4326", transform=c_tr) as d:
            d.write(np.full((8, 8), 38.0, dtype="float32"), 1)  # em %, não g/kg
        has_clay = True

    (out / "meta.json").write_text(json.dumps({
        "scene_date": (today - timedelta(days=5)).strftime("%Y-%m-%d"), "source": "simulado",
        "clay": has_clay, "created": today.isoformat(timespec="seconds")}), encoding="utf-8")
    return out
