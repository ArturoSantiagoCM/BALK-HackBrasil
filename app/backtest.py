"""Backtest simples das regras de geada e de chuva com histórico REAL do Open-Meteo.

Compara a previsão feita 1 dia antes (Previous Runs API, `*_previous_day1`) com o que ocorreu segundo a reanálise
ERA5 (Historical Weather API). Mede acerto de eventos (acerto, perda, alarme falso) e erro da temperatura.

LIMITES (dizer sempre junto com o número): a "verdade" é uma reanálise em grade de ~9-25 km, NÃO uma estação do
INMET na lavoura; a reanálise suaviza mínimas extremas e costuma não pegar geada local. Serve para ver o comportamento da
regra e do limite, não para prometer taxa de acerto ao produtor. Uso gratuito do Open-Meteo: só não comercial.
"""
from collections import defaultdict
from datetime import date, datetime
from typing import Callable, Optional

import requests

from app import config

PREV_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
ARCH_URL = "https://archive-api.open-meteo.com/v1/archive"
TZ = "America/Sao_Paulo"

# pontos de inverno no Sul (geada) e um de controle em clima quente; coordenadas de municípios, não de lavouras
DEFAULT_POINTS = [("Passo Fundo (RS)", -28.2628, -52.4067), ("Vacaria (RS)", -28.5122, -50.9339),
                  ("Lages (SC)", -27.8161, -50.3262), ("Guarapuava (PR)", -25.3907, -51.4628),
                  ("Sorriso (MT), controle", -12.5425, -55.7211)]


def _get(url: str, params: dict) -> dict:
    last = None
    for _ in range(2):
        try:
            r = requests.get(url, params=params, timeout=40)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"Open-Meteo falhou: {last}")


def fetch_hourly(lat: float, lon: float, start: str, end: str) -> dict:
    """Previsão de 1 dia antes e reanálise, por hora, alinhadas pelo horário local."""
    base = {"latitude": lat, "longitude": lon, "start_date": start, "end_date": end, "timezone": TZ}
    prev = _get(PREV_URL, {**base, "hourly": "temperature_2m_previous_day1,precipitation_previous_day1"})["hourly"]
    arch = _get(ARCH_URL, {**base, "hourly": "temperature_2m,precipitation"})["hourly"]
    truth = dict(zip(arch["time"], zip(arch["temperature_2m"], arch["precipitation"])))
    rows = []
    for t, ft, fp in zip(prev["time"], prev["temperature_2m_previous_day1"], prev["precipitation_previous_day1"]):
        if t in truth:
            rows.append({"time": t, "fc_t": ft, "fc_p": fp, "tr_t": truth[t][0], "tr_p": truth[t][1]})
    return {"rows": rows}


def night_minima(rows: list[dict], key: str, hours=range(0, 10), min_valid: int = 8) -> dict[date, float]:
    """Mínima da madrugada (0h-9h locais) de cada dia, só se houver horas suficientes com dado."""
    by_day = defaultdict(list)
    for r in rows:
        t = datetime.fromisoformat(r["time"])
        if t.hour in hours and r[key] is not None:
            by_day[t.date()].append(r[key])
    return {d: min(v) for d, v in by_day.items() if len(v) >= min_valid}


def daily_sums(rows: list[dict], key: str, min_valid: int = 20) -> dict[date, float]:
    by_day = defaultdict(list)
    for r in rows:
        if r[key] is not None:
            by_day[datetime.fromisoformat(r["time"]).date()].append(r[key])
    return {d: sum(v) for d, v in by_day.items() if len(v) >= min_valid}


def confusion(pairs: list[tuple[float, float]], fc_limit: float, truth_limit: float, event: str = "le") -> dict:
    """Evento = valor <= limite (geada) ou >= limite (chuva). pairs = (previsto, ocorrido)."""
    hit = (lambda v, lim: v <= lim) if event == "le" else (lambda v, lim: v >= lim)
    tp = fp = fn = tn = 0
    for fc, tr in pairs:
        f, t = hit(fc, fc_limit), hit(tr, truth_limit)
        tp += f and t
        fp += f and not t
        fn += (not f) and t
        tn += (not f) and not t
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else None
    return {"n": len(pairs), "eventos_reais": tp + fn, "acertos": tp, "alarmes_falsos": fp, "perdas": fn, "sem_evento": tn,
            "precisao": prec, "recall": rec, "f1": f1}


def _errors(pairs: list[tuple[float, float]]) -> dict:
    if not pairs:
        return {"mae": None, "vies": None}
    d = [f - t for f, t in pairs]
    return {"mae": sum(abs(x) for x in d) / len(d), "vies": sum(d) / len(d)}


def evaluate_point(data: dict, frost_limit: float, rain_limit_mm: float = 5.0, margins=(0.0, 1.0, 2.0)) -> dict:
    rows = data["rows"]
    fc, tr = night_minima(rows, "fc_t"), night_minima(rows, "tr_t")
    pairs = [(fc[d], tr[d]) for d in fc if d in tr]
    rain_fc, rain_tr = daily_sums(rows, "fc_p"), daily_sums(rows, "tr_p")
    rpairs = [(rain_fc[d], rain_tr[d]) for d in rain_fc if d in rain_tr]
    return {
        "noites": len(pairs), "dias": len(rpairs), "temperatura": _errors(pairs),
        "geada": confusion(pairs, frost_limit, frost_limit, "le"),
        # sensibilidade: alertar com a previsão até X graus acima do limite troca alarme falso por menos perdas
        "geada_margem": {m: confusion(pairs, frost_limit + m, frost_limit, "le") for m in margins},
        "chuva": confusion(rpairs, rain_limit_mm, rain_limit_mm, "ge"), "chuva_limite_mm": rain_limit_mm}


