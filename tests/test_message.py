from datetime import timedelta

import pytest

from app.alerts.rules import evaluate_frost, evaluate_harvest, evaluate_spraying, evaluate_stress
from app.data import simulated
from app.message import render
from app.message.polish import polish, validate_polished
from app.message.templates import Report, to_sms
from app.models import Alert, Producer, SpatialStats, Viability, Weather
from tests.conftest import NOW, make_hours


def todos_os_alertas():
    bom = Weather(hours=make_hours())
    ruim = Weather(hours=make_hours(wind_kmh=25.0, rain_prob=85.0, rain_mm=3.0))
    adiar = Weather(hours=make_hours(wind_kmh=lambda i: 20.0 if i < 30 else 6.0))
    geada = Weather(hours=simulated.scenario_weather("geada", NOW))
    prod = Producer(id=1, phone="1", crop="soja", planting_date=(NOW - timedelta(days=125)).strftime("%Y-%m-%d"))
    st = SpatialStats(ndvi_mean=0.4, area_ha=7.0, ndvi_ref_mean=0.7, ndvi_ref_std=0.1)
    return [evaluate_spraying(bom, now=NOW), evaluate_spraying(ruim, now=NOW), evaluate_spraying(adiar, now=NOW),
            evaluate_frost(geada, now=NOW), evaluate_stress(st), evaluate_harvest(prod, bom, now=NOW),
            evaluate_harvest(prod, Weather(hours=make_hours(rain_mm=1.0)), now=NOW)]


@pytest.mark.parametrize("lang", ["pt", "es", "en"])
def test_todo_alerta_sai_em_whatsapp_e_sms_nos_3_idiomas(lang):
    for a in todos_os_alertas():
        wa = render(a, "whatsapp", lang)
        assert wa.strip() and "{" not in wa and "None" not in wa
        assert len(wa.splitlines()) == 3  # ação, o dado que justifica, confiança + como responder (curto e ao ponto)
        sms = render(a, "sms", lang)
        assert len(sms) <= 160, sms
        assert sms.isascii(), sms
        assert sms.endswith("Resp 1=ok 2=ajuda") and sms.startswith("BALK:")
        assert "{" not in sms and "None" not in sms


def test_whatsapp_pt_tem_acao_motivo_confianca_e_como_responder():
    wa = render(evaluate_spraying(Weather(hours=make_hours()), now=NOW), "whatsapp", "pt")
    linhas = wa.splitlines()
    assert "Pulverize" in linhas[0] and "11h" in linhas[0]
    assert "km/h" in linhas[1]
    assert "Confiança" in linhas[2] and "Responda 1" in linhas[2]
    assert len(wa) <= 260  # cabe na tela do celular sem rolar


def test_sms_de_geada_no_formato_do_guia():
    a = evaluate_frost(Weather(hours=simulated.scenario_weather("geada", NOW)), now=NOW)
    sms = render(a, "sms", "pt")
    assert sms.startswith("BALK: GEADA amanha 3h-8h, min 2C.") or sms.startswith("BALK: GEADA amanha")


def test_to_sms_remove_acento_e_corta():
    assert to_sms("Pulverização até às 9h") == "Pulverizacao ate as 9h"
    assert len(to_sms("x" * 300)) == 160 and to_sms("x" * 300).endswith("...")


def _viab(crop="soja", score=72):
    return Viability(crop=crop, score=score, factors={"chuva_mm": 0.4, "temp_media_c": 1.0}, limiting_factor="chuva_mm",
                     orientation="A chuva histórica fica abaixo do ideal. Avalie irrigação suplementar ou outra cultura.",
                     confidence="media")


def test_relatorio_tem_aviso_fixo_e_sms_curto():
    st = SpatialStats(area_ha=7.07, scene_date="2026-11-22", ndvi_mean=0.7)
    rep = Report(ranking=[_viab(), _viab("milho", 65), _viab("feijao", 50)], stats=st, crop_pref="soja",
                 map_url="/maps/1.png")
    for lang in ("pt", "es", "en"):
        wa = render(rep, "whatsapp", lang)
        assert "/maps/1.png" in wa and "72/100" in wa
        assert len(wa.splitlines()) <= 6, wa  # curto: os detalhes ficam no relatório do link
    wa = render(rep, "whatsapp", "pt")
    assert "Não substitui um engenheiro agrônomo" in wa and "Atenção: a chuva histórica" in wa and "(boa)" in wa
    sms = render(rep, "sms", "pt")
    assert len(sms) <= 160 and sms.isascii() and "72/100" in sms


def test_relatorio_so_municipio_explica_o_limite():
    txt = render(Report(ranking=[], stats=None, only_weather=True), "whatsapp", "pt")
    assert "município" in txt and "pin" in txt


# ---- validador e IA ----
ORIG = "Pulverize hoje, das 11h às 14h.\nVento de 6 km/h, 22°C e chance de chuva de 10%."
DATA = {"vento_kmh": 6.0, "temp": 22.0, "chuva_prob": 10, "action": "Pulverize das 11h às 14h.", "window": "11h-14h"}


def test_validador_aceita_texto_fiel():
    ok, motivo = validate_polished(ORIG, "Pode pulverizar hoje, das 11h às 14h. Vento de 6 km/h e chuva de 10%.", DATA, 200)
    assert ok, motivo


def test_validador_reprova_numero_inventado():
    ok, motivo = validate_polished(ORIG, "Pulverize hoje, das 11h às 14h. Vento de 9 km/h.", DATA, 200)
    assert not ok and "inventado" in motivo


def test_validador_reprova_tamanho_lista_proibida_e_janela():
    assert not validate_polished(ORIG, "Pulverize das 11h às 14h. " + "a" * 300, DATA, 100)[0]
    assert "proibida" in validate_polished(ORIG, "Pulverize das 11h às 14h, resultado garantido.", DATA, 200)[1]
    assert "proibida" in validate_polished(ORIG, "Pulverize das 11h às 14h com a dose certa.", DATA, 200)[1]
    assert "janela" in validate_polished(ORIG, "Pulverize hoje com vento de 6 km/h.", DATA, 200)[1]


def test_polish_usa_ia_so_se_valida_e_nunca_quebra():
    bom = lambda s, u: "Pode pulverizar hoje, das 11h às 14h. Vento de 6 km/h."  # noqa: E731
    inventa = lambda s, u: "Pulverize das 11h às 14h. Vento de 40 km/h."  # noqa: E731

    def cai(s, u):
        raise TimeoutError("demorou")
    assert polish(ORIG, DATA, "pt", 200, llm=bom).startswith("Pode pulverizar")
    assert polish(ORIG, DATA, "pt", 200, llm=inventa) == ORIG
    assert polish(ORIG, DATA, "pt", 200, llm=cai) == ORIG
    assert polish(ORIG, DATA, "pt", 200, llm=lambda s, u: None) == ORIG


def test_ia_desligada_nao_quebra_o_render(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    a = evaluate_spraying(Weather(hours=make_hours()), now=NOW)
    assert render(a, "whatsapp", "pt", use_ai=True) == render(a, "whatsapp", "pt")
