"""Testes do motor geo (app/geo): relevo, índices e relações entre camadas, com valores conhecidos."""
import numpy as np
import pytest

from app.data import simulated
from app.engine.python_engine import analyze_python, analyze_with_products
from app.geo import indices, relations, terrain


# ---------- relevo ----------
def _plane(slope_pct=10.0, cell=10.0, n=20, toward="north"):
    """Plano que sobe para o norte (linha 0 = norte)."""
    rows = np.arange(n)[:, None] * np.ones((1, n))
    z = 100 + (n - 1 - rows) * cell * slope_pct / 100
    return z if toward == "north" else z[::-1]


def test_horn_em_plano_inclinado_e_exato_inclusive_nas_bordas():
    slope, aspect = terrain.slope_aspect(_plane(10.0), 10, 10)
    assert np.allclose(slope, 10.0, atol=1e-6)
    assert np.allclose(aspect, 180.0, atol=1e-6)  # sobe para o norte = desce para o sul


@pytest.mark.parametrize("sobe,esperado", [("north", 180.0), ("south", 0.0)])
def test_aspecto_aponta_para_onde_desce(sobe, esperado):
    _, aspect = terrain.slope_aspect(_plane(8.0, toward=sobe), 10, 10)
    assert aspect[5, 5] == pytest.approx(esperado, abs=1e-6)


def test_aspecto_leste_e_terreno_plano():
    z = 100 + np.arange(20)[None, :] * np.ones((20, 1))  # sobe para o leste (colunas)
    _, asp = terrain.slope_aspect(z, 10, 10)
    assert asp[5, 5] == pytest.approx(270.0, abs=1e-6)  # desce para o oeste
    s, a = terrain.slope_aspect(np.full((9, 9), 50.0), 10, 10)
    assert np.allclose(s, 0) and np.isnan(a).all()


def test_pixel_retangular_e_pixel_invalido():
    z = _plane(10.0, cell=10.0)  # sobe 1 m por linha
    assert terrain.slope_aspect(z, 10, 20)[0][5, 5] == pytest.approx(5.0, abs=1e-6)  # linhas a 20 m: metade
    assert terrain.slope_aspect(z, 10, 10)[0][5, 5] == pytest.approx(10.0, abs=1e-6)
    with pytest.raises(ValueError):
        terrain.slope_aspect(np.zeros((2, 2)), 10, 10)
    with pytest.raises(ValueError):
        terrain.slope_aspect(np.zeros((5, 5)), 0, 10)


def test_nodata_no_dem_nao_espalha():
    z = _plane(10.0)
    z[8, 8] = np.nan
    s, _ = terrain.slope_aspect(z, 10, 10)
    assert np.isnan(s[8, 8]) and np.isfinite(s[9, 9]) and np.isfinite(s[7, 7])


def test_tpi_baixada_negativa_e_topo_positivo():
    z = np.full((41, 41), 100.0)
    z[20, 20] = 95.0  # buraco
    z[5, 5] = 108.0  # pico
    t = terrain.tpi(z, 5)
    assert t[20, 20] < -4.5 and t[5, 5] > 7.0
    assert abs(t[30, 10]) < 1e-9  # chão plano


def test_rugosidade_ignora_vizinho_nodata():
    z = np.full((5, 5), 10.0)
    z[2, 2] = 13.0
    assert terrain.roughness(z)[2, 2] == pytest.approx(np.sqrt(8 * 9.0))
    z[2, 3] = np.nan
    assert terrain.roughness(z)[2, 2] == pytest.approx(np.sqrt(7 * 9.0))


def test_indice_de_ar_frio_so_em_baixada_pouco_inclinada():
    tpi = np.array([[-4.0, -4.0, 3.0]])
    slope = np.array([[2.0, 20.0, 2.0]])
    c = terrain.cold_pool_index(tpi, slope, depression_ref_m=2.0)
    assert c[0, 0] == 1.0 and c[0, 1] == 0.5 and c[0, 2] == 0.0


