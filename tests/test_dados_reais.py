"""O caminho de dados REAIS exercitado sem internet: arquivos locais no lugar das URLs, STAC falso e falhas de rede.

O que isto prova: a lógica de recorte, reflectância (escala e deslocamento), unidades (g/kg -> %, pH x 10) e as quedas
para reserva. O que NÃO prova: que o Earth Search e o SoilGrids respondem como esperado (isso exige rede; rode
`python check_apis.py` e `DATA_MODE=real`).
"""
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
import rasterio
import requests
from pyproj import Transformer
from rasterio.transform import Affine

from app import config, db
from app.data import package, sentinel, simulated
from app.data.climate import get_climate_history
from app.data.weather import get_weather
from app.engine.python_engine import analyze_python
from app.models import Producer

LAT, LON = -15.7347, -48.0152
NOW = datetime(2026, 11, 27, 10, 0)


def _utm_tif(path, dn, dtype="uint16", pixel=10.0, size=200):
    """GeoTIFF em UTM, 2 km x 2 km (bem maior que o recorte de 1 km), centrado no ponto."""
    epsg = simulated.utm_epsg(LAT, LON)
    x, y = Transformer.from_crs(4326, epsg, always_xy=True).transform(LON, LAT)
    tr = Affine(pixel, 0, x - size * pixel / 2, 0, -pixel, y + size * pixel / 2)
    with rasterio.open(path, "w", driver="GTiff", height=size, width=size, count=1, dtype=dtype, crs=f"EPSG:{epsg}",
                       transform=tr) as d:
        d.write(np.full((size, size), dn, dtype=dtype), 1)
    return path


def test_recorte_aplica_escala_e_deslocamento_da_reflectancia(tmp_path):
    src = _utm_tif(tmp_path / "red_full.tif", 3000)  # DN 3000, scale 1e-4, offset -0.1 -> 0.2
    out = tmp_path / "red.tif"
    sentinel._save_window(str(src), sentinel.bbox_around(LAT, LON), out, scale=0.0001, offset=-0.1, as_reflectance=True)
    with rasterio.open(out) as d:
        a = d.read(1)
        assert 90 <= d.width <= 110 and 90 <= d.height <= 110  # ~1 km a 10 m
        assert np.allclose(a, 0.2, atol=1e-5)


def test_pixel_sem_dado_vira_nan_e_nao_reflectancia_negativa(tmp_path):
    src = _utm_tif(tmp_path / "x.tif", 0)  # DN 0 = sem dado no Sentinel-2
    out = tmp_path / "o.tif"
    sentinel._save_window(str(src), sentinel.bbox_around(LAT, LON), out, scale=0.0001, offset=-0.1, as_reflectance=True)
    with rasterio.open(out) as d:
        assert np.isnan(d.read(1)).all()


def test_soilgrids_converte_g_por_kg_em_percentual_e_ph_vezes_10(tmp_path):
    epsg4326 = Affine(0.001, 0, LON - 0.05, 0, -0.001, LAT + 0.05)
    for nome, dn, esperado in (("clay", 380, 38.0), ("ph", 61, 6.1)):
        f = tmp_path / f"{nome}_src.tif"
        with rasterio.open(f, "w", driver="GTiff", height=100, width=100, count=1, dtype="int16", crs="EPSG:4326",
                           transform=epsg4326, nodata=-32768) as d:
            d.write(np.full((100, 100), dn, dtype="int16"), 1)
        out = tmp_path / f"{nome}.tif"
        assert sentinel._fetch_soilgrids(str(f), LAT, LON, out) is True
        with rasterio.open(out) as d:
            assert np.allclose(d.read(1), esperado)


def test_soilgrids_inacessivel_devolve_false_sem_quebrar(tmp_path):
    assert sentinel._fetch_soilgrids("/caminho/que/nao/existe.vrt", LAT, LON, tmp_path / "c.tif") is False


class _Asset:
    def __init__(self, href, bands=None):
        self.href, self.extra_fields = href, {"raster:bands": bands or [{}]}


