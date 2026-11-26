"""Imagens do relatório detalhado, no estilo de um projeto de QGIS: título, escala, norte, coordenadas relativas,
legenda com unidade e a estatística da área. Cada imagem é um PNG separado (um mapa por assunto).

As coordenadas são em metros a partir do ponto da lavoura (o relatório não mostra coordenadas absolutas).
"""
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch, Patch, Polygon, Rectangle  # noqa: E402

from app import config  # noqa: E402
from app.engine.python_engine import analyze_with_products  # noqa: E402
from app.geo.pipeline import Products  # noqa: E402

GREEN, AMBER, RED, GREY = "#2e7d32", "#f9a825", "#c62828", "#9e9e9e"
FOOT = "BALK · estimativa orientativa a partir de satélite e clima · não substitui um engenheiro agrônomo"


def _extent(P: Products):
    tr = P.transform
    rows, cols = P.ndvi.shape
    px, py = P.point
    return (tr.c - px, tr.c + cols * tr.a - px, tr.f + rows * tr.e - py, tr.f - py)


def _grid_xy(P: Products):
    tr = P.transform
    rows, cols = np.indices(P.ndvi.shape)
    return tr.c + (cols + 0.5) * tr.a - P.point[0], tr.f + (rows + 0.5) * tr.e - P.point[1]


def _decorate(ax, P: Products, fonte: str):
    """Elementos de mapa: círculo da área, ponto, escala, seta do norte, eixos em metros."""
    xy = P.extra.get("polygon_xy")
    if xy:  # talhão desenhado: o contorno dele; sem talhão, o círculo de 150 m
        ax.add_patch(Polygon(xy, closed=True, fill=False, color="black", lw=1.8, ls="--", zorder=5))
    else:
        ax.add_patch(Circle((0, 0), 150, fill=False, color="black", lw=1.6, ls="--", zorder=5))
    ax.plot([0], [0], marker="+", color="black", ms=9, zorder=6)
    x0, x1, y0, y1 = _extent(P)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_xticks([-400, -200, 0, 200, 400])
    ax.set_yticks([-400, -200, 0, 200, 400])
    ax.tick_params(labelsize=7)
    ax.set_xlabel("metros a leste do ponto", fontsize=7)
    ax.set_ylabel("metros ao norte", fontsize=7)
    ax.grid(True, color="white", alpha=0.35, lw=0.5)
    # barra de escala de 200 m
    sx, sy = x0 + (x1 - x0) * 0.05, y0 + (y1 - y0) * 0.06
    ax.add_patch(Rectangle((sx, sy), 100, 12, fc="black", ec="black", zorder=7))
    ax.add_patch(Rectangle((sx + 100, sy), 100, 12, fc="white", ec="black", zorder=7))
    ax.text(sx + 100, sy + 22, "200 m", ha="center", fontsize=7, zorder=7,
            bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))
    # seta do norte
    ax.annotate("", xy=(0.94, 0.96), xytext=(0.94, 0.84), xycoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", color="black", lw=1.6), zorder=7)
    ax.text(0.94, 0.975, "N", transform=ax.transAxes, ha="center", fontsize=9, weight="bold", zorder=7,
            bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))
    ax.figure.text(0.01, 0.005, f"{fonte}  ·  {FOOT}", fontsize=5.5, color="#555")


def _stat_box(ax, arr, aoi, unit="", nd=2):
    v = arr[aoi & np.isfinite(arr)]
    if v.size:
        ax.text(0.98, 0.03, f"na área: mín {v.min():.{nd}f} · média {v.mean():.{nd}f} · máx {v.max():.{nd}f} {unit}",
                transform=ax.transAxes, ha="right", fontsize=6.5, zorder=8,
                bbox=dict(fc="white", ec="#999", alpha=0.85, pad=2))


def _save(fig, path: Path):
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def _raster_map(P, arr, title, cmap, vmin, vmax, label, path, fonte, unit="", nd=2, extra=None):
    fig, ax = plt.subplots(figsize=(6.4, 5.8))
    cm = plt.get_cmap(cmap).with_extremes(bad="white")
    im = ax.imshow(np.ma.masked_invalid(arr), cmap=cm, vmin=vmin, vmax=vmax, extent=_extent(P), zorder=1)
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
    cb.set_label(label, fontsize=8)
    cb.ax.tick_params(labelsize=7)
    ax.set_title(title, fontsize=11, weight="bold")
    if extra:
        extra(ax)
    _decorate(ax, P, fonte)
    _stat_box(ax, arr, P.aoi, unit, nd)
    _save(fig, path)


