"""Funções de cálculo puras do M5 (cada uma com teste)."""
import math
from typing import Optional


def wet_bulb_stull(temp_c: float, rh_pct: float) -> float:
    """Temperatura de bulbo úmido, fórmula de Stull (2011), válida para UR 5-99% e T -20..50 C."""
    t, rh = temp_c, rh_pct
    return (t * math.atan(0.151977 * math.sqrt(rh + 8.313659)) + math.atan(t + rh) - math.atan(rh - 1.676331)
            + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh) - 4.686035)


def delta_t(temp_c: float, rh_pct: float) -> float:
    """Delta T = T - Tw (C). Teste: T=20, UR=50 -> Tw ~13,7 e Delta T ~6,3."""
    return temp_c - wet_bulb_stull(temp_c, rh_pct)


def gdd(tmax: float, tmin: float, tbase: float = 10.0) -> float:
    """Graus-dia: max(0, (tmax+tmin)/2 - tbase)."""
    return max(0.0, (tmax + tmin) / 2.0 - tbase)


def zscore(value: float, mean: float, std: float) -> Optional[float]:
    """z = (valor - média) / desvio; None se o desvio for zero (ou ausente)."""
    if std is None or std == 0:
        return None
    return (value - mean) / std


def confidence_from(hours_ahead: float, rain_prob: float) -> str:
    """alta: previsão das próximas 24 h e chuva <20% ou >80%; média: até 48 h; baixa: depois disso."""
    if hours_ahead <= 24 and (rain_prob < 20 or rain_prob > 80):
        return "alta"
    if hours_ahead <= 48:
        return "media"
    return "baixa"
