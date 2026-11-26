"""M3: analyze(producer) escolhe o motor por ENGINE=qgis|python (mesma saída)."""
import logging

from app import config
from app.data.package import build_local_package
from app.engine.python_engine import analyze_python
from app.engine.qgis_engine import EngineUnavailable, analyze_qgis
from app.models import Producer, SpatialStats

log = logging.getLogger("balk.engine")


def analyze(producer: Producer) -> SpatialStats:
    work = build_local_package(producer)
    if config.engine_name() == "qgis":
        try:
            return analyze_qgis(work, producer.lat, producer.lon)
        except (EngineUnavailable, RuntimeError) as e:
            log.warning("motor QGIS indisponível (%s); usando Python", e)
    return analyze_python(work, producer.lat, producer.lon)
