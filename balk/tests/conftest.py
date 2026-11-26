import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

NOW = datetime(2026, 11, 27, 10, 0)  # quinta-feira, 10h (fora do horário quieto)


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    """Cada teste usa banco e pasta work próprios, dados simulados e motor Python."""
    monkeypatch.setenv("BALK_DB", str(tmp_path / "teste.db"))
    monkeypatch.setenv("BALK_WORK", str(tmp_path / "work"))
    monkeypatch.setenv("DATA_MODE", "simulado")
    monkeypatch.setenv("ENGINE", "python")


def make_hours(n=72, now=NOW, **over):
    """72 horas de clima constante e bom para pulverizar; over sobrescreve campos ou aceita funções f(i)->valor."""
    base = {"temp": 22.0, "rh": 65.0, "rain_prob": 10.0, "rain_mm": 0.0, "wind_kmh": 6.0, "et0": 0.1}
    start = now.replace(minute=0) + timedelta(hours=1)
    rows = []
    for i in range(n):
        row = dict(base)
        for k, v in over.items():
            row[k] = v(i) if callable(v) else v
        row["time"] = (start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00")
        rows.append(row)
    return rows
