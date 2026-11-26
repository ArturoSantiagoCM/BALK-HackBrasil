import pytest

from app import config
from app.models import SpatialStats
from app.viability import fit, load_crops, rank_crops, score_crop, validate_crops
from tests.conftest import NOW

CLIMA_OTIMO = {"monthly": {m: {"temp": 25.0, "rain": 120.0} for m in range(1, 13)}}


def stats(**over):
    base = dict(ndvi_mean=0.7, ndvi_std=0.05, slope_mean_pct=2.0, slope_max_pct=4.0, clay_pct=40.0,
                elevation_m=700.0, area_ha=7.0, scene_date="2026-11-22", engine="python")
    base.update(over)
    return SpatialStats(**base)


def test_fit_trapezio():
    assert fit(None, 0, 1, 2, 3) == 0.0
    assert fit(1.5, 0, 1, 2, 3) == 1.0
    assert fit(0.5, 0, 1, 2, 3) == pytest.approx(0.5)
    assert fit(2.5, 0, 1, 2, 3) == pytest.approx(0.5)
    assert fit(0, 0, 1, 2, 3) == 0.0 and fit(3, 0, 1, 2, 3) == 0.0


def test_tudo_otimo_da_100():
    v = score_crop(stats(), CLIMA_OTIMO, load_crops()["soja"], today=NOW)
    assert v.score == 100 and v.confidence == "alta"
    assert v.orientation  # frase de "sem fator crítico"


def test_fator_zero_limita_a_40():
    v = score_crop(stats(slope_mean_pct=50.0), CLIMA_OTIMO, load_crops()["soja"], today=NOW)
    assert v.score <= 40 and v.limiting_factor == "declive_pct"
    assert "inclinado" in v.orientation


def test_dado_ausente_derruba_confianca_sem_zerar_nota():
    v = score_crop(stats(clay_pct=None), CLIMA_OTIMO, load_crops()["soja"], today=NOW)
    assert "argila_pct" not in v.factors and v.score == 100 and v.confidence == "media"


def test_confianca_por_idade_da_cena():
    assert score_crop(stats(scene_date="2026-10-01"), CLIMA_OTIMO, load_crops()["soja"], today=NOW).confidence == "baixa"
    assert score_crop(stats(scene_date="2026-11-10"), CLIMA_OTIMO, load_crops()["soja"], today=NOW).confidence == "media"
    assert score_crop(stats(scene_date=None), CLIMA_OTIMO, load_crops()["soja"], today=NOW).confidence == "baixa"


def test_ranking_devolve_3_e_poe_a_cultura_informada_primeiro():
    r = rank_crops(stats(), CLIMA_OTIMO, today=NOW)
    assert len(r) == 3 and r[0].score >= r[1].score >= r[2].score
    r2 = rank_crops(stats(), CLIMA_OTIMO, crop_pref="hortalica", today=NOW)
    assert len(r2) == 3 and r2[0].crop == "hortalica"


def test_crops_yaml_real_e_valido():
    validate_crops(config.crops_cfg())


def test_crops_yaml_fora_de_ordem_falha_com_mensagem_clara():
    bad = {"padrao": {"ndvi_std": {"a": 0, "b": 1, "c": 2, "d": 3}},
           "culturas": {"x": {"fatores": {"temp_media_c": {"a": 0, "b": 5, "c": 3, "d": 9},
                                          "chuva_mm": {"a": 0, "b": 1, "c": 2, "d": 3},
                                          "declive_pct": {"a": 0, "b": 1, "c": 2, "d": 3},
                                          "argila_pct": {"a": 0, "b": 1, "c": 2, "d": 3}}}}}
    with pytest.raises(ValueError, match="fora de ordem"):
        validate_crops(bad)