class _Item:
    def __init__(self, assets, when="2026-11-20T13:00:00Z", cloud=5):
        self.assets, self.id, self.properties = assets, "S2X_FAKE", {"eo:cloud_cover": cloud}
        self.datetime = datetime.fromisoformat(when.replace("Z", "+00:00"))


class _Search:
    def __init__(self, items):
        self._items = items

    def items(self):
        return iter(self._items)


def _fake_client(monkeypatch, tmp_path, with_dem=True, cloud_items=True):
    reflect = dict(scale=0.0001, offset=-0.1)
    files = {"red": _utm_tif(tmp_path / "s_red.tif", 3000), "nir": _utm_tif(tmp_path / "s_nir.tif", 5000),
             "scl": _utm_tif(tmp_path / "s_scl.tif", 4, "uint8", 20.0, 100),
             "swir16": _utm_tif(tmp_path / "s_swir.tif", 3500, pixel=20.0, size=100),
             "rededge1": _utm_tif(tmp_path / "s_re.tif", 4000, pixel=20.0, size=100),
             "nir08": _utm_tif(tmp_path / "s_nir08.tif", 4800, pixel=20.0, size=100)}
    bands = [reflect]
    assets = {k: _Asset(str(v), bands if k != "scl" else None) for k, v in files.items()}
    dem = tmp_path / "dem_full.tif"
    with rasterio.open(dem, "w", driver="GTiff", height=200, width=200, count=1, dtype="float32", crs="EPSG:4326",
                       transform=Affine(0.0003, 0, LON - 0.03, 0, -0.0003, LAT + 0.03)) as d:
        d.write(np.full((200, 200), 1050.0, dtype="float32"), 1)

    class FakeClient:
        @staticmethod
        def open(url):
            c = FakeClient()
            c.url = url
            return c

        def search(self, collections, **kw):
            if collections == [sentinel.S2_COLLECTION]:
                self.last_query = kw
                return _Search([_Item(assets)] if cloud_items else [])
            return _Search([_Item({"data": _Asset(str(dem))})] if with_dem else [])
    monkeypatch.setattr(sentinel, "Client", FakeClient)
    monkeypatch.setattr(sentinel, "SOILGRIDS_CLAY", str(tmp_path / "nao_existe.vrt"))  # SoilGrids fora do ar
    monkeypatch.setattr(sentinel, "SOILGRIDS_PH", str(tmp_path / "nao_existe.vrt"))


def test_fetch_sentinel_completo_com_stac_falso_e_o_motor_geo_le_o_resultado(monkeypatch, tmp_path):
    _fake_client(monkeypatch, tmp_path)
    out = tmp_path / "work" / "1"
    meta = sentinel.fetch_sentinel_clip(LAT, LON, out, today=NOW)
    assert meta["scene_date"] == "2026-11-20" and meta["source"] == "earth-search" and meta["clay"] is False
    for nome in ("red", "nir", "scl", "swir", "rededge", "nir08", "dem"):
        assert (out / f"{nome}.tif").exists(), nome
    s = analyze_python(out, LAT, LON)
    # red 0,2 e nir 0,4 (DN 5000*1e-4-0,1): NDVI = 0,2/0,6; NDMI usa B8A 0,38 e SWIR 0,25
    assert s.ndvi_mean == pytest.approx(0.3333, abs=1e-3)
    assert s.ndmi_mean == pytest.approx((0.38 - 0.25) / (0.38 + 0.25), abs=2e-3)
    assert s.ndre_mean == pytest.approx((0.38 - 0.3) / (0.38 + 0.3), abs=2e-3)
    assert s.elevation_m == pytest.approx(1050.0, abs=0.5) and s.scene_date == "2026-11-20"
    assert s.clay_pct is None and s.ph is None  # SoilGrids caiu: fatores saem da conta, nada quebra


