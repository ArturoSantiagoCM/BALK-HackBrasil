"""M6: modelos fixos (texto de reserva). render(alert_or_report, channel, lang) preenche os números."""
import unicodedata
from dataclasses import dataclass
from typing import Optional, Union

from app.models import Alert, SpatialStats, Viability
from app.viability import DISCLAIMER

SMS_SUFFIX = " Resp 1=ok 2=ajuda"

WEEKDAYS = {
    "pt": ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"],
    "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
}
TODAY_TOMORROW = {"pt": ("hoje", "amanhã"), "es": ("hoy", "mañana"), "en": ("today", "tomorrow")}
CONF = {"pt": {"alta": "alta", "media": "média", "baixa": "baixa (vale conferir)"},
        "es": {"alta": "alta", "media": "media", "baixa": "baja (conviene verificar)"},
        "en": {"alta": "high", "media": "medium", "baixa": "low (worth checking)"}}
LBL = {"pt": ("Por quê", "Confiança"), "es": ("Por qué", "Confianza"), "en": ("Why", "Confidence")}
CROPS = {"pt": {"soja": "soja", "milho": "milho", "cafe": "café", "feijao": "feijão", "hortalica": "hortaliça"},
         "es": {"soja": "soja", "milho": "maíz", "cafe": "café", "feijao": "frijol", "hortalica": "hortaliza"},
         "en": {"soja": "soybean", "milho": "corn", "cafe": "coffee", "feijao": "beans", "hortalica": "vegetables"}}
FACTOR = {"pt": {"temp_media_c": "temperatura", "chuva_mm": "chuva", "declive_pct": "declividade",
                 "argila_pct": "argila", "ndvi_regular": "vigor da lavoura", "dados": "dados"},
          "es": {"temp_media_c": "temperatura", "chuva_mm": "lluvia", "declive_pct": "pendiente",
                 "argila_pct": "arcilla", "ndvi_regular": "vigor del cultivo", "dados": "datos"},
          "en": {"temp_media_c": "temperature", "chuva_mm": "rainfall", "declive_pct": "slope",
                 "argila_pct": "clay", "ndvi_regular": "crop vigor", "dados": "data"}}
ORIENT = {  # orientação traduzida (o português vem do crops.yaml)
    "es": {"temp_media_c": "La temperatura de la época queda fuera del rango ideal. Evalúe otra época o cultivo.",
           "chuva_mm": "La lluvia histórica queda fuera de lo ideal. Evalúe riego, drenaje u otro cultivo.",
           "declive_pct": "El terreno es inclinado para este cultivo. Evalúe curvas de nivel u otro cultivo.",
           "argila_pct": "La textura estimada del suelo no es la ideal. Conviene un análisis de suelo.",
           "ndvi_regular": "El cultivo está irregular en el área. Conviene recorrer el lote.",
           "_ok": "Sin factor crítico en los datos disponibles. Siga monitoreando."},
    "en": {"temp_media_c": "Seasonal temperature is outside the ideal range. Consider another season or crop.",
           "chuva_mm": "Historical rainfall is outside the ideal. Consider irrigation, drainage or another crop.",
           "declive_pct": "The land is steep for this crop. Consider contour lines or another crop.",
           "argila_pct": "Estimated soil texture is not ideal. A soil test is worth doing.",
           "ndvi_regular": "The crop looks uneven in the area. Worth walking the field.",
           "_ok": "No critical factor in the available data. Keep monitoring."}}
SHORT = {"pt": {"temp_media_c": "Reveja a epoca de plantio.", "chuva_mm": "Avalie irrigacao ou drenagem.",
                "declive_pct": "Avalie curvas de nivel.", "argila_pct": "Confira com analise de solo.",
                "ndvi_regular": "De uma volta no talhao.", "_ok": "Sem ponto critico."},
         "es": {"temp_media_c": "Revise la epoca de siembra.", "chuva_mm": "Evalue riego o drenaje.",
                "declive_pct": "Evalue curvas de nivel.", "argila_pct": "Haga un analisis de suelo.",
                "ndvi_regular": "Recorra el lote.", "_ok": "Sin punto critico."},
         "en": {"temp_media_c": "Review planting season.", "chuva_mm": "Consider irrigation/drainage.",
                "declive_pct": "Consider contour lines.", "argila_pct": "Do a soil test.",
                "ndvi_regular": "Walk the field.", "_ok": "No critical issue."}}

