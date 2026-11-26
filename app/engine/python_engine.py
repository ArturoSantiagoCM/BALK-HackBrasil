"""M3: motor espacial em Python. É o motor geo do BALK (app/geo): relevo de Horn, NDVI/NDMI/NDRE e relações entre camadas.

Mesma saída (SpatialStats) do motor QGIS. O nome do arquivo evita "python.py"/"qgis.py" para não sombrear módulos.
"""
from pathlib import Path
from typing import Optional

from app.geo.pipeline import RADIUS_M, Products, run  # noqa: F401  (RADIUS_M reexportado)
from app.models import SpatialStats


def analyze_python(work_dir: Path, lat: float, lon: float, rain_month_mm: Optional[float] = None) -> SpatialStats:
    return run(Path(work_dir), lat, lon, rain_month_mm)[0]


def analyze_with_products(work_dir: Path, lat: float, lon: float,
                          rain_month_mm: Optional[float] = None) -> tuple[SpatialStats, Products]:
    """Igual a analyze_python, mas devolve também os arrays (para o mapa e para depurar)."""
    return run(Path(work_dir), lat, lon, rain_month_mm)