def _slope_arrows(P):
    def draw(ax):
        X, Y = _grid_xy(P)
        step = 12
        sl = P.slope[::step, ::step]
        asp = np.radians(P.aspect[::step, ::step])
        ok = np.isfinite(asp) & (sl > 2.0)
        ax.quiver(X[::step, ::step][ok], Y[::step, ::step][ok], np.sin(asp)[ok], np.cos(asp)[ok], color="black",
                  scale=26, width=0.003, zorder=4)
    return draw


def _zones_map(P, zones, path, fonte):
    k = int(np.nanmax(P.zones))
    colors = ["#d73027", "#fee08b", "#1a9850", "#4575b4", "#8073ac"][:k]
    fig, ax = plt.subplots(figsize=(6.4, 5.8))
    ax.imshow(np.where(P.zones > 0, P.zones, np.nan), cmap=ListedColormap(colors), vmin=0.5, vmax=k + 0.5,
              extent=_extent(P), zorder=1)
    ax.set_title("Zonas de manejo", fontsize=11, weight="bold")
    ax.legend(handles=[Patch(fc=colors[z["id"] - 1], ec="k",
                             label=f"Zona {z['id']} ({z['label']}): {z['share_pct']:.0f}% · NDVI {z['ndvi_mean']:.2f}")
                       for z in zones], loc="upper left", fontsize=7, framealpha=0.9)
    _decorate(ax, P, fonte)
    _save(fig, path)


def _anomaly_map(P, path, fonte):
    z = (P.ndvi - P.ref_mean) / P.ref_std
    weak = np.where(np.isfinite(z), (z < -1.0).astype(float), 0.0)
    X, Y = _grid_xy(P)

    def extra(ax):
        if weak.any() and not weak.all():
            ax.contour(X, Y, weak, levels=[0.5], colors="black", linewidths=1.3, zorder=4)
    _raster_map(P, z, "Onde a lavoura está mais fraca que o resto", "RdBu", -3, 3, "desvios em relação ao NDVI médio da cena",
                path, fonte, nd=1, extra=extra)


def _weather_chart(data: dict, path: Path):
    hrs = data["clima"]["horas"]
    if not hrs:
        return False
    t = [datetime.fromisoformat(h["time"]) for h in hrs]
    R = config.rules()
    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(8, 7), sharex=True)
    a1.plot(t, [h["temp"] for h in hrs], color="#d84315", lw=1.8, label="temperatura prevista (°C)")
    a1.axhline(R["geada"]["tmin"], color="#1565c0", ls="--", lw=1.2, label=f"limite de geada ({R['geada']['tmin']} °C)")
    off = data["relacoes"].get("geada_relevo_c") if data.get("relacoes") else None
    if off and off <= -0.3:
        a1.plot(t, [h["temp"] + off for h in hrs], color="#1565c0", lw=1, ls=":", label=f"ponto mais baixo ({off:+.1f} °C)")
    a1.set_ylabel("°C")
    a2.bar(t, [h["rain_mm"] for h in hrs], width=0.035, color="#1976d2", label="chuva (mm/h)")
    a2b = a2.twinx()
    a2b.plot(t, [h["rain_prob"] for h in hrs], color="#6a1b9a", lw=1.2, label="chance de chuva (%)")
    a2b.set_ylim(0, 100)
    a2b.set_ylabel("%")
    a2.set_ylabel("mm/h")
    a3.plot(t, [h["wind_kmh"] for h in hrs], color="#37474f", lw=1.6, label="vento (km/h)")
    c = R["pulverizacao"]
    a3.axhspan(c["vento_min"], c["vento_max"], color="#a5d6a7", alpha=0.5, label=f"vento bom p/ pulverizar ({c['vento_min']}-{c['vento_max']})")
    a3.set_ylabel("km/h")
    base = datetime.fromisoformat(data["gerado_em"]).date()
    for a in data["alertas"]:
        ev = a["evidencia"]
        if a["tipo"] in ("pulverizacao", "geada") and ev.get("inicio_h") is not None and ev.get("modo") != "evitar":
            d0 = datetime.combine(base + timedelta(days=ev.get("dia_offset", 0)), datetime.min.time())
            s, e = d0 + timedelta(hours=ev["inicio_h"]), d0 + timedelta(hours=ev["fim_h"] if ev["fim_h"] else 24)
            col = "#66bb6a" if a["tipo"] == "pulverizacao" else "#42a5f5"
            for ax in (a1, a2, a3):
                ax.axvspan(s, e, color=col, alpha=0.3)
            a1.text(s, a1.get_ylim()[1], "janela de pulverização" if a["tipo"] == "pulverizacao" else "geada", fontsize=7, va="top")
    for ax in (a1, a2, a3):
        ax.grid(alpha=0.3)
    a1.legend(fontsize=7, loc="upper right")
    a3.legend(fontsize=7, loc="upper right")
    a3.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %Hh"))
    a3.xaxis.set_major_locator(mdates.HourLocator(interval=12))
    fig.autofmt_xdate()
    fig.suptitle("Clima das próximas 72 horas e as janelas escolhidas", fontsize=11, weight="bold")
    fig.text(0.01, 0.005, FOOT, fontsize=5.5, color="#555")
    _save(fig, path)
    return True