# (linha 1: ação, linha 2: motivo com o dado, por quê, SMS)
T = {
 "pt": {
  ("pulverizacao", "agora"): ("Pulverize {dia}, das {ini}h às {fim}h.", "Vento de {vento_kmh} km/h, {temp}°C e chance de chuva de {chuva_prob}%.",
                              "temperatura, vento e umidade dentro dos limites nesta janela", "BALK: pulverizar {dia} {ini}h-{fim}h. Vento {vento_kmh}km/h, chuva {chuva_prob}%."),
  ("pulverizacao", "adiar"): ("Adie a pulverização para {dia}, das {ini}h às {fim}h.", "Antes disso vento ou chuva atrapalham; nessa janela o vento fica em {vento_kmh} km/h e a chuva em {chuva_prob}%.",
                              "só nessa janela temperatura, vento e umidade ficam nos limites", "BALK: adie a pulverizacao para {dia} {ini}h-{fim}h. Vento {vento_kmh}km/h."),
  ("pulverizacao", "evitar"): ("Evite pulverizar nas próximas 72 horas.", "Vento até {vento_max} km/h e chance de chuva até {chuva_prob_max}% nas próximas 24 horas.",
                               "a chuva lava o produto e o vento espalha a calda", "BALK: evite pulverizar nas proximas 72h. Vento ate {vento_max}km/h, chuva {chuva_prob_max}%."),
  ("geada", None): ("Geada {dia}, das {ini}h às {fim}h. Proteja a lavoura sensível.", "Mínima prevista de {tmin}°C.",
                    "a temperatura fica abaixo de {limite}°C", "BALK: GEADA {dia} {ini}h-{fim}h, min {tmin}C. Proteja culturas sensiveis."),
  ("estresse", None): ("Vale conferir a lavoura nesta semana.", "A vegetação da área está bem mais fraca do que o esperado para a época.",
                       "a vegetação vista pelo satélite está bem mais fraca que a referência", "BALK: vale conferir a lavoura. A vegetacao esta mais fraca que o esperado."),
  ("colheita", "janela"): ("Janela de colheita: {horas} horas secas a partir de {dia}, {ini}h.", "Chuva esperada de {chuva_mm} mm no período.",
                           "pouca chuva permite colher sem perda", "BALK: colheita {dia} {ini}h, {horas}h secas. Chuva {chuva_mm}mm."),
  ("colheita", "sem_janela"): ("Sem {horas} horas secas nos próximos 3 dias. Adie a colheita.", "A chuva prevista passa do limite em todas as janelas.",
                               "colher molhado aumenta a perda", "BALK: sem {horas}h secas nos proximos 3 dias. Adie a colheita."),
 },
 "es": {
  ("pulverizacao", "agora"): ("Fumigue {dia}, de {ini} a {fim} h.", "Viento de {vento_kmh} km/h, {temp}°C y {chuva_prob}% de probabilidad de lluvia.",
                              "temperatura, viento y humedad dentro de los límites", "BALK: fumigar {dia} {ini}-{fim}h. Viento {vento_kmh}km/h, lluvia {chuva_prob}%."),
  ("pulverizacao", "adiar"): ("Posponga la fumigación para {dia}, de {ini} a {fim} h.", "Antes hay viento o lluvia; en esa ventana el viento es de {vento_kmh} km/h y la lluvia {chuva_prob}%.",
                              "solo en esa ventana se cumplen los límites", "BALK: posponga la fumigacion a {dia} {ini}-{fim}h. Viento {vento_kmh}km/h."),
  ("pulverizacao", "evitar"): ("Evite fumigar en las próximas 72 horas.", "Viento hasta {vento_max} km/h y lluvia hasta {chuva_prob_max}% en las próximas 24 horas.",
                               "la lluvia lava el producto y el viento lo dispersa", "BALK: evite fumigar 72h. Viento hasta {vento_max}km/h, lluvia {chuva_prob_max}%."),
  ("geada", None): ("Helada {dia}, de {ini} a {fim} h. Proteja el cultivo sensible.", "Mínima prevista de {tmin}°C.",
                    "la temperatura queda bajo {limite}°C", "BALK: HELADA {dia} {ini}-{fim}h, min {tmin}C. Proteja cultivos sensibles."),
  ("estresse", None): ("Conviene revisar el cultivo esta semana.", "La vegetación del área está bastante más débil de lo esperado para la época.",
                       "la vegetación vista por el satélite está más débil que la referencia", "BALK: revise el cultivo. La vegetacion esta mas debil de lo esperado."),
  ("colheita", "janela"): ("Ventana de cosecha: {horas} horas secas desde {dia}, {ini} h.", "Lluvia esperada de {chuva_mm} mm en el período.",
                           "poca lluvia permite cosechar sin pérdida", "BALK: cosecha {dia} {ini}h, {horas}h secas. Lluvia {chuva_mm}mm."),
  ("colheita", "sem_janela"): ("Sin {horas} horas secas en los próximos 3 días. Posponga la cosecha.", "La lluvia prevista supera el límite en todas las ventanas.",
                               "cosechar mojado aumenta la pérdida", "BALK: sin {horas}h secas en 3 dias. Posponga la cosecha."),
 },
 "en": {
  ("pulverizacao", "agora"): ("Spray {dia}, {ini} to {fim} h.", "Wind {vento_kmh} km/h, {temp}°C and {chuva_prob}% chance of rain.",
                              "temperature, wind and humidity are within limits", "BALK: spray {dia} {ini}-{fim}h. Wind {vento_kmh}km/h, rain {chuva_prob}%."),
  ("pulverizacao", "adiar"): ("Postpone spraying to {dia}, {ini} to {fim} h.", "Before that wind or rain get in the way; in that window wind is {vento_kmh} km/h and rain {chuva_prob}%.",
                              "only that window meets the limits", "BALK: postpone spraying to {dia} {ini}-{fim}h. Wind {vento_kmh}km/h."),
  ("pulverizacao", "evitar"): ("Avoid spraying for the next 72 hours.", "Wind up to {vento_max} km/h and rain chance up to {chuva_prob_max}% in the next 24 hours.",
                               "rain washes the product off and wind spreads it", "BALK: avoid spraying 72h. Wind up to {vento_max}km/h, rain {chuva_prob_max}%."),
  ("geada", None): ("Frost {dia}, {ini} to {fim} h. Protect sensitive crops.", "Forecast low of {tmin}°C.",
                    "temperature drops below {limite}°C", "BALK: FROST {dia} {ini}-{fim}h, low {tmin}C. Protect sensitive crops."),
  ("estresse", None): ("Worth checking the crop this week.", "Vegetation in the area is much weaker than expected for the season.",
                       "vegetation seen by the satellite is well below the reference", "BALK: check your crop. Vegetation is weaker than expected."),
  ("colheita", "janela"): ("Harvest window: {horas} dry hours from {dia}, {ini} h.", "Expected rain of {chuva_mm} mm in the period.",
                           "little rain allows harvesting without loss", "BALK: harvest {dia} {ini}h, {horas}h dry. Rain {chuva_mm}mm."),
  ("colheita", "sem_janela"): ("No {horas} dry hours in the next 3 days. Postpone harvest.", "Forecast rain exceeds the limit in every window.",
                               "harvesting wet increases losses", "BALK: no {horas}h dry in 3 days. Postpone harvest."),
 },
}

