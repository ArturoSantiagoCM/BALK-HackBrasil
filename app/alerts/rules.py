"""M5: regras determinísticas. O modelo de linguagem NÃO decide nada aqui."""
from datetime import datetime, timedelta
from typing import Optional

from app import config
from app.alerts.calc import confidence_from, delta_t, zscore
from app.models import Alert, Producer, SpatialStats, Weather


def _t(h: dict) -> datetime:
    return datetime.fromisoformat(h["time"])


def _hours_ahead(t: datetime, now: datetime) -> float:
    return max(0.0, (t - now).total_seconds() / 3600)


def _ok_spray(h: dict, c: dict) -> bool:
    t = _t(h)
    dt = delta_t(h["temp"], h["rh"])
    return (c["hora_ini"] <= t.hour < c["hora_fim"] and c.get("temp_min", -99) <= h["temp"] <= c["temp_max"]
            and c["vento_min"] <= h["wind_kmh"] <= c["vento_max"] and h["rh"] >= c["rh_min"]
            and h["rain_prob"] <= c["chuva_prob_max"] and h["rain_mm"] <= 0.2
            and c["delta_t_min"] <= dt <= c["delta_t_max"])


def evaluate_spraying(weather: Weather, cfg: Optional[dict] = None, now: Optional[datetime] = None) -> Optional[Alert]:
    """Melhor janela de 3 horas nas próximas 72 h. Sempre devolve 1 alerta (pulverizar, adiar ou evitar)."""
    c = cfg or config.rules()["pulverizacao"]
    now = now or datetime.now()
    hrs = weather.hours
    n = c["janela_horas"]
    found = None
    for i in range(len(hrs) - n + 1):
        if all(_ok_spray(h, c) for h in hrs[i:i + n]):
            found = i
            break
    if found is None:
        nxt = hrs[:24]
        ev = {"modo": "evitar", "vento_max": round(max(h["wind_kmh"] for h in nxt), 1),
              "chuva_prob_max": round(max(h["rain_prob"] for h in nxt)),
              "temp_max": round(max(h["temp"] for h in nxt), 1), "horas_analisadas": len(hrs)}
        return Alert(type="pulverizacao", action="Evite pulverizar nas próximas 72 horas.", window=None,
                     evidence=ev, confidence=confidence_from(0, ev["chuva_prob_max"]),
                     why="Vento, chuva ou calor fora dos limites em todas as janelas de 3 horas.")
    win = hrs[found:found + n]
    start, end = _t(win[0]), _t(win[-1]) + timedelta(hours=1)
    ahead = _hours_ahead(start, now)
    rp = max(h["rain_prob"] for h in win)
    ev = {"modo": "agora" if ahead <= 24 else "adiar", "dia_offset": (start.date() - now.date()).days,
          "weekday": start.weekday(), "inicio_h": start.hour, "fim_h": end.hour,
          "temp": round(sum(h["temp"] for h in win) / n, 1), "vento_kmh": round(max(h["wind_kmh"] for h in win), 1),
          "rh": round(sum(h["rh"] for h in win) / n), "chuva_prob": round(rp),
          "delta_t": round(sum(delta_t(h["temp"], h["rh"]) for h in win) / n, 1)}
    window = f"{start.hour:02d}h-{end.hour:02d}h"
    action = (f"Pulverize das {start.hour}h às {end.hour}h." if ev["modo"] == "agora"
              else f"Adie a pulverização para {start:%d/%m}, das {start.hour}h às {end.hour}h.")
    return Alert(type="pulverizacao", action=action, window=window, evidence=ev,
                 confidence=confidence_from(ahead, rp),
                 why="Temperatura, vento, umidade e chance de chuva dentro dos limites nesta janela.")


def evaluate_frost(weather: Weather, cfg: Optional[dict] = None, now: Optional[datetime] = None,
                   relief_offset_c: float = 0.0) -> Optional[Alert]:
    """Geada: mínima prevista <= limite. `relief_offset_c` (<= 0, do motor geo) é o quanto mais frio o ponto baixo
    da área fica que a previsão do ponto (ar frio acumula em baixadas). [H] hipótese a validar com agrônomo."""
    c = cfg or config.rules()["geada"]
    now = now or datetime.now()
    off = min(0.0, relief_offset_c or 0.0)
    cold = [i for i, h in enumerate(weather.hours) if h["temp"] + off <= c["tmin"]]
    if not cold:
        return None
    i0 = cold[0]
    run = [i0]
    for i in cold[1:]:
        if i == run[-1] + 1:
            run.append(i)
        else:
            break
    seg = [weather.hours[i] for i in run]
    start, end = _t(seg[0]), _t(seg[-1]) + timedelta(hours=1)
    forecast_min = min(h["temp"] for h in seg)
    tmin = forecast_min + off
    ahead = _hours_ahead(start, now)
    ev = {"tmin": round(tmin, 1), "dia_offset": (start.date() - now.date()).days, "weekday": start.weekday(),
          "inicio_h": start.hour, "fim_h": end.hour, "limite": c["tmin"]}
    if off <= -0.3:  # o relevo pesou: mostra a previsão do ponto e a do ponto mais baixo
        ev.update({"modo": "relevo", "tmin_previsto": round(forecast_min, 1)})
    return Alert(type="geada", action="Proteja a lavoura sensível antes da madrugada.",
                 window=f"{start.hour:02d}h-{end.hour:02d}h", evidence=ev,
                 confidence=confidence_from(ahead, seg[0]["rain_prob"]),
                 why=f"Mínima de {tmin:.0f} C na área, abaixo do limite de {c['tmin']} C.")


