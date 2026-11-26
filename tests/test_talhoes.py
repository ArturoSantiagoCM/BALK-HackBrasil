"""Talhões desenhados: validação de geometria no backend, área calculada de forma independente e análise do polígono."""
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pyproj import Transformer
from shapely.geometry import Polygon

from app import config, db, plots
from app.data import simulated
from app.engine.python_engine import analyze_python
from app.main import app
from app.models import Producer
from app.service import analyze_producer
from tests.conftest import NOW

client = TestClient(app)
LAT, LON = -23.5874, -46.6576


def quadrado(lat=LAT, lon=LON, lado_m=200.0, dx_m=0.0, dy_m=0.0) -> dict:
    """GeoJSON de um quadrado de `lado_m` metros com o canto sudoeste deslocado (dx, dy) do ponto."""
    dlat = lado_m / 111_320.0
    dlon = lado_m / (111_320.0 * math.cos(math.radians(lat)))
    x0, y0 = lon + dx_m / (111_320.0 * math.cos(math.radians(lat))), lat + dy_m / 111_320.0
    ring = [[x0, y0], [x0 + dlon, y0], [x0 + dlon, y0 + dlat], [x0, y0 + dlat], [x0, y0]]
    return {"type": "Polygon", "coordinates": [ring]}


def area_utm_ha(geo: dict) -> float:
    """Cálculo independente: projeta para UTM e usa a área plana."""
    poly = Polygon(geo["coordinates"][0])
    epsg = simulated.utm_epsg(poly.centroid.y, poly.centroid.x)
    t = Transformer.from_crs(4326, epsg, always_xy=True).transform
    from shapely.ops import transform
    return transform(t, poly).area / 10_000.0


# ---------- validação ----------
def test_poligono_valido_e_area_confere_com_calculo_independente_a_1_porcento():
    geo = quadrado(lado_m=300.0)  # ~9 ha
    poly, erros, area = plots.validate_polygon(geo)
    assert erros == [] and poly is not None
    assert abs(area - area_utm_ha(geo)) / area_utm_ha(geo) < 0.01
    assert abs(area - 9.0) < 0.2


def test_feature_do_geojson_tambem_e_aceita():
    _, erros, _ = plots.validate_polygon({"type": "Feature", "properties": {}, "geometry": quadrado()})
    assert erros == []


@pytest.mark.parametrize("nome,geo,trecho", [
    ("gravata", {"type": "Polygon", "coordinates": [[[-46.66, -23.58], [-46.65, -23.59], [-46.65, -23.58], [-46.66, -23.59], [-46.66, -23.58]]]}, "inválido"),
    ("nao fechado", {"type": "Polygon", "coordinates": [[[-46.66, -23.58], [-46.65, -23.58], [-46.65, -23.59], [-46.66, -23.59]]]}, "não fechado"),
    ("fora do Brasil", quadrado(lat=40.4, lon=-3.7), "fora do Brasil"),
    ("pequeno demais", quadrado(lado_m=15.0), "abaixo do mínimo"),
    ("grande demais", quadrado(lado_m=5000.0), "acima do máximo"),
    ("dois vertices", {"type": "Polygon", "coordinates": [[[-46.6, -23.5], [-46.5, -23.5]]]}, "pelo menos 3 vértices"),
    ("nao e poligono", {"type": "Point", "coordinates": [-46.6, -23.5]}, "Polygon"),
    ("lixo", {"type": "Polygon", "coordinates": "x"}, "inválidas"),
    ("nao numerico", {"type": "Polygon", "coordinates": [[[0, 0], [float("nan"), 1], [1, 1], [0, 0]]]}, "não numéricas"),
    ("com buraco", {"type": "Polygon", "coordinates": [quadrado(lado_m=500)["coordinates"][0], quadrado(lado_m=100, dx_m=100, dy_m=100)["coordinates"][0]]}, "buraco"),
])
def test_geometrias_invalidas_sao_recusadas_com_motivo_claro(nome, geo, trecho):
    poly, erros, _ = plots.validate_polygon(geo)
    assert poly is None and any(trecho in e for e in erros), (nome, erros)


def test_sobreposicao_relevante_e_recusada_mas_vizinho_encostado_passa():
    a = quadrado(lado_m=300.0)
    sobreposto = quadrado(lado_m=300.0, dx_m=100.0)  # ~67% em cima do primeiro
    assert any("sobrepõe" in e for e in plots.validate_polygon(sobreposto, [a])[1])
    vizinho = quadrado(lado_m=300.0, dx_m=300.0)  # encostado, sem invadir
    assert plots.validate_polygon(vizinho, [a])[1] == []


def test_limites_de_quantidade_e_de_area_total_vem_da_configuracao():
    lim = {**plots.limits(), "max_por_produtor": 2}
    a, b = quadrado(dx_m=0), quadrado(dx_m=400)
    assert plots.validate_polygon(quadrado(dx_m=800), [a, b], lim)[1][0].startswith("limite de 2 talhões")
    lim2 = {**plots.limits(), "area_total_max_ha": 10.0}
    assert any("área total" in e for e in plots.validate_polygon(quadrado(lado_m=300, dx_m=400), [quadrado(lado_m=300)], lim2)[1])
    assert plots.limits()["area_min_ha"] == config.rules()["talhoes"]["area_min_ha"]