def test_compass():
    assert [terrain.compass(d) for d in (0, 45, 90, 180, 270, 350)] == ["N", "NE", "E", "S", "O", "N"]


# ---------- índices ----------
def test_indices_espectrais_valores_conhecidos():
    nir, red, swir, re_ = np.array([0.5]), np.array([0.1]), np.array([0.25]), np.array([0.2])
    assert indices.ndvi(red, nir)[0] == pytest.approx(0.6667, abs=1e-3)
    assert indices.ndmi(nir, swir)[0] == pytest.approx(0.3333, abs=1e-3)
    assert indices.ndre(nir, re_)[0] == pytest.approx(0.4286, abs=1e-3)
    assert np.isnan(indices.ndvi(np.array([0.0]), np.array([0.0]))[0])  # 0/0 vira NaN, não erro


def test_mascara_de_cena_descarta_nuvem_e_sombra():
    scl = np.array([4, 5, 3, 8, 9, 10, 11])
    assert indices.scene_mask(scl).tolist() == [True, True, False, False, False, False, False]
    assert indices.scene_mask(None) is None


# ---------- relações ----------
def test_zonas_de_manejo_separam_dois_grupos_e_ordenam_do_mais_fraco():
    n = 40
    ndvi = np.where(np.arange(n)[None, :] < 20, 0.3, 0.8) * np.ones((n, 1))
    slope = np.where(np.arange(n)[None, :] < 20, 12.0, 3.0) * np.ones((n, 1))
    mask = np.ones((n, n), bool)
    labels, zones = relations.management_zones({"ndvi": ndvi, "slope": slope}, mask, k=2, pixel_area_m2=100)
    assert [z["id"] for z in zones] == [1, 2] and zones[0]["label"] == "fraca" and zones[1]["label"] == "forte"
    assert zones[0]["ndvi_mean"] == pytest.approx(0.3) and zones[1]["ndvi_mean"] == pytest.approx(0.8)
    assert zones[0]["share_pct"] == pytest.approx(50.0) and zones[0]["area_ha"] == pytest.approx(8.0)
    assert (labels[:, :20] == 1).all() and (labels[:, 20:] == 2).all()


def test_zonas_com_pouco_dado_nao_quebram():
    labels, zones = relations.management_zones({"ndvi": np.full((4, 4), 0.5)}, np.ones((4, 4), bool), k=3)
    assert zones == [] and labels.sum() == 0


class _Tr:  # transformação mínima: pixel 10 m, canto superior esquerdo em (0, 100)
    a, e, c, f = 10.0, -10.0, 0.0, 100.0


def test_area_fraca_diz_onde_fica():
    ndvi = np.full((10, 10), 0.7)
    ndvi[0:3, 3:7] = 0.2  # faixa no topo = norte
    aoi = np.ones((10, 10), bool)
    r = relations.weak_area(ndvi, aoi, _Tr, (50.0, 50.0), 0.65, 0.1)
    assert r["dir"] == "N" and r["pct"] == pytest.approx(12.0)
    assert relations.weak_area(np.full((10, 10), 0.7), aoi, _Tr, (50, 50), 0.65, 0.1)["dir"] is None
    assert relations.weak_area(ndvi, aoi, _Tr, (50, 50), None, None) == {"pct": None, "dir": None}


def test_erosao_sobe_com_declive_e_cai_com_cobertura():
    cfg = {"declive_ref_pct": 15, "chuva_ref_mm_mes": 250, "baixo_ate": 0.25, "medio_ate": 0.6}
    aoi = np.ones((6, 6), bool)
    suave, c1 = relations.erosion_index(np.full((6, 6), 3.0), np.full((6, 6), 0.8), aoi, 40.0, 130.0, cfg)
    forte, c2 = relations.erosion_index(np.full((6, 6), 30.0), np.full((6, 6), 0.8), aoi, 40.0, 130.0, cfg)
    nu, c3 = relations.erosion_index(np.full((6, 6), 30.0), np.full((6, 6), 0.1), aoi, 40.0, 130.0, cfg)
    plano, _ = relations.erosion_index(np.zeros((6, 6)), np.full((6, 6), 0.1), aoi, 40.0, 130.0, cfg)
    assert suave < forte < nu and plano == 0.0
    assert (c1, c3) == ("baixo", "alto")
    assert relations.erosion_index(None, np.zeros((2, 2)), aoi[:2, :2], None, None, cfg) == (None, None)


