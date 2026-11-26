"""M2 (real): recortes de ~1 km de Sentinel-2 L2A, Copernicus DEM e argila do SoilGrids.

Usa UMA só coleção no projeto inteiro: sentinel-2-l2a (Earth Search v1).
Reflectância: valor_real = DN * scale + offset, lidos dos metadados do item (raster:bands).
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from pystac_client import Client
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

STAC_URL = "https://earthsearch.aws.element84.com/v1"
S2_COLLECTION = "sentinel-2-l2a"
DEM_COLLECTION = "cop-dem-glo-30"
SOILGRIDS_CLAY = "https://files.isric.org/soilgrids/latest/data/clay/clay_0-5cm_mean.vrt"
SOILGRIDS_PH = "https://files.isric.org/soilgrids/latest/data/phh2o/phh2o_0-5cm_mean.vrt"


def bbox_around(lat: float, lon: float, half_m: float = 500) -> list[float]:
    dlat = half_m / 111320.0
    dlon = half_m / (111320.0 * max(np.cos(np.radians(lat)), 0.01))
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def _save_window(href: str, bbox: list[float], out: Path, scale: float = 1.0, offset: float = 0.0,
                 as_reflectance: bool = False, nodata_dn: Optional[float] = None) -> None:
    with rasterio.Env(AWS_NO_SIGN_REQUEST="YES", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(href) as src:
            b = transform_bounds("EPSG:4326", src.crs, *bbox)
            win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
            data = src.read(1, window=win)
            tr = src.window_transform(win)
            if as_reflectance:
                valid = data != (nodata_dn if nodata_dn is not None else 0)
                arr = np.where(valid, data.astype("float32") * scale + offset, np.nan).astype("float32")
                profile = dict(dtype="float32", nodata=np.nan)
            else:
                arr, profile = data, dict(dtype=data.dtype, nodata=src.nodata)
            with rasterio.open(out, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                               crs=src.crs, transform=tr, **profile) as dst:
                dst.write(arr, 1)


def fetch_sentinel_clip(lat: float, lon: float, out_dir: Path, today: Optional[datetime] = None,
                        max_cloud: int = 30, days: int = 30) -> dict:
    """Cena mais recente com <30% de nuvem nos últimos 30 dias -> red.tif, nir.tif, scl.tif, dem.tif."""
    today = today or datetime.now()
    out_dir.mkdir(parents=True, exist_ok=True)
    bbox = bbox_around(lat, lon)
    client = Client.open(STAC_URL)
    rng = f"{(today - timedelta(days=days)):%Y-%m-%d}/{today:%Y-%m-%d}"
    items = list(client.search(collections=[S2_COLLECTION], bbox=bbox, datetime=rng,
                               query={"eo:cloud_cover": {"lt": max_cloud}}, max_items=25).items())
    if not items:
        raise RuntimeError("nenhuma cena Sentinel-2 com pouca nuvem nos últimos 30 dias")
    item = max(items, key=lambda i: i.datetime)
    for key in ("red", "nir"):
        asset = item.assets[key]
        band = (asset.extra_fields.get("raster:bands") or [{}])[0]
        _save_window(asset.href, bbox, out_dir / f"{key}.tif", scale=band.get("scale", 0.0001),
                     offset=band.get("offset", 0.0), as_reflectance=True)
    _save_window(item.assets["scl"].href, bbox, out_dir / "scl.tif")
    for key, fname in (("swir16", "swir.tif"), ("rededge1", "rededge.tif"), ("nir08", "nir08.tif")):  # 20 m: NDMI/NDRE (B11, B05, B8A)
        if key in item.assets:  # opcionais: sem elas o motor geo só não calcula NDMI/NDRE
            asset = item.assets[key]
            band = (asset.extra_fields.get("raster:bands") or [{}])[0]
            _save_window(asset.href, bbox, out_dir / fname, scale=band.get("scale", 0.0001),
                         offset=band.get("offset", 0.0), as_reflectance=True)
    dem_items = list(client.search(collections=[DEM_COLLECTION], bbox=bbox, max_items=1).items())
    if dem_items:
        _save_window(dem_items[0].assets["data"].href, bbox, out_dir / "dem.tif")
    has_clay = fetch_clay(lat, lon, out_dir / "clay.tif")
    has_ph = fetch_ph(lat, lon, out_dir / "ph.tif")
    meta = {"scene_date": item.datetime.strftime("%Y-%m-%d"), "scene_id": item.id, "source": "earth-search",
            "clay": has_clay, "ph": has_ph, "cloud": item.properties.get("eo:cloud_cover"),
            "created": today.isoformat(timespec="seconds")}
    (out_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def fetch_clay(lat: float, lon: float, out: Path) -> bool:
    """Argila (0-5 cm) do SoilGrids em %, a partir do VRT público. Falhou: sem esse fator (confiança menor)."""
    return _fetch_soilgrids(SOILGRIDS_CLAY, lat, lon, out)


def fetch_ph(lat: float, lon: float, out: Path) -> bool:
    """pH em água (0-5 cm) do SoilGrids. O arquivo guarda pH x 10; aqui sai o pH real."""
    return _fetch_soilgrids(SOILGRIDS_PH, lat, lon, out)


def _fetch_soilgrids(url: str, lat: float, lon: float, out: Path) -> bool:
    """Janela pequena de um VRT do SoilGrids, dividida por 10 (g/kg -> %, pH x 10 -> pH). False se falhar."""
    try:
        d = 0.002
        with rasterio.Env(GDAL_HTTP_TIMEOUT="20"):
            with rasterio.open(url) as src:
                b = transform_bounds("EPSG:4326", src.crs, lon - d, lat - d, lon + d, lat + d)
                win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
                data = src.read(1, window=win).astype("float32")
                data[data == (src.nodata if src.nodata is not None else -32768)] = np.nan
                data = data / 10.0  # SoilGrids: argila em g/kg (10 g/kg = 1 %) e pH x 10
                with rasterio.open(out, "w", driver="GTiff", height=data.shape[0], width=data.shape[1],
                                   count=1, dtype="float32", crs=src.crs, transform=src.window_transform(win),
                                   nodata=np.nan) as dst:
                    dst.write(data, 1)
        return True
    except Exception:  # noqa: BLE001
        return False
