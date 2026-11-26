"""Relatório detalhado: página web (e arquivo para baixar) com os dados, os mapas e o porquê das conclusões.

Fluxo: service.analyze_producer -> explain.build (dados) -> db.create_report (token) -> link na mensagem.
As imagens são geradas de uma vez (primeiro relatório) ou na primeira visita (alertas) e ficam em work/{id}/report/{token}/.
"""
from pathlib import Path
from typing import Optional

from app import config
from app.report.explain import build  # noqa: F401
from app.report.images import render_all
from app.report.page import render_history, render_page  # noqa: F401


def report_dir(producer_id: int, token: str) -> Path:
    return config.work_root() / str(producer_id) / "report" / token


def ensure_images(data: dict) -> Path:
    """Garante os PNGs do relatório no disco (gera se faltar) e devolve a pasta."""
    pid, token = data["_producer_id"], data["_token"]
    out = report_dir(pid, token)
    if (out / "modelo.png").exists():
        return out
    from app import db
    p = db.get_producer(pid)
    work = config.work_root() / str(data.get("work_key") or pid)
    has_layers = bool(data.get("legendas")) and (work / "red.tif").exists()
    rain = data.get("chuva_mes_mm")
    data["imagens"] = render_all(work if has_layers else None, p.lat if p else 0.0, p.lon if p else 0.0, data, out, rain,
                                 data.get("poligono"))
    (out / "imagens.json").write_text(__import__("json").dumps(data["imagens"], ensure_ascii=False), encoding="utf-8")
    return out


def load_images_meta(out: Path) -> list:
    f = out / "imagens.json"
    return __import__("json").loads(f.read_text(encoding="utf-8")) if f.exists() else []


def prerender(producer_id: int, token: str, data: dict, lat: float, lon: float, rain_month_mm: Optional[float]) -> None:
    """Gera as imagens já (usado no primeiro relatório, para o link abrir na hora)."""
    out = report_dir(producer_id, token)
    work = config.work_root() / str(data.get("work_key") or producer_id)
    imgs = render_all(work if data.get("legendas") else None, lat, lon, data, out, rain_month_mm, data.get("poligono"))
    (out / "imagens.json").write_text(__import__("json").dumps(imgs, ensure_ascii=False), encoding="utf-8")