def test_frost_offset_e_umidade_e_balanco():
    cold = np.array([[0.0, 0.5, 1.0, 1.0]])
    assert relations.frost_offset(cold, np.ones((1, 4), bool), 1.0) == -1.0
    assert relations.frost_offset(np.zeros((1, 4)), np.ones((1, 4), bool), 1.0) == 0.0
    assert relations.frost_offset(None, np.ones((1, 4), bool), 1.0) is None
    assert [relations.moisture_class(v) for v in (0.05, 0.2, 0.4, None)] == ["baixa", "media", "alta", None]
    wb = relations.water_balance([{"rain_mm": 0.0, "et0": 0.3}] * 10 + [{"rain_mm": 1.0}])
    assert wb["saldo_mm"] == -2.0 and wb["horas"] == 11
    assert relations.water_attention("baixa", -8.0) and not relations.water_attention("alta", -8.0)
    assert not relations.water_attention("baixa", 3.0)


# ---------- pipeline ----------
def test_pipeline_no_pacote_ondulado_acha_baixada_zonas_e_area_fraca(tmp_path):
    lat, lon = -23.5874, -46.6576
    work = simulated.make_synthetic_package(tmp_path / "o", lat, lon, seed=1)  # relief="ondulado" é o padrão
    s, P = analyze_with_products(work, lat, lon, rain_month_mm=130.0)
    assert s.ndmi_mean is not None and s.ndre_mean is not None and s.ph == pytest.approx(6.1)
    assert s.moisture_class in ("baixa", "media", "alta")
    assert s.tpi_min is not None and s.tpi_min < -1.0  # a baixada existe
    assert s.frost_relief_offset_c is not None and s.frost_relief_offset_c < 0  # e pesa na geada
    assert s.erosion_class in ("baixo", "medio") and 0 <= s.erosion_index <= 1
    assert s.zones and len(s.zones) >= 2 and sum(z["share_pct"] for z in s.zones) == pytest.approx(100, abs=0.5)
    assert s.aspect_label in ("N", "NE", "E", "SE", "S", "SO", "O", "NO")
    assert P.zones.shape == P.ndvi.shape and np.isfinite(P.tpi).any()


def test_pipeline_sem_camadas_opcionais_so_deixa_campos_vazios(tmp_path):
    lat, lon = -23.5874, -46.6576
    work = simulated.make_synthetic_package(tmp_path / "m", lat, lon, seed=1, clay=False)
    for nm in ("swir.tif", "rededge.tif", "dem.tif"):
        (work / nm).unlink()
    s = analyze_python(work, lat, lon)
    assert s.ndvi_mean is not None
    assert s.ndmi_mean is None and s.slope_mean_pct is None and s.erosion_index is None
    assert s.frost_relief_offset_c is None and s.clay_pct is None and s.ph is None


def test_pipeline_pacote_plano_reproduz_declividade_conhecida(tmp_path):
    lat, lon = -15.7347, -48.0152
    work = simulated.make_synthetic_package(tmp_path / "pl", lat, lon, seed=2, slope_pct=6.0, relief="plano")
    s = analyze_python(work, lat, lon)
    assert s.slope_mean_pct == pytest.approx(6.0, abs=0.3) and s.aspect_label == "S"  # sobe para o norte
    assert s.frost_relief_offset_c == 0.0 and s.tpi_min > -0.5