def _factors_chart(data: dict, path: Path):
    crops = data["culturas"]
    if not crops:
        return False
    c = next((x for x in crops if x["informada"]), crops[0])
    rows = c["fatores"]
    fig, axes = plt.subplots(len(rows), 1, figsize=(8, 0.95 * len(rows) + 1.2))
    axes = np.atleast_1d(axes)
    for ax, r in zip(axes, rows):
        a, b, cc, d = (r["faixa"][k] for k in "abcd")
        span = d - a
        ax.barh([0], [d - a], left=a, color="#e0e0e0", height=0.5)
        ax.barh([0], [cc - b], left=b, color="#81c784", height=0.5)
        ax.set_xlim(a - span * 0.15, d + span * 0.15)
        ax.set_ylim(-0.7, 0.7)
        ax.set_yticks([])
        ax.tick_params(labelsize=7)
        for sp in ("top", "right", "left"):
            ax.spines[sp].set_visible(False)
        if r["valor"] is None:
            ax.text(0.5, 0.0, "sem dado", transform=ax.transAxes, ha="center", va="center", fontsize=8, color="#777")
            col = GREY
        else:
            col = GREEN if r["nota"] >= 0.8 else (AMBER if r["nota"] > 0 else RED)
            ax.plot([r["valor"]], [0], marker="v", color=col, ms=11, mec="black", zorder=5)
            ax.text(min(max(r["valor"], a - span * 0.1), d + span * 0.1), 0.55, f"{r['valor']:g} {r['unidade']}", ha="center",
                    fontsize=7.5, weight="bold")
        label = f"{r['nome']}" + (f"  → nota {r['nota']:.2f}" if r["nota"] is not None else "")
        ax.set_title(label, fontsize=8.5, loc="left", color=col if r["valor"] is not None else "#555")
    fig.suptitle(f"Por que a nota de {c['crop']} é {c['nota']}/100  (verde: faixa ideal · cinza: faixa tolerada)",
                 fontsize=10.5, weight="bold")
    fig.tight_layout(rect=(0, 0.02, 1, 0.95))
    fig.text(0.01, 0.003, FOOT, fontsize=5.5, color="#555")
    _save(fig, path)
    return True


def _model_diagram(data: dict, path: Path):
    """O caminho do dado até a conclusão, em 4 colunas."""
    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.axis("off")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 56)
    cols = [
        (2, "1. Dados coletados", "#e3f2fd", ["Sentinel-2 (imagem)", "Relevo (DEM 30 m)", "Solo (SoilGrids)", "Previsão 72 h", "Histórico 5 anos"]),
        (27, "2. Camadas calculadas", "#e8f5e9", ["NDVI (vigor)", "NDMI (umidade)", "Declividade e aspecto", "Posição no relevo (TPI)", "Máscara de nuvem"]),
        (52, "3. Relações entre camadas", "#fff8e1", ["Zonas de manejo", "Área fraca e onde fica", "Risco de erosão", "Baixada x geada", "Umidade x chuva prevista"]),
        (77, "4. Regras e conclusão", "#fce4ec", ["Nota por cultura (0-100)", "Fator que mais limita", "4 alertas com silêncio", "Confiança alta/média/baixa", "Mensagem curta + este relatório"]),
    ]
    for x, title, color, items in cols:
        ax.add_patch(FancyBboxPatch((x, 4), 21, 48, boxstyle="round,pad=0.4", fc=color, ec="#555", lw=1))
        ax.text(x + 10.5, 48.5, title, ha="center", va="center", fontsize=9, weight="bold")
        for i, it in enumerate(items):
            ax.text(x + 1.5, 40 - i * 7.2, "• " + it, fontsize=8, va="center")
    for x in (23.6, 48.6, 73.6):
        ax.annotate("", xy=(x + 3, 28), xytext=(x, 28), arrowprops=dict(arrowstyle="-|>", lw=2, color="#455a64"))
    if data.get("simulado"):
        ax.text(50, 1.2, "ATENÇÃO: parte dos dados deste relatório é SIMULADA (modo demonstração)", ha="center", fontsize=9,
                color=RED, weight="bold")
    else:
        ax.text(50, 1.2, "Cada seta é uma conta que você pode conferir nas tabelas do relatório. O modelo de linguagem só escreve a frase; quem decide são as regras.",
                ha="center", fontsize=7.5, color="#444")
    _save(fig, path)