# variantes que usam os dados do motor geo (relevo e localização da área fraca)
T["pt"][("geada", "relevo")] = ("Geada {dia}, das {ini}h às {fim}h. Proteja a lavoura sensível.", "Previsão de mínima de {tmin_previsto}°C; no ponto mais baixo da área pode chegar a {tmin}°C.",
                                "o ar frio se acumula nas baixadas da área", "BALK: GEADA {dia} {ini}h-{fim}h, min {tmin_previsto}C (baixada {tmin}C). Proteja culturas sensiveis.")
T["es"][("geada", "relevo")] = ("Helada {dia}, de {ini} a {fim} h. Proteja el cultivo sensible.", "Mínima prevista de {tmin_previsto}°C; en el punto más bajo del lote puede llegar a {tmin}°C.",
                                "el aire frío se acumula en las hondonadas", "BALK: HELADA {dia} {ini}-{fim}h, min {tmin_previsto}C (hondonada {tmin}C). Proteja cultivos sensibles.")
T["en"][("geada", "relevo")] = ("Frost {dia}, {ini} to {fim} h. Protect sensitive crops.", "Forecast low of {tmin_previsto}°C; at the lowest spot of the field it may reach {tmin}°C.",
                                "cold air pools in the field's low spots", "BALK: FROST {dia} {ini}-{fim}h, low {tmin_previsto}C (low spot {tmin}C). Protect sensitive crops.")