def run_backtest(points=None, periods=None, fetch: Optional[Callable] = None) -> dict:
    """Roda todos os pontos e períodos e soma os resultados. `fetch` permite testar sem rede."""
    fetch = fetch or fetch_hourly
    points = points or DEFAULT_POINTS
    periods = periods or [("2024-05-01", "2024-09-30"), ("2025-05-01", "2025-09-30")]
    limit = float(config.rules()["geada"]["tmin"])
    per_point, all_rows = [], []
    for name, lat, lon in points:
        rows = []
        for start, end in periods:
            rows += fetch(lat, lon, start, end)["rows"]
        per_point.append({"ponto": name, "lat": lat, "lon": lon, **evaluate_point({"rows": rows}, limit)})
        all_rows += [{**r, "time": r["time"]} for r in rows]
    # total: soma as contagens (não mistura pontos dentro de uma mesma noite)
    total = {"geada": _sum_conf([p["geada"] for p in per_point]), "chuva": _sum_conf([p["chuva"] for p in per_point]),
             "geada_margem": {m: _sum_conf([p["geada_margem"][m] for p in per_point]) for m in per_point[0]["geada_margem"]},
             "noites": sum(p["noites"] for p in per_point)}
    return {"limite_geada_c": limit, "periodos": periods, "pontos": per_point, "total": total,
            "gerado_em": datetime.now().isoformat(timespec="seconds"), "fonte_previsao": PREV_URL, "fonte_verdade": ARCH_URL}


def _sum_conf(items: list[dict]) -> dict:
    keys = ("n", "eventos_reais", "acertos", "alarmes_falsos", "perdas", "sem_evento")
    c = {k: sum(i[k] for i in items) for k in keys}
    tp, fp, fn = c["acertos"], c["alarmes_falsos"], c["perdas"]
    c["precisao"] = tp / (tp + fp) if tp + fp else None
    c["recall"] = tp / (tp + fn) if tp + fn else None
    c["f1"] = 2 * c["precisao"] * c["recall"] / (c["precisao"] + c["recall"]) if c["precisao"] and c["recall"] else None
    return c


def _pct(x) -> str:
    return "-" if x is None else f"{100 * x:.0f}%"


def to_markdown(res: dict) -> str:
    L = [f"# Backtest das regras de geada e chuva ({res['gerado_em'][:10]})", "",
         "Previsão feita **1 dia antes** (Open-Meteo Previous Runs API) contra a **reanálise ERA5** (Open-Meteo Historical Weather API), por hora, no horário de Brasília.",
         "", "**Leia isto antes do número:** a verdade aqui é uma reanálise em grade, **não uma estação do INMET na lavoura**. A reanálise suaviza as "
         "mínimas e costuma não registrar geada local; então o recorte mostra o comportamento da regra, não uma promessa de acerto ao produtor. "
         "Uso gratuito do Open-Meteo é só não comercial.", "",
         f"Períodos: {', '.join(a + ' a ' + b for a, b in res['periodos'])}. Evento de geada: mínima da madrugada (0h-9h) <= {res['limite_geada_c']:g} °C.", "",
         "## Geada por ponto (alertando quando a previsão <= limite)", "",
         "| Ponto | Noites | Geadas reais | Acertos | Alarmes falsos | Perdas | Precisão | Recall | Erro médio (°C) | Viés (°C) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for p in res["pontos"]:
        g = p["geada"]
        L.append(f"| {p['ponto']} | {p['noites']} | {g['eventos_reais']} | {g['acertos']} | {g['alarmes_falsos']} | {g['perdas']} | "
                 f"{_pct(g['precisao'])} | {_pct(g['recall'])} | {p['temperatura']['mae']:.2f} | {p['temperatura']['vies']:+.2f} |")
    t = res["total"]["geada"]
    L += [f"| **Total** | {res['total']['noites']} | {t['eventos_reais']} | {t['acertos']} | {t['alarmes_falsos']} | {t['perdas']} | "
          f"{_pct(t['precisao'])} | {_pct(t['recall'])} | | |", "",
          "## Quanto de margem no limite? (previsão <= limite + margem)", "",
          "| Margem | Acertos | Alarmes falsos | Perdas | Precisão | Recall |", "|---|---|---|---|---|---|"]
    for m, c in res["total"]["geada_margem"].items():
        L.append(f"| +{float(m):g} °C | {c['acertos']} | {c['alarmes_falsos']} | {c['perdas']} | {_pct(c['precisao'])} | {_pct(c['recall'])} |")
    c = res["total"]["chuva"]
    L += ["", f"## Chuva forte (dia com {res['pontos'][0]['chuva_limite_mm']:g} mm ou mais)", "",
          f"Dias avaliados: {c['n']} · eventos reais: {c['eventos_reais']} · acertos: {c['acertos']} · alarmes falsos: {c['alarmes_falsos']} · "
          f"perdas: {c['perdas']} · precisão {_pct(c['precisao'])} · recall {_pct(c['recall'])}.", "",
          "A chuva em grade é ainda mais incerta que a temperatura (chuva local de verão em pancadas quase nunca aparece igual na previsão e na reanálise).", ""]
    return "\n".join(L)