def render_all(work_dir: Optional[Path], lat: float, lon: float, data: dict, out_dir: Path,
               rain_month_mm: Optional[float] = None, polygon: Optional[dict] = None) -> list[dict]:
    """Gera todos os PNGs que o dado permite e devolve a lista (arquivo, título, como ler, conclusão)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    caps = data.get("legendas", {})
    sim = data.get("simulado")
    fonte = "Dados SIMULADOS (demonstração)" if sim else "Sentinel-2 · Copernicus DEM · SoilGrids"
    out = []

    def add(name, title, how, concl):
        out.append({"arquivo": f"{name}.png", "titulo": title, "como_ler": how, "conclusao": concl})

    if caps and work_dir is not None:
        _, P = analyze_with_products(work_dir, lat, lon, rain_month_mm, polygon)
        if data["culturas"]:  # mapa-resumo de 6 painéis: é a imagem que vai junto da mensagem no WhatsApp
            from app.engine.mapa import render_map
            from app.models import Viability
            vs = [Viability(crop=c["crop"], score=c["nota"], factors={}, limiting_factor="", orientation="",
                            confidence=c["confianca"]) for c in data["culturas"]]
            render_map(work_dir, lat, lon, vs, out=out_dir / "mapa.png", products=P)
        if "ndvi" in caps:
            _raster_map(P, P.ndvi, caps["ndvi"][0], "RdYlGn", 0, 1, "NDVI (0 a 1)", out_dir / "ndvi.png", fonte)
            add("ndvi", *caps["ndvi"])
        if "ndmi" in caps and P.ndmi is not None:
            _raster_map(P, P.ndmi, caps["ndmi"][0], "BrBG", -0.1, 0.5, "NDMI", out_dir / "ndmi.png", fonte)
            add("ndmi", *caps["ndmi"])
        if "slope" in caps and P.slope is not None:
            _raster_map(P, np.clip(P.slope, 0, 30), caps["slope"][0], "YlOrBr", 0, 30, "declividade (%)", out_dir / "slope.png",
                        fonte, unit="%", nd=1, extra=_slope_arrows(P))
            add("slope", *caps["slope"])
        if "tpi" in caps and P.tpi is not None:
            _raster_map(P, P.tpi, caps["tpi"][0], "RdBu", -6, 6, "TPI (m): negativo = baixada", out_dir / "tpi.png", fonte, unit="m", nd=1)
            add("tpi", *caps["tpi"])
        if "zonas" in caps and P.zones is not None:
            from app.models import SpatialStats  # noqa: F401
            _zones_map(P, data["relacoes"]["zonas"], out_dir / "zonas.png", fonte)
            add("zonas", *caps["zonas"])
        if "anomalia" in caps and P.ref_mean is not None and P.ref_std:
            _anomaly_map(P, out_dir / "anomalia.png", fonte)
            add("anomalia", *caps["anomalia"])
        if "erosao" in caps and P.erosion is not None:
            _raster_map(P, P.erosion, caps["erosao"][0], "OrRd", 0, 1, "índice relativo (0 a 1)", out_dir / "erosao.png", fonte)
            add("erosao", *caps["erosao"])
    if _factors_chart(data, out_dir / "fatores.png"):
        add("fatores", "Por que esta nota", "Cada linha é um fator. A barra cinza é a faixa tolerada pela cultura, a verde é a faixa ideal e o triângulo é o valor da sua área. Quanto mais longe do verde, menor a nota do fator.",
            "A nota final é a média ponderada das notas dos fatores. Se algum fator zera, a nota máxima é 40.")
    if _weather_chart(data, out_dir / "clima.png"):
        add("clima", "Clima das próximas 72 horas", "As faixas coloridas mostram as janelas que o BALK escolheu. A linha azul tracejada é o limite de geada. A faixa verde no vento é o intervalo bom para pulverizar.",
            "As janelas só aparecem onde temperatura, vento, umidade e chuva ficam dentro dos limites ao mesmo tempo.")
    _model_diagram(data, out_dir / "modelo.png")
    add("modelo", "Como o BALK chegou a esta conclusão", "Leia da esquerda para a direita: dados, camadas, relações e regras.",
        "As regras são do arquivo rules.yaml e crops.yaml, com a fonte de cada número. O modelo de linguagem não decide nada.")
    return out