T["pt"][("estresse", "localizado")] = ("Vale conferir o lado {dir_txt} da lavoura nesta semana.", "{pct}% da área está mais fraca que o resto.",
                                       "a vegetação dessa parte está bem mais fraca que o restante", "BALK: confira o lado {dir_txt} da lavoura. {pct}% da area esta mais fraca.")
T["es"][("estresse", "localizado")] = ("Conviene revisar el lado {dir_txt} del cultivo esta semana.", "{pct}% del área está más débil que el resto.",
                                       "la vegetación de esa parte está mucho más débil que el resto", "BALK: revise el lado {dir_txt}. {pct}% del area esta mas debil.")
T["en"][("estresse", "localizado")] = ("Worth checking the {dir_txt} side of the crop this week.", "{pct}% of the area is weaker than the rest.",
                                       "vegetation there is much weaker than the rest of the field", "BALK: check the {dir_txt} side. {pct}% of the area is weaker.")
DIRS = {"pt": {"N": "norte", "NE": "nordeste", "E": "leste", "SE": "sudeste", "S": "sul", "SO": "sudoeste", "O": "oeste",
               "NO": "noroeste", "C": "central"},
        "es": {"N": "norte", "NE": "noreste", "E": "este", "SE": "sudeste", "S": "sur", "SO": "suroeste", "O": "oeste",
               "NO": "noroeste", "C": "central"},
        "en": {"N": "north", "NE": "northeast", "E": "east", "SE": "southeast", "S": "south", "SO": "southwest",
               "O": "west", "NO": "northwest", "C": "central"}}
TERRAIN = {  # linhas extras do relatório de WhatsApp (só aparecem se o dado existir)
    "pt": {"relevo": "Relevo: declividade média de {slope}%{asp}. Risco de erosão: {eros}.",
           "asp": ", encosta voltada para {dir}", "zonas": "A área tem {n} zonas de manejo. A mais fraca ocupa {pct}% e é por onde vale começar a olhar.",
           "agua": "Umidade da vegetação: {umid}. Chuva menos evaporação previstas em 72 h: {saldo} mm.",
           "agua_atencao": "Vale ficar de olho na água.", "baixada": "Baixada: no ponto mais frio a geada pode ser {off}°C mais forte.",
           "umid": {"baixa": "baixa", "media": "média", "alta": "alta"}, "eros": {"baixo": "baixo", "medio": "médio", "alto": "alto"}},
    "es": {"relevo": "Relieve: pendiente media de {slope}%{asp}. Riesgo de erosión: {eros}.",
           "asp": ", ladera hacia {dir}", "zonas": "El área tiene {n} zonas de manejo. La más débil ocupa {pct}% y es por donde conviene empezar a mirar.",
           "agua": "Humedad de la vegetación: {umid}. Lluvia menos evaporación prevista en 72 h: {saldo} mm.",
           "agua_atencao": "Conviene vigilar el agua.", "baixada": "Hondonada: en el punto más frío la helada puede ser {off}°C más fuerte.",
           "umid": {"baixa": "baja", "media": "media", "alta": "alta"}, "eros": {"baixo": "bajo", "medio": "medio", "alto": "alto"}},
    "en": {"relevo": "Terrain: average slope {slope}%{asp}. Erosion risk: {eros}.",
           "asp": ", slope facing {dir}", "zonas": "The area has {n} management zones. The weakest takes {pct}% and is where to start looking.",
           "agua": "Vegetation moisture: {umid}. Forecast rain minus evaporation over 72 h: {saldo} mm.",
           "agua_atencao": "Keep an eye on water.", "baixada": "Low spot: at the coldest point frost may be {off}°C stronger.",
           "umid": {"baixa": "low", "media": "medium", "alta": "high"}, "eros": {"baixo": "low", "medio": "medium", "alto": "high"}},
}