def evaluate_stress(stats: Optional[SpatialStats], ndvi_history: Optional[dict] = None,
                    cfg: Optional[dict] = None) -> Optional[Alert]:
    """z-score do NDVI contra o histórico da época; sem histórico, contra a vizinhança (confiança baixa)."""
    c = cfg or config.rules()["estresse"]
    if stats is None or stats.ndvi_mean is None:
        return None
    if ndvi_history and ndvi_history.get("std"):
        z = zscore(stats.ndvi_mean, ndvi_history["mean"], ndvi_history["std"])
        ref = ndvi_history.get("referencia", "historico")  # safras anteriores (média) ou série recente da safra (baixa)
        conf = "media" if ref == "historico" else "baixa"
    else:
        z = zscore(stats.ndvi_mean, stats.ndvi_ref_mean, stats.ndvi_ref_std) if stats.ndvi_ref_mean is not None else None
        conf, ref = "baixa", "vizinhanca"
    pct, direc = stats.weak_area_pct, stats.weak_area_dir
    localized = bool(pct is not None and direc and pct >= c.get("area_fraca_min_pct", 5))
    z_hit = z is not None and z < c["z_max"]
    weak_hit = pct is not None and pct >= c.get("area_fraca_alerta_pct", 25)
    if not (z_hit or weak_hit):
        return None
    ev = {"z": round(z, 2) if z is not None else None, "ndvi": stats.ndvi_mean, "referencia": ref}
    if localized:  # o motor geo achou ONDE está a parte fraca da área
        ev.update({"modo": "localizado", "pct": pct, "direcao": direc})
        if ev["z"] is None:
            ev.pop("z")
    return Alert(type="estresse", action="Vale conferir a lavoura nesta semana.", window=None,
                 evidence=ev, confidence=conf, why="O vigor da área está bem abaixo do esperado para a época.")


def evaluate_harvest(producer: Producer, weather: Weather, cfg: Optional[dict] = None,
                     now: Optional[datetime] = None, crops: Optional[dict] = None) -> Optional[Alert]:
    """Colheita: lavoura pronta (ciclo) e 48 h seguidas com pouca chuva (soma <= limite)."""
    from app.viability import load_crops
    c = cfg or config.rules()["colheita"]
    now = now or datetime.now()
    if not producer.crop or not producer.planting_date:
        return None
    crop = (crops or load_crops()).get(producer.crop)
    if not crop:
        return None
    days = (now.date() - datetime.fromisoformat(producer.planting_date).date()).days
    if days < crop["ciclo_dias"] - c["margem_dias_ciclo"]:
        return None
    hrs, n = weather.hours, c["horas"]
    for i in range(len(hrs) - n + 1):
        seg = hrs[i:i + n]
        mm = sum(h["rain_mm"] for h in seg)
        if mm <= c["chuva_mm_max"]:
            start = _t(seg[0])
            ahead = _hours_ahead(start, now)
            ev = {"modo": "janela", "dia_offset": (start.date() - now.date()).days, "weekday": start.weekday(),
                  "inicio_h": start.hour, "horas": n, "chuva_mm": round(mm, 1), "cultura": producer.crop}
            return Alert(type="colheita", action=f"Janela de colheita de {n} horas a partir das {start.hour}h.",
                         window=f"{start.hour:02d}h+{n}h", evidence=ev,
                         confidence=confidence_from(ahead, max(h["rain_prob"] for h in seg)),
                         why=f"Chuva esperada de {mm:.0f} mm em {n} horas.")
    ev = {"modo": "sem_janela", "horas": n, "cultura": producer.crop, "dia_offset": 0}
    return Alert(type="colheita", action=f"Sem {n} horas secas nos próximos 3 dias; adie a colheita.", window=None,
                 evidence=ev, confidence="media", why="Chuva prevista acima do limite em todas as janelas.")
