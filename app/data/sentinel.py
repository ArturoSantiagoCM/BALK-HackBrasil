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

STAC_URL = "https://earth-search.aws.element84.com/v1"
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


def scale_offset(item, asset) -> tuple[float, float]:
    """Escala e deslocamento da reflectância (valor = DN x escala + deslocamento). O Earth Search v1 informa o deslocamento
    de -0,1 nos metadados da banda, mas em boa parte das cenas JÁ o aplicou nos arquivos (propriedade
    earthsearch:boa_offset_applied = true). Aplicar de novo deixa o vermelho negativo e o NDVI acima de 1."""
    band = (asset.extra_fields.get("raster:bands") or [{}])[0]
    offset = 0.0 if item.properties.get("earthsearch:boa_offset_applied") else band.get("offset", 0.0)
    return band.get("scale", 0.0001), offset


VALIDAS = (4, 5)  # classes da SCL que valem: vegetação e solo exposto (nuvem, sombra, água e neve ficam de fora)


def _valid_fraction(scl_href: str, bbox: list[float]) -> float:
    """Fração da área com pixel útil na SCL (20 m, leitura barata). É o que diz se a cena serve PARA ESTE TALHÃO:
    o percentual de nuvem do item é do recorte inteiro de 100 km e pode esconder um talhão nublado ou limpo."""
    with rasterio.Env(AWS_NO_SIGN_REQUEST="YES", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(scl_href) as src:
            b = transform_bounds("EPSG:4326", src.crs, *bbox)
            win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
            scl = src.read(1, window=win)
    return float(np.isin(scl, VALIDAS).mean()) if scl.size else 0.0


def fetch_sentinel_clip(lat: float, lon: float, out_dir: Path, today: Optional[datetime] = None,
                        max_cloud: int = 80, days: int = 60, bbox: Optional[list] = None,
                        min_valid: float = 0.6, max_candidates: int = 6) -> dict:
    """A cena mais recente que esteja LIMPA SOBRE O TALHÃO -> red, nir, scl, swir, rededge, nir08, dem, argila e pH.

    Busca até `days` dias (o mesmo limite em que a imagem ainda é aceita), confere a SCL de até `max_candidates` cenas,
    da mais nova para a mais velha, e fica com a primeira que tem pelo menos `min_valid` da área útil. Se nenhuma chegar
    lá, usa a de maior área útil, desde que tenha ao menos 10%; abaixo disso falha (o serviço vira "sem imagem adequada").
    `bbox` (lon0, lat0, lon1, lat1) cobre o talhão desenhado; o padrão é 1 km ao redor do ponto."""
    today = today or datetime.now()
    out_dir.mkdir(parents=True, exist_ok=True)
    bbox = bbox or bbox_around(lat, lon)
    client = Client.open(STAC_URL)
    rng = f"{(today - timedelta(days=days)):%Y-%m-%d}/{today:%Y-%m-%d}"
    items = list(client.search(collections=[S2_COLLECTION], bbox=bbox, datetime=rng,
                               query={"eo:cloud_cover": {"lt": max_cloud}}, max_items=40).items())
    if not items:
        raise RuntimeError(f"nenhuma cena Sentinel-2 nos últimos {days} dias")
    items.sort(key=lambda i: i.datetime, reverse=True)
    best, best_vf, tried = None, -1.0, []
    for it in items[:max_candidates]:
        try:
            vf = _valid_fraction(it.assets["scl"].href, bbox)
        except Exception:  # noqa: BLE001  (cena com arquivo ilegível: tenta a próxima)
            continue
        tried.append({"id": it.id, "data": it.datetime.strftime("%Y-%m-%d"), "util": round(vf, 3)})
        if vf > best_vf:
            best, best_vf = it, vf
        if vf >= min_valid:
            best, best_vf = it, vf
            break
    if best is None or best_vf < 0.1:
        raise RuntimeError(f"nenhuma cena com o talhão visível (nuvem) nos últimos {days} dias: {tried}")
    item = best
    for key in ("red", "nir"):
        asset = item.assets[key]
        sc, off = scale_offset(item, asset)
        _save_window(asset.href, bbox, out_dir / f"{key}.tif", scale=sc, offset=off, as_reflectance=True)
    _save_window(item.assets["scl"].href, bbox, out_dir / "scl.tif")
    for key, fname in (("swir16", "swir.tif"), ("rededge1", "rededge.tif"), ("nir08", "nir08.tif")):  # 20 m: NDMI/NDRE (B11, B05, B8A)
        if key in item.assets:  # opcionais: sem elas o motor geo só não calcula NDMI/NDRE
            asset = item.assets[key]
            sc, off = scale_offset(item, asset)
            _save_window(asset.href, bbox, out_dir / fname, scale=sc, offset=off, as_reflectance=True)
    dem_items = list(client.search(collections=[DEM_COLLECTION], bbox=bbox, max_items=1).items())
    if dem_items:
        _save_window(dem_items[0].assets["data"].href, bbox, out_dir / "dem.tif")
    has_clay = fetch_clay(lat, lon, out_dir / "clay.tif")
    has_ph = fetch_ph(lat, lon, out_dir / "ph.tif")
    if not (has_clay and has_ph):  # o mapa de argila exige baixar um bloco grande e às vezes falha: reserva pela consulta por ponto
        pt = soilgrids_point(lat, lon)
        if not has_clay and pt.get("clay") is not None:
            has_clay = _write_point(out_dir / "clay.tif", bbox, pt["clay"]) and "ponto"
        if not has_ph and pt.get("ph") is not None:
            has_ph = _write_point(out_dir / "ph.tif", bbox, pt["ph"]) and "ponto"
    cloud = item.properties.get("eo:cloud_cover")
    meta = {"scene_date": item.datetime.strftime("%Y-%m-%d"), "scene_id": item.id, "source": "earth-search",
            "clay": has_clay, "ph": has_ph, "cloud": cloud, "cloud_cover": cloud, "util_no_talhao": round(best_vf, 3),
            "offset_ja_aplicado": bool(item.properties.get("earthsearch:boa_offset_applied")),
            "cenas_conferidas": tried, "created": today.isoformat(timespec="seconds")}
    (out_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


SOILGRIDS_REST = "https://rest.isric.org/soilgrids/v2.0/properties/query"


def soilgrids_point(lat: float, lon: float) -> dict:
    """Argila (%) e pH (0-5 cm) num ponto, pela API do SoilGrids (uma chamada; uso moderado: ~5 por minuto). {} se falhar."""
    import requests
    try:
        r = requests.get(SOILGRIDS_REST, params={"lon": round(lon, 5), "lat": round(lat, 5), "property": ["clay", "phh2o"],
                                                  "depth": "0-5cm", "value": "mean"}, timeout=30)
        r.raise_for_status()
        out = {}
        for layer in r.json()["properties"]["layers"]:
            v = layer["depths"][0]["values"].get("mean")
            if v is not None:
                out["clay" if layer["name"] == "clay" else "ph"] = v / float(layer["unit_measure"].get("d_factor", 10))
        return out
    except Exception:  # noqa: BLE001
        return {}


def _write_point(out: Path, bbox: list[float], value: float) -> bool:
    """Grava o valor do ponto como um GeoTIFF de 1 pixel cobrindo a área inteira (o SoilGrids já é de 250 m: um valor só
    para o talhão é o que o dado permite dizer)."""
    from rasterio.transform import from_bounds as tb
    with rasterio.open(out, "w", driver="GTiff", height=1, width=1, count=1, dtype="float32", crs="EPSG:4326",
                       transform=tb(*bbox, 1, 1), nodata=np.nan) as dst:
        dst.write(np.array([[value]], dtype="float32"), 1)
    return True


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