LOGISTICS = {
 "pt": ("Saia {dia} às {hora}h rumo a {destino} ({dist_km} km).", "Chuva esperada na rota: {chuva_mm} mm (na pior hora seriam {pior_mm} mm). Frete estimado: R$ {frete_rs}.",
        "BALK: saia {dia} {hora}h p/ {destino} ({dist_km}km). Chuva na rota {chuva_mm}mm. Frete ~R$ {frete_rs}."),
 "es": ("Salga {dia} a las {hora} h hacia {destino} ({dist_km} km).", "Lluvia esperada en la ruta: {chuva_mm} mm (en la peor hora serían {pior_mm} mm). Flete estimado: R$ {frete_rs}.",
        "BALK: salga {dia} {hora}h a {destino} ({dist_km}km). Lluvia ruta {chuva_mm}mm. Flete ~R$ {frete_rs}."),
 "en": ("Leave {dia} at {hora} h for {destino} ({dist_km} km).", "Expected rain on the route: {chuva_mm} mm (worst hour would be {pior_mm} mm). Estimated freight: R$ {frete_rs}.",
        "BALK: leave {dia} {hora}h for {destino} ({dist_km}km). Route rain {chuva_mm}mm. Freight ~R$ {frete_rs}."),
}


@dataclass
class Report:
    ranking: list[Viability]
    stats: Optional[SpatialStats]
    crop_pref: Optional[str] = None
    map_url: Optional[str] = None
    only_weather: bool = False  # cadastro só por município: sem viabilidade do talhão
    sem_imagem: bool = False  # satélite indisponível ou velho demais: só clima, e o relatório diz isso
    plot_name: Optional[str] = None  # só preenchido quando o produtor tem mais de um talhão
    relations: Optional[dict] = None  # {"saldo_mm": float, "atencao_agua": bool} (clima x umidade da vegetação)


