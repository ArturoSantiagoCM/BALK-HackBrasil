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
  ("estresse", None): ("Vale conferir a lavoura nesta semana.", "O vigor da área está abaixo do esperado (z = {z}).",
                       "o NDVI atual é bem menor que a referência", "BALK: vale conferir a lavoura. Vigor abaixo do esperado (z {z})."),
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
  ("estresse", None): ("Conviene revisar el cultivo esta semana.", "El vigor del área está bajo lo esperado (z = {z}).",
                       "el NDVI actual es menor que la referencia", "BALK: revise el cultivo. Vigor bajo lo esperado (z {z})."),
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
  ("estresse", None): ("Worth checking the crop this week.", "Vigor in the area is below expected (z = {z}).",
                       "current NDVI is well below the reference", "BALK: check your crop. Vigor below expected (z {z})."),
  ("colheita", "janela"): ("Harvest window: {horas} dry hours from {dia}, {ini} h.", "Expected rain of {chuva_mm} mm in the period.",
                           "little rain allows harvesting without loss", "BALK: harvest {dia} {ini}h, {horas}h dry. Rain {chuva_mm}mm."),
  ("colheita", "sem_janela"): ("No {horas} dry hours in the next 3 days. Postpone harvest.", "Forecast rain exceeds the limit in every window.",
                               "harvesting wet increases losses", "BALK: no {horas}h dry in 3 days. Postpone harvest."),
 },
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


def to_sms(text: str, limit: int = 160) -> str:
    """Sem acentos nem emojis (acento vira UCS2 e o limite cai para 70). Corta com '...' se passar."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return t if len(t) <= limit else t[:limit - 3] + "..."


def fmt(v) -> str:
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else f"{v:.1f}"
    return str(v)


def day_label(offset: Optional[int], weekday: Optional[int], lang: str) -> str:
    if offset in (0, 1):
        return TODAY_TOMORROW[lang][offset]
    return WEEKDAYS[lang][weekday] if weekday is not None else ""


def _fields(ev: dict, lang: str) -> dict:
    f = {k: fmt(v) for k, v in ev.items()}
    f["dia"] = day_label(ev.get("dia_offset"), ev.get("weekday"), lang)
    f["ini"] = fmt(ev.get("inicio_h", ""))
    f["fim"] = fmt(ev.get("fim_h", ""))
    return f


def _key(alert: Alert) -> tuple:
    return alert.type, alert.evidence.get("modo")


def render_alert(alert: Alert, channel: str, lang: str = "pt") -> str:
    l1, l2, why, sms = T[lang][_key(alert)]
    f = _fields(alert.evidence, lang)
    if channel == "sms":
        body = sms.format(**f)
        return to_sms(body, 160 - len(SMS_SUFFIX)) + SMS_SUFFIX
    lw, lc = LBL[lang]
    return (f"{l1.format(**f)}\n{l2.format(**f)}\n\n{lw}: {why.format(**f)}.\n"
            f"{lc}: {CONF[lang][alert.confidence]}.")


def _orientation(v: Viability, lang: str) -> str:
    if lang == "pt":
        return v.orientation
    return ORIENT[lang].get(v.limiting_factor, ORIENT[lang]["_ok"]) if v.factors.get(v.limiting_factor, 0) < 0.8 \
        else ORIENT[lang]["_ok"]


def render_report(rep: Report, channel: str, lang: str = "pt") -> str:
    crops = CROPS[lang]
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
        return to_sms(f"BALK: {crops[top.crop]} nota {top.score}/100. Limite: {lim}. {short}", 160)
    head = {"pt": "*BALK: viabilidade da sua área*", "es": "*BALK: viabilidad de su área*",
            "en": "*BALK: your field's viability*"}[lang]
    area = {"pt": "Área analisada: {a} ha (cena de satélite de {d}).", "es": "Área analizada: {a} ha (escena de {d}).",
            "en": "Area analysed: {a} ha (satellite scene of {d})."}[lang]
    lines = [head, area.format(a=fmt(rep.stats.area_ha), d=rep.stats.scene_date or "-")]
    if rep.crop_pref:
        mine = next((v for v in rep.ranking if v.crop == rep.crop_pref), None)
        if mine:
            lines.append({"pt": "Sua cultura: {c}, nota {s}/100.", "es": "Su cultivo: {c}, nota {s}/100.",
                          "en": "Your crop: {c}, score {s}/100."}[lang].format(c=crops[mine.crop], s=mine.score))
    lines.append({"pt": "Mais indicadas:", "es": "Más indicados:", "en": "Best suited:"}[lang])
    ordered = sorted(rep.ranking, key=lambda v: -v.score)
    lines += [f"{i}. {crops[v.crop]}: {v.score}/100" for i, v in enumerate(ordered, 1)]
    if top.factors.get(top.limiting_factor, 0) < 0.8:
        label = {"pt": "Ponto de atenção", "es": "Punto de atención", "en": "Main concern"}[lang]
        lines.append(f"{label} ({lim}): {_orientation(top, lang)}")
    else:
        lines.append(_orientation(top, lang))  # sem fator crítico: não aponta um "ponto de atenção" falso
    lines.append(f"{LBL[lang][1]}: {CONF[lang][top.confidence]}.")
    lines.append(DISCLAIMER[lang])
    if rep.map_url:
        lines.append({"pt": "Mapa", "es": "Mapa", "en": "Map"}[lang] + f": {rep.map_url}")
    return "\n".join(lines)


def render_logistics(plan: dict, channel: str, lang: str = "pt") -> str:
    l1, l2, sms = LOGISTICS[lang]
    f = {k: fmt(v) for k, v in plan.items() if not isinstance(v, (dict, list))}
    f["dia"] = day_label(plan.get("dia_offset"), plan.get("weekday"), lang)
    f["hora"] = fmt(plan.get("hora"))
    text = sms.format(**f) if channel == "sms" else f"{l1.format(**f)}\n{l2.format(**f)}"
    return to_sms(text, 160) if channel == "sms" else text


def render(item: Union[Alert, Report, dict], channel: str, lang: str = "pt") -> str:
    """Alerta ou relatório -> texto final do canal (WhatsApp completo; SMS até 160 caracteres, sem acento)."""
    if isinstance(item, Alert):
        return render_alert(item, channel, lang)
    if isinstance(item, Report):
        return render_report(item, channel, lang)
    return render_logistics(item, channel, lang)
