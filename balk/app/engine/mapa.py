"""Mapa PNG: NDVI, declividade e nota de viabilidade (matplotlib sobre os rasters recortados)."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from app.engine.python_engine import load_layers  # noqa: E402
from app.models import Viability  # noqa: E402


def render_map(work_dir: Path, lat: float, lon: float, ranking: list[Viability], out: Path | None = None) -> Path:
    L = load_layers(work_dir, lat, lon)
    out = out or Path(work_dir) / "mapa.png"
    fig, ax = plt.subplots(1, 3, figsize=(12, 4), dpi=110)
    px, py = L["point"]
    tr = L["transform"]
    n_r, n_c = L["ndvi"].shape
    extent = (tr.c, tr.c + n_c * tr.a, tr.f + n_r * tr.e, tr.f)

    def draw(a, data, title, cmap, vmin, vmax):
        im = a.imshow(data, cmap=cmap, vmin=vmin, vmax=vmax, extent=extent)
        circ = plt.Circle((px, py), 150, fill=False, color="black", lw=1.5, ls="--")
        a.add_patch(circ)
        a.set_title(title, fontsize=10)
        a.set_xticks([]), a.set_yticks([])
        plt.colorbar(im, ax=a, fraction=0.046)

    draw(ax[0], L["ndvi"], "NDVI (nuvem mascarada)", "RdYlGn", 0, 1)
    if L["slope"] is not None:
        draw(ax[1], np.clip(L["slope"], 0, 30), "Declividade (%)", "YlOrBr", 0, 30)
    else:
        ax[1].axis("off")
    names = [v.crop for v in ranking][::-1]
    scores = [v.score for v in ranking][::-1]
    ax[2].barh(names, scores, color="#2e7d32")
    ax[2].set_xlim(0, 100)
    ax[2].set_title("Nota de viabilidade (0-100)", fontsize=10)
    for i, s in enumerate(scores):
        ax[2].text(s + 1, i, str(s), va="center", fontsize=9)
    fig.suptitle("BALK - estimativa orientativa; nao substitui um engenheiro agronomo", fontsize=9, y=0.02)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out)
    plt.close(fig)
    return out
