"""Leitura e alinhamento das camadas na grade de 10 m do vermelho (UTM, metros)."""
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.warp import Resampling, reproject

LAYERS = {  # arquivo -> (reamostragem, obrigatório)
    "red": ("red.tif", Resampling.bilinear, True), "nir": ("nir.tif", Resampling.bilinear, True),
    "scl": ("scl.tif", Resampling.nearest, False), "swir": ("swir.tif", Resampling.bilinear, False),
    "rededge": ("rededge.tif", Resampling.bilinear, False), "nir08": ("nir08.tif", Resampling.bilinear, False), "dem": ("dem.tif", Resampling.bilinear, False),
    "clay": ("clay.tif", Resampling.nearest, False), "ph": ("ph.tif", Resampling.nearest, False),
}


def _on_grid(path: Path, ref, resampling: Resampling) -> Optional[np.ndarray]:
    """Lê um raster e reamostra para a grade de `ref`. SCL (20 m) usa vizinho mais próximo; reflectância, bilinear."""
    if not path.exists():
        return None
    dest = np.full((ref.height, ref.width), np.nan, dtype="float32")
    with rasterio.open(path) as src:
        reproject(source=rasterio.band(src, 1), destination=dest, dst_transform=ref.transform, dst_crs=ref.crs,
                  src_nodata=src.nodata, dst_nodata=np.nan, resampling=resampling)
    return dest


def read_stack(work_dir: Path, lat: float, lon: float) -> dict:
    """Todas as camadas de work/{id}/ na mesma grade, mais transformação e ponto da lavoura em metros."""
    work_dir = Path(work_dir)
    with rasterio.open(work_dir / "red.tif") as ref:
        if ref.crs is None or ref.crs.is_geographic:
            raise ValueError("red.tif precisa estar em um CRS projetado (UTM, metros)")
        out = {"red": ref.read(1).astype("float32"), "transform": ref.transform, "crs": ref.crs,
               "shape": (ref.height, ref.width)}
        for name, (fname, resamp, required) in LAYERS.items():
            if name == "red":
                continue
            out[name] = _on_grid(work_dir / fname, ref, resamp)
            if required and out[name] is None:
                raise FileNotFoundError(work_dir / fname)
        out["point"] = Transformer.from_crs(4326, ref.crs, always_xy=True).transform(lon, lat)
    return out


def circle_mask(transform, shape, point, radius_m: float) -> np.ndarray:
    """Círculo de análise ao redor do ponto (distância ao centro do pixel <= raio)."""
    rows, cols = np.indices(shape)
    xs = transform.c + (cols + 0.5) * transform.a
    ys = transform.f + (rows + 0.5) * transform.e
    return np.hypot(xs - point[0], ys - point[1]) <= radius_m


def pixel_xy(transform, shape):
    """Coordenadas (x, y) em metros do centro de cada pixel."""
    rows, cols = np.indices(shape)
    return transform.c + (cols + 0.5) * transform.a, transform.f + (rows + 0.5) * transform.e
