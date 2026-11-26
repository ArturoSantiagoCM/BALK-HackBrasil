"""Monta os dados do relatório detalhado: o que foi coletado, a conta da nota e o porquê de cada alerta.

Tudo sai em dicts simples (JSON), guardados no banco; a página HTML e as imagens só leem isto.
Nada aqui decide coisa alguma: só mostra, com os números, o que as regras (rules.yaml, crops.yaml) já decidiram.
"""
from datetime import datetime
from typing import Optional

from app import config
from app.models import Alert, Producer, SpatialStats, Viability, Weather
from app.viability import FACTOR_LABEL, explain_crop, load_crops

DIR_NAME = {"N": "norte", "NE": "nordeste", "E": "leste", "SE": "sudeste", "S": "sul", "SO": "sudoeste", "O": "oeste",
            "NO": "noroeste", "C": "centro"}
STATUS_TXT = {"confirmado": "Conferido em fonte técnica", "ajustado": "Ajustado para bater com a fonte",
              "parcial": "Confirmado em parte", "premissa": "Premissa da equipe (sem fonte encontrada)"}


def relief_class(slope_pct: Optional[float]) -> Optional[str]:
    """Classes de relevo da Embrapa por declividade média (%)."""
    if slope_pct is None:
        return None
    for lim, name in ((3, "plano"), (8, "suave ondulado"), (20, "ondulado"), (45, "forte ondulado")):
        if slope_pct < lim:
            return name
    return "montanhoso"


def _num(v, nd=1, unit=""):
    return "sem dado" if v is None else f"{v:.{nd}f}{unit}"


def data_table(p: Producer, stats: Optional[SpatialStats], weather: Weather, climate: Optional[dict], meta: dict,
               now: datetime) -> list[dict]:
    """Uma linha por camada de dados: de onde veio, de quando é, que resolução tem e o que mostrou na sua área."""
    sim = meta.get("source") == "simulado"
    rows = []
    if stats is not None:
        age = None
        if stats.scene_date:
            age = (now.date() - datetime.fromisoformat(stats.scene_date).date()).days
        rows += [
            {"camada": "Satélite Sentinel-2 (vermelho, infravermelho, SWIR, borda do vermelho)",
             "fonte": "SIMULADO (demonstração)" if sim else "Copernicus Sentinel-2 L2A via AWS Earth Search",
             "data": stats.scene_date, "resolucao": "10 m (SWIR e borda do vermelho: 20 m)",
             "valor": f"NDVI médio {_num(stats.ndvi_mean, 2)}; umidade (NDMI) {_num(stats.ndmi_mean, 2)}",
             "nota": (f"Cena de {age} dias atrás. " if age is not None else "Sem data de cena. ")
                     + "Nuvem e sombra são descartadas pela classificação de cena (SCL)."},
            {"camada": "Relevo (modelo digital de elevação)",
             "fonte": "SIMULADO (demonstração)" if sim else "Copernicus DEM GLO-30",
             "data": None, "resolucao": "30 m, reamostrado para 10 m",
             "valor": f"declividade média {_num(stats.slope_mean_pct, 1, '%')} (máx {_num(stats.slope_max_pct, 1, '%')}); "
                      f"elevação {_num(stats.elevation_m, 0, ' m')}",
             "nota": "Relevo fino (menor que 30 m) não existe neste dado."},
            {"camada": "Solo (argila e pH, 0 a 5 cm)",
             "fonte": "SIMULADO (demonstração)" if sim else "SoilGrids (ISRIC), estimativa modelada",
             "data": None, "resolucao": "250 m",
             "valor": f"argila {_num(stats.clay_pct, 0, '%')}; pH {_num(stats.ph, 1)}",
             "nota": "É uma estimativa, não um laudo. Uma análise de solo da sua lavoura vale mais que este número."},
        ]
    hrs = weather.hours
    rows.append({
        "camada": "Previsão do tempo (próximas 72 horas)",
        "fonte": {"simulado": "SIMULADO (demonstração)", "cache": "Open-Meteo (cache)"}.get(weather.source, "Open-Meteo"),
        "data": hrs[0]["time"][:10] if hrs else None, "resolucao": "horária, grade de alguns km",
        "valor": (f"mínima {min(h['temp'] for h in hrs):.0f}°C, máxima {max(h['temp'] for h in hrs):.0f}°C, "
                  f"chuva total {sum(h['rain_mm'] for h in hrs):.0f} mm") if hrs else "sem dado",
        "nota": "A previsão erra mais quanto mais longe: por isso cada alerta traz um nível de confiança."})
    if climate:
        sim_c = climate.get("source") == "simulado"
        rows.append({
            "camada": "Histórico de clima (5 anos)",
            "fonte": "SIMULADO (demonstração)" if sim_c else "Open-Meteo Archive (ERA5)",
            "data": None, "resolucao": "diária, agregada por mês",
            "valor": f"temperatura média anual {_mean(climate, 'temp'):.1f}°C; chuva média {_mean(climate, 'rain'):.0f} mm/mês",
            "nota": "Usado para a nota de viabilidade: temperatura, chuva e dias de geada do ciclo."})
    return rows