# ---------- análise do polígono ----------
def test_analise_do_poligono_usa_so_os_pixels_do_talhao(tmp_path):
    work = simulated.make_synthetic_package(tmp_path / "p", LAT, LON, seed=1, relief="plano")
    circulo = analyze_python(work, LAT, LON)
    talhao = quadrado(lado_m=200.0, dx_m=-100.0, dy_m=-100.0)  # 200 x 200 m centrado = 4 ha
    s = analyze_python(work, LAT, LON, polygon=talhao)
    assert s.area_ha == pytest.approx(4.0, abs=0.35) and circulo.area_ha == pytest.approx(7.07, abs=0.3)
    assert s.ndvi_mean is not None and s.slope_mean_pct == pytest.approx(6.0, abs=1.0)
    meio = quadrado(lado_m=100.0, dx_m=-50.0, dy_m=-50.0)
    s2 = analyze_python(work, LAT, LON, polygon=meio)
    assert s2.area_ha == pytest.approx(1.0, abs=0.2)


def test_talhao_fora_da_cena_nao_quebra_e_fica_sem_dado(tmp_path):
    work = simulated.make_synthetic_package(tmp_path / "q", LAT, LON, seed=1)
    longe = quadrado(lado_m=200.0, dx_m=3000.0)  # 3 km a leste: fora do recorte de 1 km
    s = analyze_python(work, LAT, LON, polygon=longe)
    assert s.area_ha == 0.0 and s.ndvi_mean is None


# ---------- API e serviço ----------
def _produtor():
    return db.create_producer(Producer(phone="+5500900005001", lat=LAT, lon=LON, crop="soja", planting_date="2026-07-25",
                                       consent=True, state="ATIVO", channel="whatsapp"))


def test_api_cadastra_talhao_valido_e_recusa_o_invalido_com_a_lista_de_erros():
    p = _produtor()
    ok = client.post("/plots", json={"producer_id": p.id, "name": "Talhão 1", "geometry": quadrado(lado_m=300), "crop": "Milho",
                                     "planting_date": "2026-09-01"})
    assert ok.status_code == 200 and ok.json()["crop"] == "milho" and 8.5 < ok.json()["area_ha"] < 9.5
    nov = db.get_producer(p.id)
    assert nov.lat == pytest.approx(LAT, abs=0.01)  # o ponto vira o centro do primeiro talhão
    ruim = client.post("/plots", json={"producer_id": p.id, "name": "", "geometry": quadrado(lado_m=300, dx_m=100), "crop": "batata",
                                       "planting_date": "2030-01-01"})
    erros = ruim.json()["detail"]["erros"]
    assert ruim.status_code == 422 and any("sobrepõe" in e for e in erros) and any("cultura desconhecida" in e for e in erros) \
        and any("data de plantio" in e for e in erros) and any("nome" in e for e in erros)
    assert client.post("/plots", json={"producer_id": 999, "name": "x", "geometry": quadrado()}).status_code == 404
    assert len(client.get(f"/producers/{p.id}/plots").json()) == 1
    assert "geojson" not in client.get(f"/producers/{p.id}/plots").json()[0]


def test_analise_usa_o_talhao_com_a_cultura_dele_e_o_relatorio_mostra_o_contorno():
    p = _produtor()
    client.post("/plots", json={"producer_id": p.id, "name": "Talhão do fundo", "geometry": quadrado(lado_m=250), "crop": "milho",
                                "planting_date": "2026-07-15"})
    res = analyze_producer(p.id, full=True, now=NOW)
    assert res["plot"]["nome"] == "Talhão do fundo" and res["stats"]["area_ha"] == pytest.approx(res["plot"]["area_ha"], abs=0.5)
    assert res["ranking"][0]["crop"] == "milho"  # a cultura do talhão manda, não a do cadastro
    page = client.get("/r/" + res["report_token"]).text
    assert "Talhão do fundo" in page and "contorno tracejado" in page
    assert client.get(f"/r/{res['report_token']}/img/ndvi.png").status_code == 200


def test_exclusao_do_produtor_apaga_os_talhoes():
    p = _produtor()
    client.post("/plots", json={"producer_id": p.id, "name": "T", "geometry": quadrado()})
    assert db.list_plots(p.id)
    assert db.delete_producer(p.id)["plots"] == 1 and db.list_plots(p.id) == []


def test_apagar_talhao_so_do_proprio_produtor():
    a, b = _produtor(), db.create_producer(Producer(phone="+5500900005002", lat=LAT, lon=LON, consent=True, state="ATIVO"))
    pid = client.post("/plots", json={"producer_id": a.id, "name": "T", "geometry": quadrado()}).json()["id"]
    assert client.delete(f"/plots/{pid}", params={"producer_id": b.id}).status_code == 404  # produtor errado
    assert client.delete(f"/plots/{pid}", params={"producer_id": a.id}).status_code == 200
