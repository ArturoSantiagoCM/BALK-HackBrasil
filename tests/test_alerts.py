from datetime import timedelta

import pytest

from app.alerts import evaluate
from app.alerts.calc import confidence_from, delta_t, gdd, wet_bulb_stull, zscore
from app.alerts.rules import evaluate_frost, evaluate_harvest, evaluate_spraying, evaluate_stress
from app.alerts.silence import filter_by_silence
from app.data import simulated
from app.models import Alert, Producer, SpatialStats, Weather
from tests.conftest import NOW, make_hours


def W(**over):
    return Weather(hours=make_hours(**over))


# ---- cálculos puros ----
def test_delta_t_stull():
    assert wet_bulb_stull(20, 50) == pytest.approx(13.7, abs=0.15)
    assert delta_t(20, 50) == pytest.approx(6.3, abs=0.15)


def test_gdd():
    assert gdd(30, 20) == 15.0
    assert gdd(12, 6) == 0.0  # nunca negativo


def test_zscore():
    assert zscore(0.5, 0.7, 0.1) == pytest.approx(-2.0)
    assert zscore(0.5, 0.7, 0) is None


def test_confidence_from():
    assert confidence_from(10, 5) == "alta"
    assert confidence_from(10, 50) == "media"
    assert confidence_from(40, 5) == "media"
    assert confidence_from(60, 5) == "baixa"


# ---- pulverização ----
def test_dia_perfeito_devolve_janela():
    a = evaluate_spraying(W(), now=NOW)
    assert a.type == "pulverizacao" and a.evidence["modo"] == "agora"
    assert a.window == "11h-14h"


def test_vento_forte_e_chuva_manda_evitar():
    a = evaluate_spraying(W(wind_kmh=25.0, rain_prob=85.0, rain_mm=3.0), now=NOW)
    assert a.evidence["modo"] == "evitar" and a.window is None


def test_hoje_ruim_e_amanha_bom_sugere_adiar():
    a = evaluate_spraying(W(wind_kmh=lambda i: 20.0 if i < 30 else 6.0), now=NOW)
    assert a.evidence["modo"] == "adiar"
    assert a.evidence["dia_offset"] == 1 or a.evidence["dia_offset"] == 2


# ---- geada ----
def test_geada_com_minima_2_graus():
    w = Weather(hours=simulated.scenario_weather("geada", NOW))
    a = evaluate_frost(w, now=NOW)
    assert a.type == "geada" and a.evidence["tmin"] == 2.0


def test_sem_geada_com_clima_ameno():
    assert evaluate_frost(W(), now=NOW) is None


# ---- estresse ----
def test_estresse_por_historico_e_vizinhanca():
    st = SpatialStats(ndvi_mean=0.4, area_ha=7.0, ndvi_ref_mean=0.7, ndvi_ref_std=0.1)
    a = evaluate_stress(st)
    assert a.confidence == "baixa" and a.evidence["referencia"] == "vizinhanca"
    a2 = evaluate_stress(st, {"mean": 0.7, "std": 0.1})
    assert a2.confidence == "media"
    assert evaluate_stress(SpatialStats(ndvi_mean=0.69, area_ha=7, ndvi_ref_mean=0.7, ndvi_ref_std=0.1)) is None
    assert evaluate_stress(None) is None


# ---- colheita ----
def test_colheita_pronta_com_janela_seca():
    p = Producer(id=1, phone="1", crop="soja", planting_date=(NOW - timedelta(days=125)).strftime("%Y-%m-%d"))
    a = evaluate_harvest(p, W(), now=NOW)
    assert a.evidence["modo"] == "janela"


def test_colheita_nao_pronta_nao_alerta():
    p = Producer(id=1, phone="1", crop="soja", planting_date=(NOW - timedelta(days=30)).strftime("%Y-%m-%d"))
    assert evaluate_harvest(p, W(), now=NOW) is None


def test_colheita_sem_janela_quando_chove_sempre():
    p = Producer(id=1, phone="1", crop="soja", planting_date=(NOW - timedelta(days=125)).strftime("%Y-%m-%d"))
    a = evaluate_harvest(p, W(rain_mm=1.0), now=NOW)
    assert a.evidence["modo"] == "sem_janela"


# ---- silêncio e evaluate ----
def test_chuva_e_vento_devolve_exatamente_1_alerta_de_pulverizacao():
    p = Producer(id=1, phone="1")
    out = evaluate(p, W(wind_kmh=25.0, rain_prob=85.0, rain_mm=3.0), None, now=NOW, log=[])
    assert [a.type for a in out] == ["pulverizacao"]


def test_minima_2_graus_devolve_geada():
    p = Producer(id=1, phone="1")
    w = Weather(hours=simulated.scenario_weather("geada", NOW))
    assert "geada" in [a.type for a in evaluate(p, w, None, now=NOW, log=[])]


def test_repetir_logo_depois_nao_devolve_nada():
    p = Producer(id=1, phone="1")
    w = Weather(hours=simulated.scenario_weather("geada", NOW))
    first = evaluate(p, w, None, now=NOW, log=[])
    assert first
    log = [{"type": a.type, "sent_at": NOW.isoformat()} for a in first]
    assert evaluate(p, w, None, now=NOW + timedelta(minutes=5), log=log) == []


def _al(t):
    return Alert(type=t, action="x", evidence={}, confidence="alta", why="y")


def test_silencio_cota_semanal_com_excecao_da_geada():
    p = Producer(id=1, phone="1")
    log = [{"type": "colheita", "sent_at": (NOW - timedelta(days=4)).isoformat()},
           {"type": "estresse", "sent_at": (NOW - timedelta(days=5)).isoformat()}]
    out = filter_by_silence([_al("pulverizacao"), _al("geada")], p, log, NOW)
    assert [a.type for a in out] == ["geada"]


def test_silencio_horario_quieto_com_excecao_da_geada():
    p = Producer(id=1, phone="1")
    noite = NOW.replace(hour=22)
    out = filter_by_silence([_al("pulverizacao"), _al("geada")], p, [], noite)
    assert [a.type for a in out] == ["geada"]


def test_silencio_duplicados_do_dia_viram_um():
    out = filter_by_silence([_al("pulverizacao"), _al("pulverizacao")], Producer(id=1, phone="1"), [], NOW)
    assert len(out) == 1