def _mean(climate: dict, key: str) -> float:
    v = [m[key] for m in climate["monthly"].values()]
    return sum(v) / len(v) if v else 0.0


def crops_explained(stats: Optional[SpatialStats], climate: Optional[dict], ranking: list[Viability],
                    planting_month: Optional[int], crop_pref: Optional[str]) -> list[dict]:
    """Para cada cultura do ranking: a conta da nota, fator por fator, com a fonte de cada faixa."""
    if stats is None:
        return []
    cfg = config.crops_cfg()
    crops = load_crops()
    fontes, valid = cfg.get("fontes", {}), cfg.get("validacao", {})
    out = []
    for v in ranking:
        c = crops[v.crop]
        rows = explain_crop(stats, climate, c, planting_month if v.crop == crop_pref else None)
        for r in rows:
            val = valid.get(v.crop, {}).get(r["id"]) or valid.get("_comum", {}).get(r["id"]) or {"status": "premissa", "fonte": "EXTRA_PADRAO"}
            src = fontes.get(val["fonte"], {})
            r.update({"status": val["status"], "status_txt": STATUS_TXT[val["status"]],
                      "fonte_titulo": src.get("titulo", ""), "fonte_url": src.get("url", ""),
                      "faltou": r["valor"] is None})
        cap = any(r["nota"] == 0.0 for r in rows if r["nota"] is not None)
        out.append({"crop": v.crop, "nota": v.score, "confianca": v.confidence, "limitante": v.limiting_factor,
                    "limitante_nome": FACTOR_LABEL.get(v.limiting_factor, (v.limiting_factor, ""))[0],
                    "orientacao": v.orientation, "teto_40": cap, "ciclo_meses": c["ciclo_meses"],
                    "fatores": rows, "informada": v.crop == crop_pref})
    return out


def _row(criterio, limite, observado, atende):
    return {"criterio": criterio, "limite": limite, "observado": observado, "atende": atende}


