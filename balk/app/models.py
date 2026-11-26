"""Contratos compartilhados do BALK. SAGRADO: só muda com os 4 de acordo.

Acréscimos em relação ao guia (todos opcionais, não quebram ninguém):
- Producer.location_precision, Producer.state, Producer.active
- SpatialStats.ndvi_ref_mean / ndvi_ref_std (vizinhança, usada pelo alerta de estresse)
"""
from typing import Literal, Optional

from pydantic import BaseModel


class Producer(BaseModel):
    id: int = 0
    phone: str
    channel: Literal["whatsapp", "sms"] = "whatsapp"
    lat: float = 0.0
    lon: float = 0.0
    crop: Optional[str] = None  # vazio: o sistema sugere
    planting_date: Optional[str] = None  # "AAAA-MM-DD"
    consent: bool = False
    lang: Literal["pt", "es", "en"] = "pt"
    source: str = "direto"  # "cooperativa_x", "csv", "plataforma_y"
    location_precision: Literal["ponto", "municipio"] = "ponto"
    state: str = "INICIO"
    active: bool = True


class Weather(BaseModel):  # saída do M2 (clima)
    hours: list[dict]  # time, temp, rh, rain_prob, rain_mm, wind_kmh, et0
    source: str = "simulado"  # simulado | open-meteo | cache


class SpatialStats(BaseModel):  # saída do M3
    ndvi_mean: Optional[float] = None
    ndvi_std: Optional[float] = None
    slope_mean_pct: Optional[float] = None
    slope_max_pct: Optional[float] = None
    clay_pct: Optional[float] = None
    elevation_m: Optional[float] = None
    area_ha: float = 0.0
    scene_date: Optional[str] = None
    engine: Literal["qgis", "python", "simulado"] = "python"
    ndvi_ref_mean: Optional[float] = None
    ndvi_ref_std: Optional[float] = None


class Viability(BaseModel):  # saída do M4
    crop: str
    score: int  # 0 a 100
    factors: dict  # fator -> nota 0..1
    limiting_factor: str
    orientation: str
    confidence: Literal["baixa", "media", "alta"]


class Alert(BaseModel):  # saída do M5, entrada do M6
    type: Literal["pulverizacao", "geada", "estresse", "colheita"]
    action: str
    window: Optional[str] = None
    evidence: dict  # números usados
    confidence: Literal["baixa", "media", "alta"]
    why: str
