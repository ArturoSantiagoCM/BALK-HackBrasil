"""Índices espectrais do Sentinel-2 (reflectância 0..1 já com escala e deslocamento aplicados)."""
import numpy as np

SCL_OK = (4, 5)  # vegetação e solo nu (SCL: 3 sombra, 8/9 nuvem, 10 cirro, 11 neve são descartados)


def norm_diff(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(a - b) / (a + b), NaN onde a soma não é positiva."""
    with np.errstate(invalid="ignore", divide="ignore"):
        out = (a - b) / (a + b)
    return np.where(np.isfinite(out) & ((a + b) > 0), out, np.nan)


def ndvi(red, nir):
    """Vigor da vegetação: (NIR - Vermelho) / (NIR + Vermelho)."""
    return norm_diff(nir, red)


def ndmi(nir, swir):
    """Umidade da vegetação: (NIR - SWIR1) / (NIR + SWIR1). Baixa em estresse hídrico."""
    return norm_diff(nir, swir)


def ndre(nir, rededge):
    """Clorofila / nitrogênio relativo: (NIR - Borda do vermelho) / (NIR + Borda do vermelho)."""
    return norm_diff(nir, rededge)


def scene_mask(scl):
    """Máscara de pixels úteis pela classificação de cena. Sem SCL: tudo útil (quem chama baixa a confiança)."""
    if scl is None:
        return None
    return np.isin(scl, SCL_OK)


def apply_mask(arr, mask):
    return arr if mask is None else np.where(mask, arr, np.nan)