def alert_explained(a: Alert, p: Producer, now: datetime) -> dict:
    """Os critérios da regra, o valor observado e se cada um foi atendido, mais o status da regra (fonte)."""
    R = config.rules()
    ev = a.evidence
    rows = []
    if a.type == "pulverizacao":
        c = R["pulverizacao"]
        if ev.get("modo") == "evitar":
            rows = [_row("Temperatura", f"{c['temp_min']} a {c['temp_max']} °C", f"até {ev['temp_max']} °C (24 h)", ev["temp_max"] <= c["temp_max"]),
                    _row("Vento", f"{c['vento_min']} a {c['vento_max']} km/h", f"até {ev['vento_max']} km/h (24 h)", ev["vento_max"] <= c["vento_max"]),
                    _row("Chance de chuva", f"até {c['chuva_prob_max']}%", f"até {ev['chuva_prob_max']}% (24 h)", ev["chuva_prob_max"] <= c["chuva_prob_max"])]
        else:
            rows = [_row("Temperatura", f"{c['temp_min']} a {c['temp_max']} °C", f"{ev['temp']} °C", True),
                    _row("Vento", f"{c['vento_min']} a {c['vento_max']} km/h", f"{ev['vento_kmh']} km/h", True),
                    _row("Umidade relativa", f"acima de {c['rh_min']}%", f"{ev['rh']}%", True),
                    _row("Chance de chuva", f"até {c['chuva_prob_max']}%", f"{ev['chuva_prob']}%", True),
                    _row("Delta T (evaporação da gota)", f"{c['delta_t_min']} a {c['delta_t_max']}", f"{ev['delta_t']}", True)]
        key = "pulverizacao"
    elif a.type == "geada":
        c = R["geada"]
        prev = ev.get("tmin_previsto", ev["tmin"])
        rows = [_row("Mínima prevista no ponto (2 m)", f"{c['tmin']} °C ou menos", f"{prev} °C", prev <= c["tmin"])]
        if ev.get("modo") == "relevo":
            rows += [_row("Ajuste pelo relevo (baixada)", f"até -{c['ajuste_relevo_c']} °C", f"{round(ev['tmin'] - prev, 1)} °C", True),
                     _row("Mínima estimada no ponto mais baixo", f"{c['tmin']} °C ou menos", f"{ev['tmin']} °C", ev["tmin"] <= c["tmin"])]
        key = "geada"
    elif a.type == "estresse":
        c = R["estresse"]
        if ev.get("z") is not None:
            rows.append(_row("Desvio do NDVI contra a referência (z)", f"menor que {c['z_max']}", f"{ev['z']}", ev["z"] < c["z_max"]))
        if ev.get("pct") is not None:
            rows.append(_row("Parte da área bem abaixo da referência", f"{c['area_fraca_alerta_pct']}% ou mais", f"{ev['pct']}%", ev["pct"] >= c["area_fraca_alerta_pct"]))
        ref_txt = {"historico": "safras anteriores do mesmo talhão", "serie_recente": "série recente desta safra (confiança baixa)"}.get(
            ev.get("referencia"), "vizinhança da cena (confiança baixa)")
        rows.append(_row("Referência usada", "safras anteriores, se houver", ref_txt, ev.get("referencia") == "historico"))
        key = "estresse"
    else:  # colheita
        c = R["colheita"]
        crop = load_crops().get(p.crop or "", {})
        days = (now.date() - datetime.fromisoformat(p.planting_date).date()).days if p.planting_date else None
        if days is not None and crop:
            need = crop["ciclo_dias"] - c["margem_dias_ciclo"]
            rows.append(_row("Lavoura pronta (dias desde o plantio)", f"{need} ou mais", f"{days}", days >= need))
        if ev.get("modo") == "janela":
            rows.append(_row(f"Chuva em {ev['horas']} h seguidas", f"até {c['chuva_mm_max']} mm", f"{ev['chuva_mm']} mm", True))
        else:
            rows.append(_row(f"Alguma janela de {ev['horas']} h com até {c['chuva_mm_max']} mm", "pelo menos uma", "nenhuma nas próximas 72 h", False))
        key = "colheita"
    rule = R.get("validacao_regras", {}).get(key, {})
    return {"tipo": a.type, "acao": a.action, "janela": a.window, "confianca": a.confidence, "por_que": a.why,
            "criterios": rows, "regra_status": rule.get("status", "premissa"),
            "regra_status_txt": STATUS_TXT.get(rule.get("status", "premissa"), ""), "regra_resumo": rule.get("resumo", ""),
            "regra_fontes": rule.get("fontes", []), "evidencia": ev}


