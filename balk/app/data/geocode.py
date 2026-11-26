"""Geocodificação de município (Open-Meteo) com reserva offline.

Atenção: o município dá o centro da cidade, não a lavoura (location_precision="municipio").
"""
import unicodedata
from typing import Optional

import requests

from app import config

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

# reserva offline (centros de municípios usados na demo)
OFFLINE = {
    "sorriso": (-12.5425, -55.7211), "cuiaba": (-15.601, -56.0974), "londrina": (-23.3045, -51.1696),
    "passo fundo": (-28.2628, -52.4067), "rio verde": (-17.7923, -50.9192), "uberaba": (-19.7472, -47.9381),
    "cascavel": (-24.9578, -53.4595), "sao paulo": (-23.5505, -46.6333),
}


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()


def geocode(name: str, uf: Optional[str] = None) -> Optional[tuple[float, float]]:
    """Devolve (lat, lon) do município ou None."""
    if config.data_mode() != "simulado":
        try:
            r = requests.get(GEOCODE_URL, params={"name": name, "count": 5, "language": "pt",
                                                  "countryCode": "BR"}, timeout=10)
            r.raise_for_status()
            results = r.json().get("results") or []
            if results:
                return float(results[0]["latitude"]), float(results[0]["longitude"])
        except Exception:  # noqa: BLE001
            pass
    return OFFLINE.get(_norm(name))
