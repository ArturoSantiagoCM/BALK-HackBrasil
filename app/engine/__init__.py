"""M3: analyze(producer) escolhe o motor por ENGINE=qgis|python (mesma saída)."""
import logging
from typing import Optional

from app import config
from app.data.package import build_local_package
from app.engine.python_engine import analyze_python
from app.engine.qgis_engine import EngineUnavailable, analyze_qgis
from app.models import Producer, SpatialStats

log = logging.getLogger("balk.engine")


def analyze(producer: Producer, rain_month_mm: Optional[float] = None, polygon: Optional[dict] = None,
            key: Optional[str] = None) -> SpatialStats:
    """rain_month_mm (chuva mensal média do histórico) alimenta o índice de erosão do motor geo.
    `polygon`: talhão desenhado (GeoJSON); com ele a análise vale para o talhão de verdade, não para o círculo de 7 ha.
    O motor QGIS só conhece o círculo; com polígono usa-se sempre o motor Python."""
    work = build_local_package(producer, polygon=polygon, key=key)
    if config.engine_name() == "qgis" and not polygon:
        try:
            return analyze_qgis(work, producer.lat, producer.lon)
        except (EngineUnavailable, RuntimeError) as e:
            log.warning("motor QGIS indisponível (%s); usando Python", e)
    return analyze_python(work, producer.lat, producer.lon, rain_month_mm, polygon)
