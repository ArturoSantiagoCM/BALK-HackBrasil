from datetime import date

import pytest

from app import db
from app.logistics import best_departure, haversine_km, load_destinations, plan_route, sample_route
from app.logistics.forecast import aggregate, coop_forecast
from app.models import Producer, Weather
from tests.conftest import NOW, make_hours


def test_haversine():
    assert haversine_km(0, 0, 0, 1) == pytest.approx(111.19, abs=0.1)
    assert haversine_km(-15, -48, -15, -48) == 0


def test_sample_route_100km_a_cada_20km():
    coords = [[-48.0, -15.0], [-48.0, -14.1]]  # ~100 km para o norte
    pts = sample_route(coords, 20)
    kms = [round(p[2]) for p in pts]
    assert kms == [0, 20, 40, 60, 80, 100]
    assert pts[0][:2] == (-15.0, -48.0) and pts[-1][0] == pytest.approx(-14.1, abs=0.01)


def test_sample_route_varios_segmentos_soma_certa():
    coords = [[-48, -15], [-48, -14.5], [-47.5, -14.5]]
    pts = sample_route(coords, 20)
    total = haversine_km(-15, -48, -14.5, -48) + haversine_km(-14.5, -48, -14.5, -47.5)
    assert pts[-1][2] == pytest.approx(total, abs=0.6)
    assert all(b[2] > a[2] for a, b in zip(pts, pts[1:]))


def test_best_departure_foge_da_chuva_na_origem_e_no_caminho():
    origem = Weather(hours=make_hours(rain_mm=lambda i: 3.0 if i < 6 else 0.0))
    meio = Weather(hours=make_hours(rain_mm=lambda i: 2.0 if i in (7,) else 0.0))
    pts = [(-15.0, -48.0, 0.0), (-15.5, -48.0, 60.0)]
    r = best_departure(pts, [origem, meio], 48, 60)
    assert r["chuva_mm"] == 0.0
    # saída na hora 6 chegaria ao 2º ponto na hora 7 (2 mm): a melhor é a 8ª hora (índice 7... 0 mm)
    idx = [h["time"] for h in origem.hours].index(r["saida"])
    assert idx >= 6 and r["chuva_mm"] < r["pior_mm"]


def test_best_departure_chuva_total_correta():
    w = Weather(hours=make_hours(rain_mm=lambda i: 1.0))
    r = best_departure([(0, 0, 0.0), (0, 0, 60.0)], [w, w], 48, 60)
    assert r["chuva_mm"] == 2.0 and r["saida"] == w.hours[0]["time"]


def test_plan_route_simulado_perto_do_pnb():
    p = Producer(id=1, phone="1", lat=-15.7347, lon=-48.0152)
    dest = next(d for d in load_destinations() if d["id"] == "coop")
    plan = plan_route(p, dest, NOW)
    assert plan["dist_km"] >= 50 and plan["rota_fonte"] == "linha_reta"
    assert plan["chuva_mm"] == 0.0 and plan["pior_mm"] > 0  # o cenário chuvoso só molha a origem à tarde
    assert plan["frete_rs"] == pytest.approx(plan["dist_km"] * 6.0, abs=6)
    assert 0 <= plan["hora"] < 24 and plan["melhor_saida"]


def test_forecast_agrega_por_dia():
    items = [{"dia": date(2026, 11, 27), "t": 24.5, "produtor": 1}, {"dia": date(2026, 11, 27), "t": 10.0, "produtor": 2},
             {"dia": date(2026, 11, 29), "t": 60.0, "produtor": 3}]
    rows = aggregate(items, date(2026, 11, 27), 7, 30)
    assert len(rows) == 7
    assert rows[0] == {"data": "2026-11-27", "toneladas": 34.5, "caminhoes": 2, "produtores": 2}
    assert rows[2]["caminhoes"] == 2 and rows[1]["caminhoes"] == 0


def test_coop_forecast_com_produtores_prontos():
    db.create_producer(Producer(phone="5500900006001", lat=-23.5874, lon=-46.6576, crop="soja", planting_date="2026-07-25",
                                consent=True, source="coopx", state="ATIVO"))
    db.create_producer(Producer(phone="5500900006002", lat=-23.5874, lon=-46.6576, crop="soja", planting_date="2026-11-01",
                                consent=True, source="coopx", state="ATIVO"))  # ainda não pronta
    f = coop_forecast("coopx", NOW)
    assert f["total_toneladas"] == pytest.approx(7.0 * 3.5, abs=0.1)
    assert sum(r["caminhoes"] for r in f["dias"]) == 1

