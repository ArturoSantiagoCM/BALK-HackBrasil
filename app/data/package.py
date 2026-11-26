"""M2: pacote de dados do local -> work/{producer_id}/ (red, nir, scl, dem, clay, meta.json)."""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from app import config
from app.data import simulated
from app.models import Producer

MAX_AGE_H = 24


def _fresh(meta_path: Path, now: datetime, mode_source: str) -> bool:
    if not meta_path.exists():
        return False
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    age_h = (now - datetime.fromisoformat(meta["created"])).total_seconds() / 3600
    return age_h < MAX_AGE_H and (mode_source == "any" or meta.get("source") == mode_source)


def build_local_package(producer: Producer, now: Optional[datetime] = None) -> Path:
    """Garante work/{id}/ completo. Cache de 24 h; no modo auto, cai para simulado se a rede falhar."""
    now = now or datetime.now()
    out = config.work_root() / str(producer.id)
    meta = out / "meta.json"
    mode = config.data_mode()
    if mode == "simulado":
        if _fresh(meta, now, "simulado"):
            return out
        return simulated.make_synthetic_package(out, producer.lat, producer.lon, seed=producer.id, today=now)
    if _fresh(meta, now, "earth-search"):
        return out
    try:
        from app.data.sentinel import fetch_sentinel_clip
        fetch_sentinel_clip(producer.lat, producer.lon, out, today=now)
        return out
    except Exception:
        if meta.exists():  # reserva: último pacote salvo
            return out
        if mode == "auto":
            return simulated.make_synthetic_package(out, producer.lat, producer.lon, seed=producer.id, today=now)
        raise