def image_captions(stats: Optional[SpatialStats]) -> dict:
    """Título, como ler e a conclusão de cada imagem (com os números da área). Só entram as imagens com dado."""
    s = stats
    caps = {}
    if s is None:
        return caps
    weak = ""
    if s.weak_area_pct is not None and s.weak_area_dir:
        where = "espalhada em volta do centro" if s.weak_area_dir == "C" else f"no lado {DIR_NAME[s.weak_area_dir]}"
        weak = f" {s.weak_area_pct:.0f}% da área está bem abaixo da referência da cena, {where}."
    caps["ndvi"] = ("Vigor da vegetação (NDVI)",
                    "Verde escuro: vegetação vigorosa. Amarelo e vermelho: vegetação fraca ou solo exposto. Branco: nuvem ou sombra, descartadas. O contorno tracejado é a área analisada (o seu talhão, se você o desenhou; senão um círculo de cerca de 7 ha).",
                    f"NDVI médio de {_num(s.ndvi_mean, 2)} e irregularidade (desvio) de {_num(s.ndvi_std, 2)}." + weak)
    if s.ndmi_mean is not None:
        caps["ndmi"] = ("Umidade da vegetação (NDMI)",
                        "Azul e verde-azulado: a vegetação tem mais água. Marrom: mais seca. Muda com a cultura e a fase, então vale comparar com o histórico da própria lavoura.",
                        f"NDMI médio de {_num(s.ndmi_mean, 2)}: umidade da vegetação {s.moisture_class or 'sem classe'} (cortes em rules.yaml, premissa da equipe).")
    if s.slope_mean_pct is not None:
        asp = f", com a encosta voltada para {DIR_NAME.get(s.aspect_label, s.aspect_label)}" if s.aspect_label else ""
        caps["slope"] = ("Declividade e direção da encosta",
                         "As cores mostram o declive em %. As setas mostram para onde a água escorre. Quanto mais escuro, mais inclinado.",
                         f"Declividade média de {s.slope_mean_pct:.1f}% (máxima {_num(s.slope_max_pct, 1, '%')}){asp}. Pela classificação da Embrapa o relevo é {relief_class(s.slope_mean_pct)}.")
    if s.tpi_min is not None:
        off = s.frost_relief_offset_c
        caps["tpi"] = ("Posição no relevo: baixadas e topos",
                       "Azul: baixada, onde o ar frio e a água se acumulam. Vermelho: topo. As bordas da imagem ficam em branco porque o cálculo precisa de vizinhança.",
                       f"A baixada mais funda da área está {abs(s.tpi_min):.1f} m abaixo da vizinhança. "
                       + (f"Isso pode deixar o ponto mais baixo até {abs(off):.1f} °C mais frio que a previsão do ponto (hipótese em validação)." if off else "Sem efeito relevante na geada."))
    if s.zones:
        z = s.zones
        caps["zonas"] = ("Zonas de manejo",
                         "Cada cor é uma parte da área com comportamento parecido (vigor, declive, posição no relevo e umidade). Vermelho é a zona mais fraca. Serve para saber onde olhar primeiro.",
                         " ".join(f"Zona {x['id']} ({x['label']}): {x['share_pct']:.0f}% da área, NDVI {x['ndvi_mean']:.2f}." for x in z))
    if s.weak_area_pct is not None:
        caps["anomalia"] = ("Onde a lavoura está mais fraca que o resto",
                            "Cada pixel mostra quantos desvios ele está do NDVI médio da cena. Vermelho: bem abaixo. O contorno preto marca o que contamos como área fraca (mais de 1 desvio abaixo).",
                            f"{s.weak_area_pct:.0f}% da área está abaixo do limite." + (f" Concentrada no lado {DIR_NAME.get(s.weak_area_dir, '')}." if s.weak_area_dir and s.weak_area_dir != "C" else ""))
    if s.erosion_index is not None:
        caps["erosao"] = ("Risco relativo de erosão",
                          "Combina declividade, chuva, cobertura da vegetação e tipo de solo. É um índice relativo de 0 a 1, não é perda de solo em toneladas por hectare.",
                          f"Índice médio de {s.erosion_index:.2f}: risco {s.erosion_class}. Em terreno plano o índice é perto de zero mesmo com solo exposto.")
    return caps


