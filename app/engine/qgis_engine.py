"""M3: motor QGIS (qgis_process / PyQGIS). Chamada por subprocesso; um único processo QGIS.

STATUS: ver engine/run_chain.py. Sem QGIS instalado, levanta EngineUnavailable e o analyze()
cai para o motor Python.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

from app.models import SpatialStats

CHAIN = Path(__file__).with_name("run_chain.py")


class EngineUnavailable(RuntimeError):
    pass


def qgis_available() -> bool:
    return shutil.which("qgis_process") is not None


def analyze_qgis(work_dir: Path, lat: float, lon: float, timeout_s: int = 90) -> SpatialStats:
    if not qgis_available():
        raise EngineUnavailable("qgis_process não encontrado no PATH (use a imagem qgis/qgis)")
    py = os.getenv("QGIS_PYTHON", "python3")
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    proc = subprocess.run([py, str(CHAIN), str(work_dir), str(lat), str(lon)], capture_output=True,
                          text=True, timeout=timeout_s, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"run_chain.py falhou: {proc.stderr[-500:]}")
    last = proc.stdout.strip().splitlines()[-1]  # última linha = JSON
    data = json.loads(last)
    return SpatialStats(**{**data, "engine": "qgis"})
