"""O motor geo chegando ao produtor: geada pelo relevo, localização da área fraca, ph/geadas na nota e linhas do relatório."""
from datetime import timedelta

import pytest

from app import config
from app.alerts import evaluate
from app.alerts.rules import evaluate_frost, evaluate_stress
from app.data import simulated
from app.data.climate import mean_monthly_rain, monthly_from_daily, season_frost_days
from app.message import render
from app.message.templates import Report
from app.models import Producer, SpatialStats, Viability, Weather
from app.viability import load_crops, score_crop
from tests.conftest import NOW, make_hours

CLIMA = {"monthly": {m: {"temp": 25.0, "rain": 120.0, "frost_days": 0.0} for m in range(1, 13)}}


def _stats(**kw):
    base = dict(ndvi_mean=0.7, ndvi_std=0.05, slope_mean_pct=2.0, clay_pct=40.0, ph=6.2, area_ha=7.0,
                scene_date="2026-11-22")
    base.update(kw)
    return SpatialStats(**base)


# ---- geada pelo relevo ----
def test_geada_dispara_na_baixada_mesmo_com_previsao_acima_do_limite():
    w = Weather(hours=make_hours(temp=lambda i: 3.8 if 15 <= i <= 19 else 14.0))  # previsão do ponto: 3,8 C (limite 3)
    assert evaluate_frost(w, now=NOW) is None
    a = evaluate_frost(w, now=NOW, relief_offset_c=-1.0)
    assert a is not None and a.evidence["modo"] == "relevo"
    assert a.evidence["tmin_previsto"] == 3.8 and a.evidence["tmin"] == 2.8


def test_geada_sem_efeito_de_relevo_mantem_o_comportamento_antigo():
    w = Weather(hours=simulated.scenario_weather("geada", NOW))
    a = evaluate_frost(w, now=NOW, relief_offset_c=0.0)
    assert a.evidence["tmin"] == 2.0 and "modo" not in a.evidence


def test_evaluate_le_o_offset_do_stats():
    w = Weather(hours=make_hours(temp=lambda i: 3.8 if 15 <= i <= 19 else 14.0))
    p = Producer(id=1, phone="1")
    assert "geada" not in [x.type for x in evaluate(p, w, _stats(), now=NOW, log=[])]
    assert "geada" in [x.type for x in evaluate(p, w, _stats(frost_relief_offset_c=-1.0), now=NOW, log=[])]


def test_mensagem_de_geada_por_relevo_nos_3_idiomas_e_no_sms():
    w = Weather(hours=make_hours(temp=lambda i: 3.8 if 15 <= i <= 19 else 14.0))
    a = evaluate_frost(w, now=NOW, relief_offset_c=-1.0)
    for lang in ("pt", "es", "en"):
        wa = render(a, "whatsapp", lang)
        assert "3.8" in wa and "2.8" in wa and "None" not in wa
        sms = render(a, "sms", lang)
        assert len(sms) <= 160 and sms.isascii() and "2.8" in sms


# ---- área fraca ----
def test_estresse_localizado_diz_o_lado():
    st = _stats(ndvi_mean=0.66, ndvi_ref_mean=0.7, ndvi_ref_std=0.1, weak_area_pct=30.0, weak_area_dir="N")
    a = evaluate_stress(st)  # z = -0,4 (não dispara), mas 30% fraca >= 25% dispara
    assert a is not None and a.evidence["modo"] == "localizado" and a.evidence["direcao"] == "N"
    assert "norte" in render(a, "whatsapp", "pt") and "north" in render(a, "whatsapp", "en")
    assert "norte" in render(a, "sms", "pt") and len(render(a, "sms", "pt")) <= 160


def test_estresse_nao_dispara_com_pouca_area_fraca_e_z_normal():
    st = _stats(ndvi_mean=0.69, ndvi_ref_mean=0.7, ndvi_ref_std=0.1, weak_area_pct=10.0, weak_area_dir="NE")
    assert evaluate_stress(st) is None


def test_estresse_antigo_continua_igual_quando_nao_ha_area_fraca():
    st = _stats(ndvi_mean=0.4, ndvi_ref_mean=0.7, ndvi_ref_std=0.1)
    a = evaluate_stress(st)
    assert a.evidence["z"] == -3.0 and "modo" not in a.evidence
    assert "z = -3" in render(a, "whatsapp", "pt")


