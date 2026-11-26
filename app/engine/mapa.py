"""Mapa PNG com as camadas do motor geo: NDVI, NDMI, declividade, zonas de manejo, baixadas (TPI) e nota de viabilidade."""
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402

from app.engine.python_engine import analyze_with_products  # noqa: E402
from app.geo.pipeline import Products  # noqa: E402
from app.models import Viability  # noqa: E402


def render_map(work_dir: Path, lat: float, lon: float, ranking: list[Viability], out: Optional[Path] = None,
               products: Optional[Products] = None, rain_month_mm: Optional[float] = None) -> Path:
    P = products or analyze_with_products(work_dir, lat, lon, rain_month_mm)[1]
    out = out or Path(work_dir) / "mapa.png"
    tr = P.transform
    n_r, n_c = P.ndvi.shape
    extent = (tr.c, tr.c + n_c * tr.a, tr.f + n_r * tr.e, tr.f)
    fig, axes = plt.subplots(2, 3, figsize=(13, 8), dpi=100)
    ax = axes.ravel()

    def draw(a, data, title, cmap, vmin=None, vmax=None):
        if data is None:
            a.axis("off")
            return
        im = a.imshow(data, cmap=cmap, vmin=vmin, vmax=vmax, extent=extent)
        a.add_patch(plt.Circle(P.point, 150, fill=False, color="black", lw=1.5, ls="--"))
        a.set_title(title, fontsize=10)
        a.set_xticks([]), a.set_yticks([])
        plt.colorbar(im, ax=a, fraction=0.046)

    draw(ax[0], P.ndvi, "NDVI (vigor; nuvem mascarada)", "RdYlGn", 0, 1)
    draw(ax[1], P.ndmi, "NDMI (umidade da vegetação)", "BrBG", -0.1, 0.5)
    draw(ax[2], None if P.slope is None else np.clip(P.slope, 0, 30), "Declividade (%)", "YlOrBr", 0, 30)
    if P.zones is not None:
        zones = np.where(P.zones > 0, P.zones, np.nan)
        k = int(np.nanmax(zones))
        im = ax[3].imshow(zones, cmap=ListedColormap(["#d73027", "#fee08b", "#1a9850", "#4575b4", "#8073ac"][:k]),
                          vmin=0.5, vmax=k + 0.5, extent=extent)
        ax[3].add_patch(plt.Circle(P.point, 150, fill=False, color="black", lw=1.5, ls="--"))
        ax[3].set_title("Zonas de manejo (1 = mais fraca)", fontsize=10)
        ax[3].set_xticks([]), ax[3].set_yticks([])
        plt.colorbar(im, ax=ax[3], fraction=0.046, ticks=range(1, k + 1))
    else:
        ax[3].axis("off")
    draw(ax[4], P.tpi, "Posição no relevo (TPI, m): azul = baixada", "RdBu", -6, 6)
    names = [v.crop for v in ranking][::-1]
    scores = [v.score for v in ranking][::-1]
    ax[5].barh(names, scores, color="#2e7d32")
    ax[5].set_xlim(0, 100)
    ax[5].set_title("Nota de viabilidade (0-100)", fontsize=10)
    for i, s in enumerate(scores):
        ax[5].text(s + 1, i, str(s), va="center", fontsize=9)
    fig.suptitle("BALK - estimativa orientativa; nao substitui um engenheiro agronomo", fontsize=9, y=0.01)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out)
    plt.close(fig)
    return out
