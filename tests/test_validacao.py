"""A trilha de fontes: toda faixa e toda regra tem origem e status; os valores ajustados pela pesquisa estão no lugar."""
import re

from app import config
from app.alerts.rules import _ok_spray
from app.viability import load_crops

STATUS = {"confirmado", "ajustado", "parcial", "premissa"}


def test_toda_faixa_de_toda_cultura_tem_status_e_fonte_cadastrada():
    cfg = config.crops_cfg()
    fontes, valid = cfg["fontes"], cfg["validacao"]
    for nome, crop in cfg["culturas"].items():
        for f in crop["fatores"]:
            v = valid[nome][f]
            assert v["status"] in STATUS, (nome, f)
            assert v["fonte"] in fontes, (nome, f)
    for f in cfg["validacao"]["_comum"]:
        assert cfg["validacao"]["_comum"][f]["fonte"] in fontes
    for fid, s in fontes.items():
        assert s["titulo"] and (fid == "EXTRA_PADRAO" or re.match(r"^https?://", s["url"])), fid


def test_regras_de_alerta_tem_status_resumo_e_fonte_quando_confirmadas():
    v = config.rules()["validacao_regras"]
    for k in ("pulverizacao", "geada", "estresse", "colheita", "frete", "umidade_ndmi", "erosao", "relevo_classes"):
        assert v[k]["status"] in STATUS | {"premissa"} and v[k]["resumo"]
        if v[k]["status"] == "confirmado":
            assert v[k]["fontes"], k
    assert config.rules()["atribuicoes"]  # Open-Meteo, Copernicus, SoilGrids, OSRM


def test_valores_ajustados_pela_pesquisa_estao_no_yaml():
    c = load_crops()
    assert c["soja"]["fatores"]["chuva_mm"]["c"] == 700 and c["soja"]["fatores"]["ph"]["c"] == 6.5
    assert (c["milho"]["fatores"]["temp_media_c"]["b"], c["milho"]["fatores"]["temp_media_c"]["c"]) == (24, 30)
    assert c["milho"]["fatores"]["chuva_mm"]["b"] == 500
    assert c["cafe"]["fatores"]["chuva_mm"]["b"] == 1200 and c["cafe"]["fatores"]["ph"]["b"] == 5.5
    assert (c["feijao"]["fatores"]["temp_media_c"]["c"], c["feijao"]["fatores"]["temp_media_c"]["d"]) == (24, 30)
    # soja: ideal 20-30 C (Embrapa) continua
    assert (c["soja"]["fatores"]["temp_media_c"]["b"], c["soja"]["fatores"]["temp_media_c"]["c"]) == (20, 30)


def test_pulverizacao_respeita_a_temperatura_minima_da_embrapa():
    c = config.rules()["pulverizacao"]
    assert c["temp_min"] == 10
    base = {"time": "2026-11-27T11:00", "temp": 22.0, "rh": 70.0, "rain_prob": 10.0, "rain_mm": 0.0, "wind_kmh": 6.0}
    assert _ok_spray(base, c)
    assert not _ok_spray({**base, "temp": 8.0, "rh": 90.0}, c)  # frio demais para aplicar
    assert not _ok_spray({**base, "temp": 31.0}, c)


def test_frete_soma_o_custo_fixo_de_carga_e_descarga_da_antt(monkeypatch):
    from datetime import datetime
    from app.logistics import load_destinations, plan_route
    from app.models import Producer
    p, dest = Producer(id=1, phone="1", lat=-15.7347, lon=-48.0152), load_destinations()[0]
    now = datetime(2026, 11, 27, 10, 0)
    base = plan_route(p, dest, now)["frete_rs"]
    monkeypatch.setitem(config.rules()["logistica"], "frete_fixo_rs", 782.5)
    assert plan_route(p, dest, now)["frete_rs"] == round(base + 782.5) or abs(plan_route(p, dest, now)["frete_rs"] - base - 782.5) <= 1
