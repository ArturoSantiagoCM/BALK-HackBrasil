"""Teste de equivalência M3: NDVI com diferença < 0,01 e declividade < 1 ponto percentual entre os motores.

Só roda onde o QGIS existe (imagem qgis/qgis); aqui é ignorado. Resultado do teste deve ir para o README.
"""
import pytest

from app.data import simulated
from app.data.simulated import DEMO_POINTS
from app.engine.python_engine import analyze_python
from app.engine.qgis_engine import analyze_qgis, qgis_available

pytestmark = pytest.mark.skipif(not qgis_available(), reason="qgis_process não encontrado (sem QGIS neste ambiente)")


@pytest.mark.parametrize("nome", list(DEMO_POINTS))
def test_motores_equivalentes_nos_3_pontos(nome, tmp_path):
    p = DEMO_POINTS[nome]
    work = simulated.make_synthetic_package(tmp_path / nome, p["lat"], p["lon"], seed=1)
    a = analyze_python(work, p["lat"], p["lon"])
    b = analyze_qgis(work, p["lat"], p["lon"])
    assert abs(a.ndvi_mean - b.ndvi_mean) < 0.01
    assert abs(a.slope_mean_pct - b.slope_mean_pct) < 1.0