LIMITES = [
    "Esta é uma estimativa orientativa a partir de dados de satélite e clima. Não substitui um engenheiro agrônomo e não receita produto nem dose.",
    "A resolução do satélite é de 10 m: lavouras pequenas misturam áreas vizinhas, e a área analisada (círculo de cerca de 7 ha) pode ser maior que a sua.",
    "O satélite não é em tempo real: passa a cada poucos dias e nuvem esconde a lavoura. A data da cena está na tabela de dados.",
    "Argila e pH vêm de um mapa de 250 m (estimativa). Uma análise de solo da sua lavoura é melhor.",
    "As regras partem de referências públicas (Embrapa, MAPA, FAO) e estão em revisão por agrônomos. Onde a tabela diz 'premissa da equipe', não encontramos fonte.",
    "A previsão do tempo erra mais quanto mais distante. Cada alerta traz um nível de confiança.",
]


def build(p: Producer, now: datetime, weather: Weather, stats: Optional[SpatialStats], ranking: list[Viability],
          climate: Optional[dict], alerts: list[Alert], relations_: Optional[dict], messages: list[dict],
          meta: dict) -> dict:
    """Pacote completo do relatório (JSON). A página lê só isto."""
    planting_month = int(p.planting_date[5:7]) if p.planting_date else None
    sim = (meta.get("source") == "simulado" or weather.source == "simulado" or (climate or {}).get("source") == "simulado")
    return {
        "versao": 1, "gerado_em": now.isoformat(timespec="seconds"), "lang": "pt",
        "simulado": sim,
        "produtor": {"cultura": p.crop, "plantio": p.planting_date, "canal": p.channel,
                     "lat": round(p.lat, 2), "lon": round(p.lon, 2),  # ~1 km: o link não revela a lavoura exata
                     "precisao": p.location_precision},
        "mensagens": [{"tipo": m.get("type"), "texto": m["text"]} for m in messages],
        "dados": data_table(p, stats, weather, climate, meta, now),
        "culturas": crops_explained(stats, climate, ranking, planting_month, p.crop),
        "relacoes": _relations(stats, relations_),
        "alertas": [alert_explained(a, p, now) for a in alerts],
        "clima": {"fonte": weather.source,
                  "horas": [{k: h[k] for k in ("time", "temp", "rh", "rain_prob", "rain_mm", "wind_kmh")} for h in weather.hours]},
        "legendas": image_captions(stats),
        "imagens": [],  # preenchido por images.render_all
        "limites": LIMITES,
        "atribuicoes": config.rules().get("atribuicoes", []),
        "area_ha": stats.area_ha if stats else None,
    }


def _relations(stats: Optional[SpatialStats], rel: Optional[dict]) -> dict:
    if stats is None:
        return {}
    return {"zonas": stats.zones or [], "area_fraca_pct": stats.weak_area_pct, "area_fraca_dir": stats.weak_area_dir,
            "erosao": {"indice": stats.erosion_index, "classe": stats.erosion_class},
            "umidade": {"ndmi": stats.ndmi_mean, "classe": stats.moisture_class,
                        "saldo_mm": (rel or {}).get("saldo_mm"), "atencao": (rel or {}).get("atencao_agua")},
            "geada_relevo_c": stats.frost_relief_offset_c, "relevo": relief_class(stats.slope_mean_pct),
            "aspecto": stats.aspect_label}
