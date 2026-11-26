"""Pipeline do motor geo do BALK: camadas -> índices -> relevo -> relações -> SpatialStats + produtos para o mapa."""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from app import config
from app.geo import indices, relations, terrain
from app.geo.raster import circle_mask, read_stack
from app.models import SpatialStats

RADIUS_M = 150.0  # círculo de análise (~7 ha)

def geo_cfg() -> dict:
    """Parâmetros do motor geo, todos lidos de rules.yaml (blocos geada, relevo, agua, erosao, zonas, estresse)."""
    r = config.rules()
    return {"tpi_janela_m": r.get("relevo", {}).get("janela_m", 150),
            "depressao_m": r["geada"].get("tpi_depressao_m", 2.0),
            "geada_ajuste_c": r["geada"].get("ajuste_relevo_c", 1.0),
            "ndmi_seco": r.get("agua", {}).get("ndmi_seco", 0.1), "ndmi_umido": r.get("agua", {}).get("ndmi_umido", 0.3),
            "erosao": r.get("erosao", {}), "zonas_k": r.get("zonas", {}).get("k", 3),
            "zonas_min_pixels": r.get("zonas", {}).get("min_pixels", 30),
            "area_fraca_desvios": r["estresse"].get("area_fraca_desvios", 1.0),
            "area_fraca_min_pct": r["estresse"].get("area_fraca_min_pct", 5.0)}


@dataclass
class Products:
    """Arrays na grade de 10 m (para mapas, depuração e testes). NaN = sem dado."""
    ndvi: np.ndarray
    aoi: np.ndarray
    transform: object
    point: tuple
    ndmi: Optional[np.ndarray] = None
    ndre: Optional[np.ndarray] = None
    slope: Optional[np.ndarray] = None
    aspect: Optional[np.ndarray] = None
    tpi: Optional[np.ndarray] = None
    rough: Optional[np.ndarray] = None
    cold: Optional[np.ndarray] = None
    zones: Optional[np.ndarray] = None
    extra: dict = field(default_factory=dict)


def _f(x) -> Optional[float]:
    return None if x is None or not np.isfinite(x) else round(float(x), 4)


def _mean(a: Optional[np.ndarray], mask: np.ndarray) -> Optional[float]:
    if a is None:
        return None
    v = a[mask & np.isfinite(a)]
    return _f(v.mean()) if v.size else None


