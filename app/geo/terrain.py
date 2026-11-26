"""Relevo: declividade, aspecto, TPI, rugosidade e índice de acúmulo de ar frio.

Reimplementação independente (numpy) de métodos PUBLICADOS:
- Declividade e aspecto: janela 3x3 de Horn (1981), a mesma família de método do gdal:slope e do QGIS.
- TPI: Weiss (2001). Rugosidade: soma das diferenças ao quadrado até os 8 vizinhos (Riley et al. 1999).
Nenhum código do QGIS é copiado (o QGIS é GPL; ver docs/GUIA_PROGRAMADORES.md, seção "QGIS e licença").

Convenções: grade em metros (UTM), linha 0 = norte. Nodata = NaN. Aspecto = direção para onde a encosta
desce, em graus de bússola (0 = norte, 90 = leste).
"""
import numpy as np


def _pad_linear(z: np.ndarray) -> np.ndarray:
    """Borda de 1 pixel por extrapolação linear (2*borda - vizinho): planos inclinados continuam exatos."""
    if z.shape[0] < 3 or z.shape[1] < 3:
        raise ValueError("o relevo precisa de pelo menos 3 linhas e 3 colunas")
    p = np.empty((z.shape[0] + 2, z.shape[1] + 2), dtype="float64")
    p[1:-1, 1:-1] = z
    p[0, 1:-1] = 2 * z[0] - z[1]
    p[-1, 1:-1] = 2 * z[-1] - z[-2]
    p[1:-1, 0] = 2 * z[:, 0] - z[:, 1]
    p[1:-1, -1] = 2 * z[:, -1] - z[:, -2]
    p[0, 0], p[0, -1] = 2 * p[0, 1] - p[0, 2], 2 * p[0, -2] - p[0, -3]
    p[-1, 0], p[-1, -1] = 2 * p[-1, 1] - p[-1, 2], 2 * p[-1, -2] - p[-1, -3]
    return p


def _window(z: np.ndarray):
    """Os 9 vizinhos z11..z33 (linha, coluna; 1 = topo/esquerda). Vizinho NaN vira o valor central."""
    p = _pad_linear(z)
    h, w = z.shape
    c = z.astype("float64")
    out = {}
    for r in range(3):
        for k in range(3):
            v = p[r:r + h, k:k + w].copy()
            v = np.where(np.isfinite(v), v, c)
            out[(r + 1, k + 1)] = v
    return out


def slope_aspect(dem: np.ndarray, cell_x: float, cell_y: float) -> tuple[np.ndarray, np.ndarray]:
    """Declividade em % e aspecto em graus (NaN em terreno plano). cell_x/cell_y em metros (> 0)."""
    if cell_x <= 0 or cell_y <= 0:
        raise ValueError("tamanho de pixel precisa ser positivo")
    w = _window(dem)
    dzdx = ((w[1, 3] + 2 * w[2, 3] + w[3, 3]) - (w[1, 1] + 2 * w[2, 1] + w[3, 1])) / (8 * cell_x)  # leste - oeste
    dzdy = ((w[1, 1] + 2 * w[1, 2] + w[1, 3]) - (w[3, 1] + 2 * w[3, 2] + w[3, 3])) / (8 * cell_y)  # norte - sul
    slope_pct = np.hypot(dzdx, dzdy) * 100.0
    aspect = np.degrees(np.arctan2(-dzdx, -dzdy)) % 360.0  # para onde desce
    aspect = np.where(np.hypot(dzdx, dzdy) < 1e-6, np.nan, aspect)
    center = np.isfinite(dem)
    return np.where(center, slope_pct, np.nan), np.where(center, aspect, np.nan)


def slope_degrees(slope_pct: np.ndarray) -> np.ndarray:
    return np.degrees(np.arctan(slope_pct / 100.0))


def _box_sum_count(z: np.ndarray, r: int):
    """Soma e contagem de pixels válidos numa janela (2r+1)x(2r+1), truncada nas bordas (imagem integral)."""
    v = np.where(np.isfinite(z), z, 0.0).astype("float64")
    n = np.isfinite(z).astype("float64")
    s = np.pad(v.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    c = np.pad(n.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    h, w = z.shape
    i = np.arange(h)[:, None]
    j = np.arange(w)[None, :]
    r0, r1 = np.clip(i - r, 0, h), np.clip(i + r + 1, 0, h)
    c0, c1 = np.clip(j - r, 0, w), np.clip(j + r + 1, 0, w)
    tot = s[r1, c1] - s[r0, c1] - s[r1, c0] + s[r0, c0]
    cnt = c[r1, c1] - c[r0, c1] - c[r1, c0] + c[r0, c0]
    return tot, cnt


def box_mean(z: np.ndarray, r: int) -> np.ndarray:
    """Média numa janela (2r+1)x(2r+1), ignorando NaN."""
    tot, cnt = _box_sum_count(z, r)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cnt > 0, tot / cnt, np.nan)


def tpi(dem: np.ndarray, r_px: int) -> np.ndarray:
    """Topographic Position Index: cota - média dos vizinhos (sem o centro). Negativo = baixada; positivo = topo."""
    tot, cnt = _box_sum_count(dem, r_px)
    with np.errstate(invalid="ignore", divide="ignore"):
        others = np.where(cnt > 1, (tot - np.nan_to_num(dem)) / (cnt - 1), np.nan)
    out = np.where(np.isfinite(dem), dem - others, np.nan)
    h, w = dem.shape
    edge = np.zeros((h, w), dtype=bool)  # janela cortada pela borda dá TPI enviesado em encosta: descarta
    edge[:r_px, :] = edge[h - r_px:, :] = True
    edge[:, :r_px] = edge[:, w - r_px:] = True
    return np.where(edge, np.nan, out)


def roughness(dem: np.ndarray) -> np.ndarray:
    """Rugosidade: raiz da soma dos quadrados das diferenças aos vizinhos válidos (como no filtro de rugosidade do QGIS)."""
    p = _pad_linear(dem)
    h, w = dem.shape
    c = dem.astype("float64")
    acc = np.zeros_like(c)
    for r in range(3):
        for k in range(3):
            if (r, k) == (1, 1):
                continue
            d = p[r:r + h, k:k + w] - c
            acc += np.where(np.isfinite(d), d * d, 0.0)
    return np.where(np.isfinite(c), np.sqrt(acc), np.nan)


def cold_pool_index(tpi_arr: np.ndarray, slope_pct: np.ndarray, depression_ref_m: float = 5.0,
                    gentle_slope_pct: float = 8.0) -> np.ndarray:
    """0..1: quanto o pixel favorece o acúmulo de ar frio (baixada de pouca declividade). HIPÓTESE a validar."""
    depress = np.clip(-tpi_arr / depression_ref_m, 0.0, 1.0)
    gentle = np.where(slope_pct <= gentle_slope_pct, 1.0, 0.5)  # encosta forte drena o ar frio
    return depress * gentle


def compass(deg: float) -> str:
    """Ponto cardeal (8 direções) de um ângulo de bússola."""
    return ["N", "NE", "E", "SE", "S", "SO", "O", "NO"][int(((deg % 360) + 22.5) // 45) % 8]
