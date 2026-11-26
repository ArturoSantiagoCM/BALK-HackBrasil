"""Relações entre camadas: o que o BALK tem de seu em cima do relevo e dos índices.

Tudo aqui é heurística explicável. As que dependem de calibração agronômica estão marcadas [H] (hipótese a validar)
e os números ficam em rules.yaml (bloco `geo`), nunca no código.
"""
from typing import Optional

import numpy as np

from app.geo.terrain import compass


def management_zones(features: dict, mask: np.ndarray, k: int = 3, pixel_area_m2: float = 100.0,
                     min_pixels: int = 30):
    """Zonas de manejo por k-means (numpy puro, determinístico) sobre NDVI, declividade, TPI e NDMI.

    Devolve (rótulos, zonas). Rótulo 0 = fora da análise; 1..k ordenados do NDVI mais fraco ao mais forte.
    """
    names = list(features)
    valid = mask.copy()
    for a in features.values():
        valid &= np.isfinite(a)
    labels = np.zeros(mask.shape, dtype="int16")
    n = int(valid.sum())
    if n < min_pixels:
        return labels, []
    k = max(1, min(k, n // 10))
    X = np.stack([features[nm][valid] for nm in names], axis=1).astype("float64")
    mu, sd = X.mean(0), X.std(0)
    Z = (X - mu) / np.where(sd > 1e-9, sd, 1.0)
    order = np.argsort(Z.sum(1))
    centers = Z[order[[int((i + 0.5) / k * n) for i in range(k)]]].copy()  # início determinístico por quantis
    for _ in range(30):
        d = ((Z[:, None, :] - centers[None, :, :]) ** 2).sum(2)
        lab = d.argmin(1)
        new = np.array([Z[lab == j].mean(0) if (lab == j).any() else centers[j] for j in range(k)])
        if np.allclose(new, centers):
            break
        centers = new
    ndvi_i = names.index("ndvi")
    rank = np.argsort(np.argsort([X[lab == j, ndvi_i].mean() if (lab == j).any() else np.inf for j in range(k)]))
    labels[valid] = rank[lab] + 1
    zones = []
    for j in range(k):
        sel = lab == j
        if not sel.any():
            continue
        zid = int(rank[j]) + 1
        z = {"id": zid, "share_pct": round(float(100.0 * sel.sum() / n), 1),
             "area_ha": round(float(sel.sum() * pixel_area_m2 / 10000.0), 2),
             "label": "fraca" if zid == 1 and k > 1 else ("forte" if zid == k and k > 1 else "media")}
        for nm, col in zip(names, X.T):
            z[f"{nm}_mean"] = round(float(col[sel].mean()), 3)
        zones.append(z)
    zones.sort(key=lambda z: z["id"])
    return labels, zones


def weak_area(ndvi: np.ndarray, aoi: np.ndarray, transform, point, ref_mean: Optional[float],
              ref_std: Optional[float], n_std: float = 1.0, min_pct: float = 5.0, centre_m: float = 25.0) -> dict:
    """Parte da área com NDVI abaixo de (referência - n desvios) e a direção em que ela está em relação ao ponto."""
    ok = aoi & np.isfinite(ndvi)
    if ref_mean is None or not ref_std or ok.sum() == 0:
        return {"pct": None, "dir": None}
    weak = ok & (ndvi < ref_mean - n_std * ref_std)
    pct = round(100.0 * weak.sum() / ok.sum(), 1)
    if pct < min_pct:
        return {"pct": pct, "dir": None}
    rows, cols = np.nonzero(weak)
    xs = transform.c + (cols + 0.5) * transform.a
    ys = transform.f + (rows + 0.5) * transform.e
    dx, dy = xs.mean() - point[0], ys.mean() - point[1]
    if np.hypot(dx, dy) < centre_m:
        return {"pct": pct, "dir": "C"}  # espalhada em volta do centro
    return {"pct": pct, "dir": compass(float(np.degrees(np.arctan2(dx, dy))))}


def erosion_index(slope_pct: Optional[np.ndarray], ndvi: np.ndarray, aoi: np.ndarray, clay_pct: Optional[float],
                  rain_month_mm: Optional[float], cfg: dict):
    """Índice 0..1 de risco de erosão, relativo (NÃO é perda de solo em t/ha). [H]

    índice = S x (0,4 R + 0,4 C + 0,2 K), cortado em 0..1, com
      S = declividade / declive_ref_pct (a declividade "liga" o risco: terreno plano dá ~0),
      R = chuva mensal média / chuva_ref_mm_mes, C = cobertura = 1 - NDVI, K = solo (argila: mais argila, menos erodível).
    Referências e cortes (baixo_ate, medio_ate) vêm de rules.yaml, bloco `erosao`.
    """
    if slope_pct is None:
        return None, None
    S = np.clip(np.where(aoi, slope_pct, np.nan) / cfg.get("declive_ref_pct", 15.0), 0.0, 1.5)
    R = float(np.clip((rain_month_mm if rain_month_mm is not None else 100.0) / cfg.get("chuva_ref_mm_mes", 250.0), 0.0, 1.5))
    K = 0.8 if clay_pct is None else float(np.clip(1.15 - 0.011 * clay_pct, 0.4, 1.0))
    C = np.clip(1.0 - np.where(np.isfinite(ndvi), ndvi, 0.5), 0.05, 1.0)  # sem NDVI: cobertura média
    idx = np.clip(S * (0.4 * R + 0.4 * C + 0.2 * K), 0.0, 1.0)
    ok = aoi & np.isfinite(idx)
    if not ok.any():
        return None, None
    m = float(idx[ok].mean())
    return round(m, 3), ("baixo" if m <= cfg.get("baixo_ate", 0.25) else "medio" if m <= cfg.get("medio_ate", 0.6) else "alto")


def frost_offset(cold_index: Optional[np.ndarray], aoi: np.ndarray, max_offset_c: float) -> Optional[float]:
    """Quanto mais frio (°C, negativo) o ponto mais baixo da área fica em relação à previsão do ponto. [H]"""
    if cold_index is None:
        return None
    v = cold_index[aoi & np.isfinite(cold_index)]
    if v.size == 0:
        return None
    return round(-max_offset_c * float(np.percentile(v, 90)), 1)


def moisture_class(ndmi_mean: Optional[float], low: float = 0.1, high: float = 0.3) -> Optional[str]:
    if ndmi_mean is None:
        return None
    return "baixa" if ndmi_mean < low else ("alta" if ndmi_mean >= high else "media")


def water_balance(hours: list[dict]) -> dict:
    """Chuva prevista menos ET0 nas próximas horas (mm). Saldo negativo = a lavoura perde mais água do que ganha."""
    rain = sum(h.get("rain_mm") or 0.0 for h in hours)
    et0 = sum(h.get("et0") or 0.0 for h in hours)
    return {"chuva_mm": round(rain, 1), "et0_mm": round(et0, 1), "saldo_mm": round(rain - et0, 1), "horas": len(hours)}


def water_attention(moisture: Optional[str], saldo_mm: float, limit_mm: float = -5.0) -> bool:
    """Umidade da vegetação baixa E saldo hídrico previsto negativo: vale chamar a atenção (sem prescrever)."""
    return moisture == "baixa" and saldo_mm <= limit_mm