def run(work_dir: Path, lat: float, lon: float, rain_month_mm: Optional[float] = None,
        radius_m: float = RADIUS_M) -> tuple[SpatialStats, Products]:
    work_dir = Path(work_dir)
    cfg = geo_cfg()
    S = read_stack(work_dir, lat, lon)
    tr, shape, point = S["transform"], S["shape"], S["point"]
    cell_x, cell_y = abs(tr.a), abs(tr.e)
    mask = indices.scene_mask(S["scl"])
    nir = S["nir"]

    ndvi = indices.apply_mask(indices.ndvi(S["red"], nir), mask)
    nir_s = S["nir08"] if S["nir08"] is not None else nir  # NDMI/NDRE padrão usam B8A (nir08, 20 m); sem ela, B08
    ndmi = indices.apply_mask(indices.ndmi(nir_s, S["swir"]), mask) if S["swir"] is not None else None
    ndre = indices.apply_mask(indices.ndre(nir_s, S["rededge"]), mask) if S["rededge"] is not None else None
    aoi = circle_mask(tr, shape, point, radius_m)

    slope = aspect = tpi = rough = cold = None
    if S["dem"] is not None:
        slope, aspect = terrain.slope_aspect(S["dem"], cell_x, cell_y)
        tpi = terrain.tpi(S["dem"], max(1, round(cfg["tpi_janela_m"] / cell_x)))
        rough = terrain.roughness(S["dem"])
        cold = terrain.cold_pool_index(tpi, slope, cfg["depressao_m"])

    nd_in = ndvi[aoi & np.isfinite(ndvi)]
    ref = ndvi[np.isfinite(ndvi)]
    ref_mean = _f(ref.mean()) if ref.size > 10 else None
    ref_std = _f(ref.std()) if ref.size > 10 else None

    def at_point(layer):
        """Camadas de 250 m (SoilGrids): 1 ou 2 pixels dentro do círculo, então lê o pixel do ponto."""
        if layer is None:
            return None
        r, c = int((tr.f - point[1]) / cell_y), int((point[0] - tr.c) / tr.a)
        v = layer[r, c] if 0 <= r < shape[0] and 0 <= c < shape[1] else np.nan
        return _f(v) if np.isfinite(v) else _mean(layer, aoi)
    clay_pct, ph = at_point(S["clay"]), at_point(S["ph"])

    # relações entre camadas
    feats = {"ndvi": ndvi}
    for nm, arr in (("slope", slope), ("tpi", tpi), ("ndmi", ndmi)):
        if arr is not None:
            feats[nm] = arr
    labels, zones = relations.management_zones(feats, aoi, int(cfg["zonas_k"]), cell_x * cell_y,
                                               int(cfg["zonas_min_pixels"]))
    weak = relations.weak_area(ndvi, aoi, tr, point, ref_mean, ref_std, cfg["area_fraca_desvios"],
                               cfg["area_fraca_min_pct"])
    eros, eros_cls = relations.erosion_index(slope, ndvi, aoi, clay_pct, rain_month_mm, cfg["erosao"])
    offset = relations.frost_offset(cold, aoi, cfg["geada_ajuste_c"])

    asp_deg = asp_lbl = None
    if aspect is not None and slope is not None:
        sel = aoi & np.isfinite(aspect) & (slope > 2.0)  # em terreno quase plano o aspecto não significa nada
        if sel.sum() > 5:
            rad = np.radians(aspect[sel])
            asp_deg = round(float(np.degrees(np.arctan2(np.sin(rad).mean(), np.cos(rad).mean())) % 360), 1)
            asp_lbl = terrain.compass(asp_deg)

    meta = {}
    if (work_dir / "meta.json").exists():
        meta = json.loads((work_dir / "meta.json").read_text(encoding="utf-8"))
    ndmi_mean = _mean(ndmi, aoi)
    stats = SpatialStats(
        ndvi_mean=_f(nd_in.mean()) if nd_in.size else None, ndvi_std=_f(nd_in.std()) if nd_in.size else None,
        slope_mean_pct=_mean(slope, aoi),
        slope_max_pct=_f(slope[aoi & np.isfinite(slope)].max()) if slope is not None and (aoi & np.isfinite(slope)).any() else None,
        clay_pct=clay_pct, ph=ph, elevation_m=_mean(S["dem"], aoi) if S["dem"] is not None else None,
        area_ha=round(float(aoi.sum()) * cell_x * cell_y / 10000.0, 2), scene_date=meta.get("scene_date"),
        engine="python", ndvi_ref_mean=ref_mean, ndvi_ref_std=ref_std,
        ndmi_mean=ndmi_mean, ndre_mean=_mean(ndre, aoi), moisture_class=relations.moisture_class(
            ndmi_mean, cfg["ndmi_seco"], cfg["ndmi_umido"]),
        aspect_deg=asp_deg, aspect_label=asp_lbl, tpi_min=_f(np.nanmin(tpi[aoi])) if tpi is not None and np.isfinite(tpi[aoi]).any() else None,
        roughness_mean=_mean(rough, aoi), frost_relief_offset_c=offset, erosion_index=eros, erosion_class=eros_cls,
        weak_area_pct=weak["pct"], weak_area_dir=weak["dir"], zones=zones or None)
    return stats, Products(ndvi=ndvi, aoi=aoi, transform=tr, point=point, ndmi=ndmi, ndre=ndre, slope=slope,
                           aspect=aspect, tpi=tpi, rough=rough, cold=cold, zones=labels if zones else None)
