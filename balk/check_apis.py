"""Confere as APIs externas: imprime OK ou FALHA com a latência. Rode: python check_apis.py"""
import time

import requests

CHECKS = {
    "Open-Meteo previsão": ("https://api.open-meteo.com/v1/forecast",
                            {"latitude": -23.58, "longitude": -46.65, "hourly": "temperature_2m", "forecast_days": 1}),
    "Open-Meteo histórico": ("https://archive-api.open-meteo.com/v1/archive",
                             {"latitude": -23.58, "longitude": -46.65, "start_date": "2025-01-01",
                              "end_date": "2025-01-03", "daily": "temperature_2m_mean"}),
    "Open-Meteo geocodificação": ("https://geocoding-api.open-meteo.com/v1/search", {"name": "Sorriso", "count": 1}),
    "Earth Search (STAC)": ("https://earthsearch.aws.element84.com/v1/collections/sentinel-2-l2a", {}),
    "OSRM (demo)": ("https://router.project-osrm.org/route/v1/driving/-48.0,-15.7;-47.95,-16.25", {}),
}


def main() -> int:
    fails = 0
    for name, (url, params) in CHECKS.items():
        t0 = time.time()
        try:
            r = requests.get(url, params=params, timeout=15)
            ok = r.status_code == 200
        except Exception as e:  # noqa: BLE001
            ok, r = False, e
        ms = int((time.time() - t0) * 1000)
        print(f"{'OK    ' if ok else 'FALHA '} {name:28s} {ms:5d} ms" + ("" if ok else f"  ({r})"))
        fails += not ok
    return fails


if __name__ == "__main__":
    raise SystemExit(main())
