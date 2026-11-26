import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import Affine

from app.data import simulated
from app.engine.python_engine import analyze_python
from app.models import Producer

LAT, LON = -15.0, -48.0


def _grid(tmp_path, red, nir, scl, dem):
    """Rasters sintéticos 10x10 (10 m) em UTM, centrados no ponto."""
    epsg = simulated.utm_epsg(LAT, LON)
    x, y = Transformer.from_crs(4326, epsg, always_xy=True).transform(LON, LAT)
    tr = Affine(10, 0, x - 50, 0, -10, y + 50)
    crs = f"EPSG:{epsg}"

    def w(name, arr, transform=tr, dtype="float32"):
        with rasterio.open(tmp_path / name, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1],
                           count=1, dtype=dtype, crs=crs, transform=transform) as d:
            d.write(arr.astype(dtype), 1)
    w("red.tif", red), w("nir.tif", nir)
    w("scl.tif", scl, Affine(20, 0, x - 50, 0, -20, y + 50), "uint8")  # 5x5 em 20 m
    w("dem.tif", dem)
    return tmp_path


def test_valores_conhecidos_10x10(tmp_path):
    red, nir = np.full((10, 10), 0.1), np.full((10, 10), 0.5)
    scl = np.full((5, 5), 4)
    dem = 100 + (9 - np.arange(10))[:, None] * np.ones((1, 10))  # sobe 1 m a cada 10 m = 10%
    _grid(tmp_path, red, nir, scl, dem)
    s = analyze_python(tmp_path, LAT, LON)
    assert s.engine == "python"
    assert s.ndvi_mean == pytest.approx(0.6667, abs=1e-3) and s.ndvi_std == pytest.approx(0, abs=1e-3)
    assert s.slope_mean_pct == pytest.approx(10.0, abs=0.01) and s.slope_max_pct == pytest.approx(10.0, abs=0.01)
    assert s.elevation_m == pytest.approx(104.5, abs=0.01)
    assert s.area_ha == pytest.approx(1.0) and s.clay_pct is None


def test_scl_20m_mascara_nuvem_na_grade_de_10m(tmp_path):
    red, nir = np.full((10, 10), 0.1), np.full((10, 10), 0.5)
    red[:4, :], nir[:4, :] = 0.3, 0.3  # nas linhas 0-3 NDVI = 0 (seria puxado para baixo sem máscara)
    scl = np.full((5, 5), 4)
    scl[:2, :] = 9  # nuvem nas 2 primeiras linhas de 20 m = 4 linhas de 10 m
    dem = np.full((10, 10), 50.0)
    _grid(tmp_path, red, nir, scl, dem)
    s = analyze_python(tmp_path, LAT, LON)
    assert s.ndvi_mean == pytest.approx(0.6667, abs=1e-3)
    assert s.slope_mean_pct == pytest.approx(0.0, abs=1e-6)


def test_pacote_simulado_completo_e_plausivel(tmp_path):
    out = simulated.make_synthetic_package(tmp_path / "p", -23.5874, -46.6576, seed=1, slope_pct=6.0, relief="plano")
    s = analyze_python(out, -23.5874, -46.6576)
    assert 0.5 < s.ndvi_mean < 0.95 and s.ndvi_std < 0.1
    assert s.slope_mean_pct == pytest.approx(6.0, abs=1.0)
    assert s.clay_pct == pytest.approx(38.0)
    assert s.area_ha == pytest.approx(7.07, abs=0.3)  # círculo de 150 m ~ 7 ha
    assert s.scene_date is not None


def test_analyze_escolhe_motor_e_cai_para_python():
    from app.engine import analyze
    import os
    os.environ["ENGINE"] = "qgis"  # sem QGIS neste ambiente: deve cair para o Python
    s = analyze(Producer(id=7, phone="x", lat=-15.7347, lon=-48.0152))
    assert s.engine == "python" and s.ndvi_mean is not None