# ---- nota: pH e geadas no ciclo ----
def test_ph_fora_da_faixa_limita_a_nota():
    soja = load_crops()["soja"]
    ok = score_crop(_stats(ph=6.0), CLIMA, soja, today=NOW)
    assert ok.score == 100 and "ph" in ok.factors
    ruim = score_crop(_stats(ph=4.0), CLIMA, soja, today=NOW)
    assert ruim.score <= 40 and ruim.limiting_factor == "ph" and "pH" in ruim.orientation


def test_geadas_no_ciclo_derrubam_a_nota_e_dado_ausente_nao():
    soja = load_crops()["soja"]
    clima = {"monthly": {m: {"temp": 25.0, "rain": 120.0, "frost_days": 2.0} for m in range(1, 13)}}
    v = score_crop(_stats(), clima, soja, today=NOW)  # 5 meses x 2 dias = 10 dias de geada
    assert v.factors["geadas_ciclo"] == 0.0 and v.score <= 40 and v.limiting_factor == "geadas_ciclo"
    sem = score_crop(_stats(), {"monthly": {m: {"temp": 25.0, "rain": 120.0} for m in range(1, 13)}}, soja, today=NOW)
    assert "geadas_ciclo" not in sem.factors and sem.score == 100  # histórico antigo sem mínimas: fator sai da conta


def test_historico_conta_dias_de_geada_por_mes():
    times = [f"2024-07-{d:02d}" for d in range(1, 11)] + [f"2025-07-{d:02d}" for d in range(1, 11)]
    tmins = [2.0] * 4 + [8.0] * 6 + [1.0] * 2 + [9.0] * 8  # 4 geadas em 2024, 2 em 2025 -> média 3
    m = monthly_from_daily(times, [10.0] * 20, [0.0] * 20, tmins, frost_c=3.0)
    assert m[7]["frost_days"] == 3.0
    assert season_frost_days({"monthly": m}, 7, 1) == 3.0
    assert season_frost_days({"monthly": m}, 7, 2) is None  # agosto sem dado
    assert "frost_days" not in monthly_from_daily(times, [10.0] * 20, [0.0] * 20)[7]
    assert mean_monthly_rain({"monthly": m}) == 0.0 and mean_monthly_rain(None) is None


def test_crops_yaml_tem_ph_e_geadas_validos_em_todas_as_culturas():
    crops = load_crops()  # validate_crops confere a ordem a<=b<=c<=d de todas as faixas
    assert all("ph" in c["fatores"] and "geadas_ciclo" in c["fatores"] for c in crops.values())
    assert abs(sum(config.crops_cfg()["padrao"]["pesos"].values()) - 1.0) < 1e-9


# ---- relatório ----
def _viab():
    return Viability(crop="soja", score=80, factors={"chuva_mm": 0.5}, limiting_factor="chuva_mm", orientation="x",
                     confidence="media")


def test_relatorio_traz_relevo_zonas_agua_e_baixada():
    st = _stats(slope_mean_pct=6.4, aspect_label="S", erosion_class="baixo", moisture_class="baixa",
                frost_relief_offset_c=-0.8, zones=[{"id": 1, "share_pct": 30.0, "ndvi_mean": 0.55}, {"id": 2, "share_pct": 70.0, "ndvi_mean": 0.75}])
    rep = Report(ranking=[_viab()], stats=st, relations={"saldo_mm": -8.2, "atencao_agua": True})
    for lang, trechos in {"pt": ("declividade média de 6.4%", "voltada para sul", "Zonas de manejo: 2", "baixa", "-8.2", "olho na água", "0.8"),
                          "es": ("pendiente media", "hacia sur", "Zonas de manejo: 2", "baja", "-8.2", "vigilar", "0.8"),
                          "en": ("average slope 6.4%", "facing south", "Management zones: 2", "low", "-8.2", "Keep an eye", "0.8")}.items():
        txt = render(rep, "whatsapp", lang)
        for t in trechos:
            assert t in txt, (lang, t)
    sms = render(rep, "sms", "pt")
    assert len(sms) <= 160 and sms.isascii()  # o SMS não ganha linhas novas


def test_relatorio_sem_dados_do_motor_geo_fica_como_antes():
    rep = Report(ranking=[_viab()], stats=_stats())
    txt = render(rep, "whatsapp", "pt")
    assert "Relevo" not in txt and "Zonas" not in txt and "Umidade" not in txt and "Baixada" not in txt
