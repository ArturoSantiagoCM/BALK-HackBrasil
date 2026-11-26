"""M4: nota de viabilidade (0-100), ranking de 3 culturas e orientação. Explicável, sem produto e dose."""
from datetime import datetime
from typing import Optional

from app import config
from app.data.climate import season_stats
from app.models import SpatialStats, Viability

DISCLAIMER = {
    "pt": "Estimativa orientativa a partir de dados de satélite e clima. Não substitui um engenheiro agrônomo.",
    "es": "Estimación orientativa a partir de datos de satélite y clima. No sustituye a un ingeniero agrónomo.",
    "en": "Indicative estimate from satellite and climate data. It does not replace an agronomist.",
}
FACTORS = ["temp_media_c", "chuva_mm", "declive_pct", "argila_pct", "ndvi_regular"]


def fit(x, a, b, c, d) -> float:
    """Função trapezoidal: a=mín abs, b=ótimo mín, c=ótimo máx, d=máx abs."""
    if x is None or x <= a or x >= d:
        return 0.0
    if b <= x <= c:
        return 1.0
    return (x - a) / (b - a) if x < b else (d - x) / (d - c)


def validate_crops(raw: dict) -> None:
    """Falha com mensagem clara se alguma faixa não estiver em ordem a <= b <= c <= d."""
    def check(where, r):
        for k in "abcd":
            if k not in r:
                raise ValueError(f"crops.yaml: {where} sem o número '{k}'")
        if not (r["a"] <= r["b"] <= r["c"] <= r["d"]):
            raise ValueError(f"crops.yaml: {where} fora de ordem (precisa a<=b<=c<=d): {r}")
    check("padrao.ndvi_std", raw["padrao"]["ndvi_std"])
    for name, c in raw["culturas"].items():
        for f in ("temp_media_c", "chuva_mm", "declive_pct", "argila_pct"):
            if f not in c["fatores"]:
                raise ValueError(f"crops.yaml: cultura '{name}' sem o fator '{f}'")
            check(f"{name}.{f}", c["fatores"][f])


def load_crops() -> dict:
    """crops.yaml validado, com os padrões (pesos, orientação, ndvi) já mesclados em cada cultura."""
    raw = config.crops_cfg()
    validate_crops(raw)
    pad = raw["padrao"]
    out = {}
    for name, c in raw["culturas"].items():
        fat = dict(c["fatores"])
        fat.setdefault("ndvi_regular", pad["ndvi_std"])
        out[name] = {**c, "nome": name, "fatores": fat, "pesos": c.get("pesos", pad["pesos"]),
                     "orientacao_por_fator": {**pad["orientacao_por_fator"], **c.get("orientacao_por_fator", {})},
                     "orientacao_sem_limite": pad["orientacao_sem_limite"]}
    return out


def _scene_confidence(scene_date: Optional[str], today: datetime) -> str:
    if not scene_date:
        return "baixa"
    age = (today - datetime.fromisoformat(scene_date)).days
    return "alta" if age < 10 else ("media" if age <= 30 else "baixa")


def _down(level: str) -> str:
    return {"alta": "media", "media": "baixa", "baixa": "baixa"}[level]


def score_crop(stats: SpatialStats, climate: Optional[dict], crop_cfg: dict, planting_month: Optional[int] = None,
               today: Optional[datetime] = None) -> Viability:
    today = today or datetime.now()
    temp = chuva = None
    if climate:
        start = planting_month or crop_cfg["mes_plantio_usual"]
        temp, chuva = season_stats(climate, start, crop_cfg["ciclo_meses"])
    values = {"temp_media_c": temp, "chuva_mm": chuva, "declive_pct": stats.slope_mean_pct,
              "argila_pct": stats.clay_pct, "ndvi_regular": stats.ndvi_std}
    factors, missing = {}, []
    for f in FACTORS:
        if values[f] is None:
            missing.append(f)  # dado ausente: sai da conta e a confiança cai (não vira nota zero)
            continue
        r = crop_cfg["fatores"][f]
        factors[f] = round(fit(values[f], r["a"], r["b"], r["c"], r["d"]), 3)
    if factors:
        w = {f: crop_cfg["pesos"][f] for f in factors}
        score = round(100 * sum(w[f] * factors[f] for f in factors) / sum(w.values()))
        if any(v == 0.0 for v in factors.values()):
            score = min(score, 40)
        limiting = min(factors, key=lambda f: factors[f])
        if factors[limiting] >= 0.8:
            orientation = crop_cfg["orientacao_sem_limite"]
        else:
            orientation = crop_cfg["orientacao_por_fator"][limiting]
    else:
        score, limiting, orientation = 0, "dados", "Sem dados suficientes para avaliar esta cultura."
    conf = _scene_confidence(stats.scene_date, today)
    if "argila_pct" in missing:
        conf = _down(conf)
    if any(m in missing for m in ("temp_media_c", "chuva_mm", "declive_pct")):
        conf = _down(conf)
    return Viability(crop=crop_cfg["nome"], score=int(score), factors=factors, limiting_factor=limiting,
                     orientation=orientation, confidence=conf)


def rank_crops(stats: SpatialStats, climate: Optional[dict], crop_pref: Optional[str] = None,
               planting_month: Optional[int] = None, today: Optional[datetime] = None,
               n: int = 3) -> list[Viability]:
    """3 melhores culturas. Se o produtor informou a cultura, ela vem primeiro com a sua nota."""
    crops = load_crops()
    scored = {name: score_crop(stats, climate, cfg, planting_month if name == crop_pref else None, today)
              for name, cfg in crops.items()}
    ordered = sorted(scored.values(), key=lambda v: -v.score)
    if crop_pref in scored:
        rest = [v for v in ordered if v.crop != crop_pref]
        return ([scored[crop_pref]] + rest)[:n]
    return ordered[:n]