def to_sms(text: str, limit: int = 160) -> str:
    """Sem acentos nem emojis (acento vira UCS2 e o limite cai para 70). Corta com '...' se passar."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return t if len(t) <= limit else t[:limit - 3] + "..."


def fmt(v, lang: Optional[str] = None) -> str:
    """Número para o produtor: inteiro sem casas; senão 1 casa, com vírgula em português e espanhol (23,5 °C)."""
    if isinstance(v, float):
        s = str(int(v)) if v.is_integer() else f"{v:.1f}"
        return s.replace(".", ",") if lang in ("pt", "es") else s
    return str(v)


def day_label(offset: Optional[int], weekday: Optional[int], lang: str) -> str:
    if offset in (0, 1):
        return TODAY_TOMORROW[lang][offset]
    return WEEKDAYS[lang][weekday] if weekday is not None else ""


def _fields(ev: dict, lang: str) -> dict:
    f = {k: fmt(v, lang) for k, v in ev.items()}
    f["dia"] = day_label(ev.get("dia_offset"), ev.get("weekday"), lang)
    f["ini"] = fmt(ev.get("inicio_h", ""), lang)
    f["fim"] = fmt(ev.get("fim_h", ""), lang)
    if ev.get("direcao"):
        f["dir_txt"] = DIRS[lang].get(ev["direcao"], ev["direcao"])
    return f


def terrain_lines(rep: "Report", lang: str) -> list[str]:
    """Linhas do relatório que vêm do motor geo. Cada uma só aparece se o dado existir."""
    s, T_ = rep.stats, TERRAIN[lang]
    if s is None:
        return []
    out = []
    age = (rep.relations or {}).get("idade_cena_dias")
    if age is not None and (rep.relations or {}).get("cena_antiga"):
        out.append({"pt": f"Atenção: a imagem de satélite é de {age} dias atrás, então a confiança é menor.",
                    "es": f"Atención: la imagen de satélite es de hace {age} días, así que la confianza es menor.",
                    "en": f"Note: the satellite image is {age} days old, so confidence is lower."}[lang])
    if s.slope_mean_pct is not None and s.erosion_class:
        asp = T_["asp"].format(dir=DIRS[lang][s.aspect_label]) if s.aspect_label else ""
        out.append(T_["relevo"].format(slope=fmt(round(s.slope_mean_pct, 1)), asp=asp, eros=T_["eros"][s.erosion_class]))
    if s.zones and len(s.zones) > 1:
        weak = s.zones[0]
        out.append(T_["zonas"].format(n=len(s.zones), pct=fmt(weak["share_pct"])))
    if s.moisture_class and rep.relations and rep.relations.get("saldo_mm") is not None:
        line = T_["agua"].format(umid=T_["umid"][s.moisture_class], saldo=fmt(rep.relations["saldo_mm"]))
        out.append(line + (" " + T_["agua_atencao"] if rep.relations.get("atencao_agua") else ""))
    if s.frost_relief_offset_c is not None and s.frost_relief_offset_c <= -0.3:
        out.append(T_["baixada"].format(off=fmt(abs(s.frost_relief_offset_c))))
    return out


def _key(alert: Alert) -> tuple:
    return alert.type, alert.evidence.get("modo")


PLOT_LABEL = {"pt": "Talhão", "es": "Lote", "en": "Plot"}


def render_alert(alert: Alert, channel: str, lang: str = "pt", plot: Optional[str] = None) -> str:
    """`plot`: nome do talhão, usado quando o produtor tem mais de um ("Talhão Fundo: Pulverize hoje...")."""
    l1, l2, why, sms = T[lang][_key(alert)]
    f = _fields(alert.evidence, lang)
    if channel == "sms":
        body = sms.format(**f)
        if plot:
            body = body.replace("BALK:", f"BALK {plot[:12].strip()}:", 1)
        return to_sms(body, 160 - len(SMS_SUFFIX)) + SMS_SUFFIX
    # WhatsApp: 3 linhas e ao ponto (ação, o dado que a justifica, confiança + como responder). O "por quê" completo,
    # com cada critério da regra, fica no relatório do link.
    lc = LBL[lang][1]
    head = f"*{PLOT_LABEL[lang]} {plot}:* " if plot else ""
    return f"{head}{l1.format(**f)}\n{l2.format(**f)}\n{lc}: {CONF[lang][alert.confidence]}. {REPLY[lang]}"


REPLY = {"pt": "Responda 1 se vai fazer, 2 para falar com um agrônomo.",
         "es": "Responda 1 si lo hará, 2 para hablar con un agrónomo.",
         "en": "Reply 1 if you will do it, 2 to talk to an agronomist."}


def _orientation(v: Viability, lang: str) -> str:
    if lang == "pt":
        return v.orientation
    return ORIENT[lang].get(v.limiting_factor, ORIENT[lang]["_ok"]) if v.factors.get(v.limiting_factor, 0) < 0.8 \
        else ORIENT[lang]["_ok"]


def render_report(rep: Report, channel: str, lang: str = "pt") -> str:
    crops = CROPS[lang]
    if rep.sem_imagem:  # estado explícito "sem imagem adequada": não se apresenta dado velho nem simulado como atual
        msg = {"pt": "Não consegui uma imagem de satélite recente e boa da sua área agora (nuvem ou falha). Hoje só envio avisos de clima, com menos confiança. Tento de novo amanhã.",
               "es": "No conseguí una imagen de satélite reciente y buena de su área ahora (nubes o falla). Hoy solo envío avisos de clima, con menos confianza. Intento de nuevo mañana.",
               "en": "I could not get a recent, good satellite image of your area right now (clouds or outage). Today I only send weather alerts, with lower confidence. I will try again tomorrow."}[lang]
        return to_sms("BALK: sem imagem de satelite boa agora. So avisos de clima hoje. Tento amanha.", 160) if channel == "sms" else msg
    if rep.only_weather or not rep.ranking:
        msg = {"pt": "BALK: cadastro por município recebe alertas de clima. Para a análise da lavoura, envie o pin de localização pelo WhatsApp.",
               "es": "BALK: el registro por municipio recibe alertas de clima. Para el análisis del lote, envíe la ubicación por WhatsApp.",
               "en": "BALK: municipality sign-up gets weather alerts. For field analysis, send your location pin on WhatsApp."}[lang]
        return to_sms(msg, 160) if channel == "sms" else msg
    top = rep.ranking[0]  # a cultura informada vem primeiro (ou a melhor, se o produtor não informou)
    lim = FACTOR[lang].get(top.limiting_factor, top.limiting_factor)
    if channel == "sms":
        short = SHORT[lang].get(top.limiting_factor, SHORT[lang]["_ok"]) if top.factors.get(top.limiting_factor, 0) < 0.8 \
            else SHORT[lang]["_ok"]
        tag = f"BALK {rep.plot_name[:12].strip()}" if rep.plot_name else "BALK"
        return to_sms(f"{tag}: {crops[top.crop]} nota {top.score}/100. Limite: {lim}. {short}", 160)
    # WhatsApp: curto e ao ponto. Nota da cultura, a melhor alternativa (se for bem melhor), UM ponto de atenção,
    # a confiança e o aviso. Os números, mapas, zonas, relevo, água e a conta de cada nota ficam no relatório do link.
    head = {"pt": "*BALK · sua lavoura*", "es": "*BALK · su cultivo*", "en": "*BALK · your field*"}[lang]
    if rep.plot_name:
        head = f"*BALK · {PLOT_LABEL[lang]} {rep.plot_name}*"
    lines = [head]
    ordered = sorted(rep.ranking, key=lambda v: -v.score)
    best = ordered[0]
    mine = next((v for v in rep.ranking if v.crop == rep.crop_pref), None) if rep.crop_pref else None
    nota = {"pt": "{c}: nota {s}/100 ({q}).", "es": "{c}: nota {s}/100 ({q}).", "en": "{c}: score {s}/100 ({q})."}[lang]
    if mine:
        lines.append(nota.format(c=crops[mine.crop].capitalize(), s=mine.score, q=QUALITY[lang][_quality(mine.score)]))
        if best.crop != mine.crop and best.score - mine.score >= 10:
            lines.append({"pt": "Melhor opção para esta área: {c} ({s}/100).", "es": "Mejor opción para esta área: {c} ({s}/100).",
                          "en": "Best option for this area: {c} ({s}/100)."}[lang].format(c=crops[best.crop], s=best.score))
    else:
        lines.append({"pt": "Melhor cultura para esta área: {c}, nota {s}/100.", "es": "Mejor cultivo para esta área: {c}, nota {s}/100.",
                      "en": "Best crop for this area: {c}, score {s}/100."}[lang].format(c=crops[best.crop], s=best.score))
    focus = mine or best
    r = rep.relations or {}
    old = bool(r.get("cena_antiga") and r.get("idade_cena_dias") is not None)
    if focus.factors.get(focus.limiting_factor, 0) < 0.8:
        o = _orientation(focus, lang)
        lines.append({"pt": "Atenção", "es": "Atención", "en": "Watch out"}[lang] + f": {o[:1].lower() + o[1:]}")
        if old:  # imagem velha muda a confiança: o produtor precisa saber mesmo quando já há outro ponto de atenção
            lines.append({"pt": f"A imagem de satélite é de {r['idade_cena_dias']} dias atrás.", "es": f"La imagen de satélite es de hace {r['idade_cena_dias']} días.",
                          "en": f"The satellite image is {r['idade_cena_dias']} days old."}[lang])
    else:
        extra = _main_extra(rep, lang)
        lines.append(extra or _orientation(focus, lang))  # sem fator crítico: não inventa um "ponto de atenção"
    lines.append(f"{LBL[lang][1]}: {CONF[lang][focus.confidence]}. {DISCLAIMER_SHORT[lang]}")
    if rep.map_url:
        lines.append({"pt": "Mapa", "es": "Mapa", "en": "Map"}[lang] + f": {rep.map_url}")
    return "\n".join(lines)


QUALITY = {"pt": {"boa": "boa", "media": "média", "baixa": "baixa"}, "es": {"boa": "buena", "media": "media", "baixa": "baja"},
           "en": {"boa": "good", "media": "fair", "baixa": "low"}}
DISCLAIMER_SHORT = {"pt": "Não substitui um engenheiro agrônomo.", "es": "No sustituye a un ingeniero agrónomo.",
                    "en": "Not a substitute for an agronomist."}


def _quality(score: int) -> str:
    return "boa" if score >= 70 else "media" if score >= 50 else "baixa"


def _main_extra(rep: "Report", lang: str) -> Optional[str]:
    """Sem fator crítico na nota: o ponto de atenção mais importante que o motor geo achou (só um), ou nada."""
    s, r = rep.stats, rep.relations or {}
    if s is None:
        return None
    if r.get("cena_antiga") and r.get("idade_cena_dias") is not None:
        return {"pt": f"Atenção: a imagem de satélite é de {r['idade_cena_dias']} dias atrás.", "es": f"Atención: la imagen es de hace {r['idade_cena_dias']} días.",
                "en": f"Note: the satellite image is {r['idade_cena_dias']} days old."}[lang]
    if r.get("atencao_agua"):
        return {"pt": "Atenção: a lavoura está com pouca água e a previsão não repõe. Fique de olho.",
                "es": "Atención: el cultivo tiene poca agua y el pronóstico no la repone.",
                "en": "Watch out: the crop is low on water and the forecast will not make up for it."}[lang]
    if s.erosion_class == "alto":
        return {"pt": "Atenção: risco alto de erosão no terreno.", "es": "Atención: riesgo alto de erosión.", "en": "Watch out: high erosion risk."}[lang]
    if s.weak_area_pct is not None and s.weak_area_pct >= 25 and s.weak_area_dir:
        where = {"pt": "no centro", "es": "en el centro", "en": "in the middle"}[lang] if s.weak_area_dir == "C" else \
            {"pt": "no lado {d}", "es": "lado {d}", "en": "{d} side"}[lang].format(d=DIRS[lang].get(s.weak_area_dir, ""))
        return {"pt": f"Atenção: {s.weak_area_pct:.0f}% da área está mais fraca, {where}.",
                "es": f"Atención: {s.weak_area_pct:.0f}% del área está más débil, {where}.",
                "en": f"Watch out: {s.weak_area_pct:.0f}% of the area is weaker, {where}."}[lang]
    return None


def render_logistics(plan: dict, channel: str, lang: str = "pt") -> str:
    l1, l2, sms = LOGISTICS[lang]
    f = {k: fmt(v, lang) for k, v in plan.items() if not isinstance(v, (dict, list))}
    f["dia"] = day_label(plan.get("dia_offset"), plan.get("weekday"), lang)
    f["hora"] = fmt(plan.get("hora"))
    text = sms.format(**f) if channel == "sms" else f"{l1.format(**f)}\n{l2.format(**f)}"
    return to_sms(text, 160) if channel == "sms" else text


def render(item: Union[Alert, Report, dict], channel: str, lang: str = "pt", plot: Optional[str] = None) -> str:
    """Alerta ou relatório -> texto final do canal (WhatsApp completo; SMS até 160 caracteres, sem acento).
    `plot` = nome do talhão, quando o produtor tem mais de um."""
    if isinstance(item, Alert):
        return render_alert(item, channel, lang, plot)
    if isinstance(item, Report):
        return render_report(item, channel, lang)
    return render_logistics(item, channel, lang)