def test_sem_cena_com_pouca_nuvem_levanta_erro_claro(monkeypatch, tmp_path):
    _fake_client(monkeypatch, tmp_path, cloud_items=False)
    with pytest.raises(RuntimeError, match="nenhuma cena"):
        sentinel.fetch_sentinel_clip(LAT, LON, tmp_path / "w", today=NOW)


def test_sem_dem_o_pacote_sai_sem_relevo_e_o_motor_continua(monkeypatch, tmp_path):
    _fake_client(monkeypatch, tmp_path, with_dem=False)
    out = tmp_path / "w2"
    sentinel.fetch_sentinel_clip(LAT, LON, out, today=NOW)
    s = analyze_python(out, LAT, LON)
    assert s.ndvi_mean is not None and s.slope_mean_pct is None and s.erosion_index is None


# ---- modos real / auto e quedas ----
def _sem_rede(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("sem rede")
    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr("time.sleep", lambda s: None)


def test_modo_auto_sem_rede_cai_para_simulado_e_modo_real_levanta(monkeypatch):
    _sem_rede(monkeypatch)
    monkeypatch.setenv("DATA_MODE", "auto")
    w = get_weather(LAT, LON, NOW)
    assert w.source == "simulado" and len(w.hours) == 72
    assert get_climate_history(LAT, LON, today=NOW)["source"] == "simulado"
    monkeypatch.setenv("DATA_MODE", "real")
    with pytest.raises(RuntimeError, match="Open-Meteo falhou"):
        get_weather(LAT, LON, NOW)


def test_ultimo_valor_salvo_serve_de_reserva_quando_a_rede_cai(monkeypatch):
    _sem_rede(monkeypatch)
    monkeypatch.setenv("DATA_MODE", "real")
    linhas = simulated.scenario_weather("bom", NOW)
    db.cache_set(f"wx:{LAT:.2f}:{LON:.2f}:last", {"hours": linhas})
    w = get_weather(LAT, LON, NOW)
    assert w.source == "cache" and w.hours == linhas


def test_resposta_do_open_meteo_com_buracos_e_lida(monkeypatch):
    t0 = "2026-11-27T"
    horas = [f"{t0}{h:02d}:00" for h in range(10, 24)]
    payload = {"hourly": {"time": horas, "temperature_2m": [20.0] * 13 + [None], "relative_humidity_2m": [60] * 14,
                          "precipitation_probability": [None] * 14, "precipitation": [0.0] * 14,
                          "wind_speed_10m": [7.0] * 14, "et0_fao_evapotranspiration": [None] * 14}}
    from app.data.weather import parse_open_meteo
    rows = parse_open_meteo(payload, NOW)
    assert len(rows) == 13  # a hora sem temperatura sai
    assert rows[0]["rain_prob"] == 0.0 and rows[0]["et0"] == 0.0 and rows[0]["wind_kmh"] == 7.0


def test_pacote_real_em_cache_de_24h_nao_baixa_de_novo(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_MODE", "real")
    p = Producer(id=9, phone="x", lat=LAT, lon=LON)
    out = config.work_root() / "9"
    out.mkdir(parents=True)
    (out / "meta.json").write_text(json.dumps({"source": "earth-search", "created": NOW.isoformat(), "scene_date": "2026-11-20"}))
    monkeypatch.setattr(sentinel, "fetch_sentinel_clip", lambda *a, **k: pytest.fail("baixou de novo"))
    assert package.build_local_package(p, NOW) == out


def test_modo_auto_sem_stac_gera_pacote_simulado_mas_modo_real_falha(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "auto")
    monkeypatch.setattr(sentinel, "fetch_sentinel_clip", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fora do ar")))
    p = Producer(id=10, phone="y", lat=LAT, lon=LON)
    out = package.build_local_package(p, NOW)
    assert json.loads((out / "meta.json").read_text())["source"] == "simulado"
    monkeypatch.setenv("DATA_MODE", "real")
    with pytest.raises(RuntimeError):
        package.build_local_package(Producer(id=11, phone="z", lat=LAT, lon=LON), NOW)
