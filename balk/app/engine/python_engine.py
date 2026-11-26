"""M3: motor espacial em Python (rasterio + numpy + pyproj). Mesma saída do motor QGIS.

Nome do arquivo evita "python.py"/"qgis.py" para não sombrear módulos ao rodar scripts soltos.
"""
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.warp import Resampling, reproject

from app.models import SpatialStats

RADIUS_M = 150.0  # círculo de análise (~7 ha)
SCL_OK = (4, 5)  # vegetação e solo nu


def _on_grid(path: Path, ref: rasterio.DatasetReader, resampling: Resampling) -> Optional[np.ndarray]:
    """Lê um raster e reamostra para a grade (10 m) do vermelho. SCL (20 m) usa vizinho mais próximo."""
    if not path.exists():
        return None
    dest = np.full((ref.height, ref.width), np.nan, dtype="float32")
    with rasterio.open(path) as src:
        reproject(source=rasterio.band(src, 1), destination=dest, dst_transform=ref.transform,
                  dst_crs=ref.crs, src_nodata=src.nodata, dst_nodata=np.nan, resampling=resampling)
    return dest


def load_layers(work_dir: Path, lat: float, lon: float, radius_m: float = RADIUS_M) -> dict:
    """Calcula NDVI mascarado, declividade (%), máscara do círculo e argila no ponto."""
    work_dir = Path(work_dir)
    with rasterio.open(work_dir / "red.tif") as red_ds:
        red = red_ds.read(1).astype("float32")
        with rasterio.open(work_dir / "nir.tif") as nir_ds:
            nir = nir_ds.read(1).astype("float32")
        if red_ds.crs is None or red_ds.crs.is_geographic:
            raise ValueError("red.tif precisa estar em um CRS projetado (UTM, metros)")
        tr, shape = red_ds.transform, (red_ds.height, red_ds.width)
        scl = _on_grid(work_dir / "scl.tif", red_ds, Resampling.nearest)
        dem = _on_grid(work_dir / "dem.tif", red_ds, Resampling.bilinear)
        clay = _on_grid(work_dir / "clay.tif", red_ds, Resampling.nearest)
        px, py = Transformer.from_crs(4326, red_ds.crs, always_xy=True).transform(lon, lat)

    with np.errstate(invalid="ignore", divide="ignore"):
        ndvi = (nir - red) / (nir + red)
    valid = np.isfinite(ndvi) & ((nir + red) > 0)
    if scl is not None:  # sem SCL: não mascara (reduzir confiança fica a cargo de quem chama)
        valid &= np.isin(scl, SCL_OK)
    ndvi = np.where(valid, ndvi, np.nan)

    rows, cols = np.indices(shape)
    xs = tr.c + (cols + 0.5) * tr.a
    ys = tr.f + (rows + 0.5) * tr.e
    aoi = np.hypot(xs - px, ys - py) <= radius_m

    slope = None
    if dem is not None:
        gy, gx = np.gradient(dem, abs(tr.e), abs(tr.a))  # dem em metros, grade em metros
        slope = np.hypot(gx, gy) * 100.0  # porcentagem

    clay_pct = None
    if clay is not None:
        r, c = int((tr.f - py) / abs(tr.e)), int((px - tr.c) / tr.a)
        v = clay[r, c] if 0 <= r < shape[0] and 0 <= c < shape[1] else np.nan
        clay_pct = float(v) if np.isfinite(v) else (float(np.nanmean(clay[aoi])) if np.isfinite(clay[aoi]).any() else None)

    return {"ndvi": ndvi, "slope": slope, "dem": dem, "aoi": aoi, "clay_pct": clay_pct,
            "pixel_area_m2": abs(tr.a * tr.e), "transform": tr, "point": (px, py)}


def _f(x) -> Optional[float]:
    return None if x is None or not np.isfinite(x) else round(float(x), 4)


def analyze_python(work_dir: Path, lat: float, lon: float) -> SpatialStats:
    import json
    work_dir = Path(work_dir)
    L = load_layers(work_dir, lat, lon)
    aoi, ndvi = L["aoi"], L["ndvi"]
    nd = ndvi[aoi]
    nd = nd[np.isfinite(nd)]
    meta = {}
    if (work_dir / "meta.json").exists():
        meta = json.loads((work_dir / "meta.json").read_text(encoding="utf-8"))
    sl, dem = L["slope"], L["dem"]
    slope_in = sl[aoi][np.isfinite(sl[aoi])] if sl is not None else np.array([])
    dem_in = dem[aoi][np.isfinite(dem[aoi])] if dem is not None else np.array([])
    ref = ndvi[np.isfinite(ndvi)]
    return SpatialStats(
        ndvi_mean=_f(nd.mean()) if nd.size else None,
        ndvi_std=_f(nd.std()) if nd.size else None,
        slope_mean_pct=_f(slope_in.mean()) if slope_in.size else None,
        slope_max_pct=_f(slope_in.max()) if slope_in.size else None,
        clay_pct=_f(L["clay_pct"]),
        elevation_m=_f(dem_in.mean()) if dem_in.size else None,
        area_ha=round(float(aoi.sum()) * L["pixel_area_m2"] / 10000.0, 2),
        scene_date=meta.get("scene_date"),
        engine="python",
        ndvi_ref_mean=_f(ref.mean()) if ref.size > 10 else None,
        ndvi_ref_std=_f(ref.std()) if ref.size > 10 else None,
    )
