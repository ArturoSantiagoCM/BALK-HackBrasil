"""Talhões desenhados no mapa: validação de geometria (no backend, nunca confiando só no cliente) e área geodésica.

Regras (limites em rules.yaml, bloco `talhoes`): polígono válido e FECHADO, sem autointerseção, coordenadas dentro do Brasil,
área mínima e máxima, sem sobreposição relevante com outros talhões do mesmo produtor e limites de quantidade e de área total.
GeoJSON em EPSG:4326 (longitude, latitude).
"""
import hashlib
import json
import math
from typing import Optional

from pyproj import Geod
from shapely.geometry import Polygon, shape
from shapely.validation import explain_validity

from app import config

BRASIL_BBOX = (-74.0, -33.8, -34.7, 5.3)  # lon_min, lat_min, lon_max, lat_max (caixa aproximada do país)
_GEOD = Geod(ellps="WGS84")


def limits() -> dict:
    return {"area_min_ha": 0.05, "area_max_ha": 1000.0, "max_por_produtor": 20, "area_total_max_ha": 5000.0,
            "sobreposicao_max_pct": 5.0, "max_vertices": 500, **(config.rules().get("talhoes") or {})}


def geodesic_area_ha(poly: Polygon) -> float:
    """Área sobre o elipsoide WGS84 (não depende de projeção), em hectares."""
    area, _ = _GEOD.geometry_area_perimeter(poly)
    return abs(area) / 10_000.0


def _geometry(obj: dict) -> dict:
    return obj.get("geometry") if obj.get("type") == "Feature" else obj


def polygon_hash(geojson: dict) -> str:
    return hashlib.sha1(json.dumps(geojson, sort_keys=True).encode()).hexdigest()[:12]


def check_plot_input(geometry: dict, name: str, crop: Optional[str], planting_date: Optional[str],
                     others: Optional[list[dict]] = None, require_name: bool = True) -> dict:
    """Validação ÚNICA de um talhão enviado por qualquer porta (API interna e site): geometria, nome, cultura e data.
    Devolve {poly, geometry, area_ha, crop, planting_date, name, errors}; sem erros = pode gravar."""
    from app.ingest.conversation import match_crop, parse_date
    poly, errors, area = validate_polygon(geometry, others)
    clean_crop = None
    if crop:
        clean_crop = match_crop(crop)
        if clean_crop is None:
            errors.append(f"cultura desconhecida: {crop}")
    planting = None
    if planting_date:
        try:
            planting = parse_date(planting_date)
        except ValueError as e:
            errors.append(f"data de plantio inválida ({e})")
    if require_name and not (name or "").strip():
        errors.append("o talhão precisa de um nome")
    # o que se grava é a geometria JÁ VALIDADA e reescrita só com números (nada de chaves extras nem coordenadas em texto)
    clean = {"type": "Polygon", "coordinates": [[[x, y] for x, y in poly.exterior.coords]]} if poly is not None else {}
    return {"poly": poly, "geometry": clean, "area_ha": area, "crop": clean_crop, "planting_date": planting,
            "name": (name or "").strip()[:60], "errors": errors if poly is not None or errors else ["geometria inválida"]}


def validate_polygon(geojson: dict, others: Optional[list[dict]] = None, lim: Optional[dict] = None) -> tuple[Optional[Polygon], list[str], float]:
    """Devolve (polígono, erros, área em ha). Sem erros = polígono aceito. `others` = GeoJSONs dos outros talhões do produtor."""
    lim, errors = lim or limits(), []
    g = _geometry(geojson or {})
    if not isinstance(g, dict) or g.get("type") != "Polygon":
        return None, ["a geometria precisa ser um Polygon do GeoJSON"], 0.0
    try:
        ring = g["coordinates"][0]
        if len(g["coordinates"]) > 1:
            errors.append("polígono com buraco não é aceito: desenhe talhões separados")
        pts = [(float(x), float(y)) for x, y in ring]
    except (KeyError, IndexError, TypeError, ValueError):
        return None, ["coordenadas inválidas"], 0.0
    if any(not (math.isfinite(x) and math.isfinite(y)) for x, y in pts):
        return None, ["coordenadas inválidas (não numéricas)"], 0.0
    if len(pts) < 4:
        return None, ["um polígono precisa de pelo menos 3 vértices"], 0.0
    if len(pts) > lim["max_vertices"] + 1:  # antes de qualquer conta geométrica (contra polígonos gigantes)
        return None, [f"polígono com vértices demais (máximo de {lim['max_vertices']}): simplifique o desenho"], 0.0
    if pts[0] != pts[-1]:
        return None, ["polígono não fechado: o primeiro e o último ponto precisam ser iguais"], 0.0
    poly = Polygon(pts)
    if not poly.is_valid:
        errors.append(f"polígono inválido ({explain_validity(poly)}): cruzamento de linhas ou vértices repetidos")
        return None, errors, 0.0
    x0, y0, x1, y1 = BRASIL_BBOX
    minx, miny, maxx, maxy = poly.bounds
    if minx < x0 or maxx > x1 or miny < y0 or maxy > y1:
        errors.append("coordenadas fora do Brasil")
    area = geodesic_area_ha(poly)
    if area < lim["area_min_ha"]:
        errors.append(f"área de {area:.3f} ha abaixo do mínimo de {lim['area_min_ha']:g} ha")
    if area > lim["area_max_ha"]:
        errors.append(f"área de {area:.1f} ha acima do máximo de {lim['area_max_ha']:g} ha")
    prior = [shape(_geometry(o)) for o in (others or [])]
    if len(prior) + 1 > lim["max_por_produtor"]:
        errors.append(f"limite de {lim['max_por_produtor']} talhões por produtor")
    if sum(geodesic_area_ha(q) for q in prior) + area > lim["area_total_max_ha"]:
        errors.append(f"área total acima de {lim['area_total_max_ha']:g} ha")
    for q in prior:
        inter = poly.intersection(q).area
        if inter > 0 and 100.0 * inter / min(poly.area, q.area) > lim["sobreposicao_max_pct"]:
            errors.append("o talhão se sobrepõe a outro talhão do mesmo produtor")
            break
    return (poly if not errors else None), errors, round(area, 4)
