"""M2: pacote de dados do local -> work/{producer_id}/ (red, nir, scl, dem, clay, meta.json)."""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from app import config
from app.data import simulated
from app.models import Producer

MAX_AGE_H = 24


def _fresh(meta_path: Path, now: datetime, mode_source: str, poly_hash: Optional[str] = None) -> bool:
    if not meta_path.exists():
        return False
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    age_h = (now - datetime.fromisoformat(meta["created"])).total_seconds() / 3600
    return (age_h < MAX_AGE_H and (mode_source == "any" or meta.get("source") == mode_source)
            and meta.get("polygon") == poly_hash)  # talhão novo ou editado: refaz o recorte


def _stamp(meta_path: Path, poly_hash: Optional[str]) -> None:
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["polygon"] = poly_hash
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


def polygon_bbox(polygon: dict, margin_m: float = 150.0, min_half_m: float = 500.0) -> list[float]:
    """Caixa [lon0, lat0, lon1, lat1] que cobre o talhão com margem (no mínimo 1 km de lado, para a vizinhança)."""
    from shapely.geometry import shape
    from app.data.sentinel import bbox_around
    g = polygon.get("geometry") if polygon.get("type") == "Feature" else polygon
    poly = shape(g)
    cx, cy = poly.centroid.x, poly.centroid.y
    min_x, min_y, max_x, max_y = poly.bounds
    half = max(min_half_m, margin_m + 111320.0 * max(max_y - min_y, (max_x - min_x) * abs(__import__("math").cos(__import__("math").radians(cy)))) / 2)
    return bbox_around(cy, cx, half)


def build_local_package(producer: Producer, now: Optional[datetime] = None, polygon: Optional[dict] = None,
                        key: Optional[str] = None) -> Path:
    """Garante work/{id}/ completo. Cache de 24 h; no modo auto (só fora de produção) cai para simulado se a rede falhar.

    `polygon` = talhão desenhado: o recorte cobre o talhão inteiro (não só 1 km ao redor do ponto)."""
    from app.plots import polygon_hash
    now = now or datetime.now()
    out = config.work_root() / (key or str(producer.id))  # um recorte por talhão: "12-p3"
    meta = out / "meta.json"
    mode = config.data_mode()
    ph = polygon_hash(polygon) if polygon else None
    seed = producer.id if not key else producer.id * 1000 + int(key.rsplit("p", 1)[-1] or 0)  # talhões diferentes, cenas diferentes
    if mode == "simulado":
        if _fresh(meta, now, "simulado", ph):
            return out
        simulated.make_synthetic_package(out, producer.lat, producer.lon, seed=seed, today=now)
        _stamp(meta, ph)
        return out
    if _fresh(meta, now, "earth-search", ph):
        return out
    try:
        from app.data.sentinel import fetch_sentinel_clip
        fetch_sentinel_clip(producer.lat, producer.lon, out, today=now, bbox=polygon_bbox(polygon) if polygon else None)
        _stamp(meta, ph)
        return out
    except Exception:
        if meta.exists():  # reserva: último pacote salvo (o serviço descarta se a cena for velha demais)
            return out
        if mode == "auto":
            simulated.make_synthetic_package(out, producer.lat, producer.lon, seed=seed, today=now)
            _stamp(meta, ph)
            return out
        raise
