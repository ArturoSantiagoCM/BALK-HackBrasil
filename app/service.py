"""Orquestra M2..M6 para um produtor: análise espacial, viabilidade, alertas e mensagens prontas.

Princípios que este arquivo faz valer:
- falha de fonte externa NUNCA vira alerta nem dado inventado: sem imagem adequada o relatório diz isso e só há aviso de clima;
- imagem velha não é apresentada como atual (confiança baixa e aviso; muito velha = "sem imagem adequada");
- nada é enviado a quem não aceitou (list_active só traz quem aceitou e está ativo).
"""
import json
import logging
import os
from datetime import datetime
from typing import Optional

from app import config, db, db_site, report
from app.alerts import evaluate
from app.data.climate import get_climate_history, mean_monthly_rain
from app.data.package import build_local_package
from app.data.weather import get_weather
from app.delivery import deliver
from app.engine import analyze
from app.geo.relations import water_attention, water_balance
from app.message import render, with_link
from app.message.templates import Report
from app.viability import rank_crops

log = logging.getLogger("balk.service")


def _use_ai() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY")) and os.getenv("USE_AI_POLISH", "1") == "1"


def _work_key(pid: int, plot: Optional[dict]) -> Optional[str]:
    """Pasta de dados própria de cada talhão ("12-p3"); sem talhão desenhado, a pasta do produtor."""
    return f"{pid}-p{plot['id']}" if plot else None


def _make_report(p, now, weather, stats, ranking, climate, alerts, relations_, messages, prerender_images: bool,
                 plot: Optional[dict] = None, extras: Optional[dict] = None) -> tuple[str, str]:
    """Guarda o relatório detalhado (dados + a conta de cada conclusão) e devolve (link pessoal, token)."""
    meta = {}
    polygon = plot["geojson"] if plot else None
    key = _work_key(p.id, plot)
    if stats is not None:
        mf = build_local_package(p, polygon=polygon, key=key) / "meta.json"
        if mf.exists():
            meta = json.loads(mf.read_text(encoding="utf-8"))
    data = report.build(p, now, weather, stats, ranking, climate, alerts, relations_, messages, meta, extras)
    data["chuva_mes_mm"] = mean_monthly_rain(climate)
    if plot:  # relatório do talhão desenhado: o mapa e as contas valem para ele, não para o círculo de 7 ha
        data["poligono"] = polygon
        data["talhao"] = {"nome": plot["name"], "area_ha": plot["area_ha"]}
        data["work_key"] = key
    token = db.create_report(p.id, data, config.report_ttl_days())
    if prerender_images:  # primeiro relatório: o link já abre com os mapas prontos
        try:
            report.prerender(p.id, token, data, p.lat, p.lon, data["chuva_mes_mm"])
        except Exception:  # noqa: BLE001  (sem imagem a página ainda abre; elas são geradas na primeira visita)
            log.exception("falha ao gerar as imagens do relatório")
    return f"{config.public_base_url()}/r/{token}", token


def _plot_centroid(plot: dict) -> tuple[float, float]:
    from shapely.geometry import shape
    c = shape(plot["geojson"]).centroid
    return c.y, c.x


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    dy = (lat2 - lat1) * 111.32
    dx = (lon2 - lon1) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


SAME_WEATHER_KM = 5.0  # a grade do clima tem ~10 km: talhões mais perto que isso dividem a mesma previsão


def _analyze_unit(p, plot: Optional[dict], full: bool, now: datetime, multi: bool, already: int, wx: list) -> dict:
    """Análise de UM talhão (ou da propriedade inteira, sem talhão desenhado): satélite, viabilidade, alertas e mensagens.
    `wx` guarda (lat, lon, clima, histórico) já buscados nesta rodada: talhões vizinhos reaproveitam o mesmo clima."""
    plot_id = plot["id"] if plot else 0
    plot_name = plot["name"] if plot else None
    label = plot_name if (multi and plot_name) else None  # o nome só aparece quando há mais de um talhão
    if plot:
        lat, lon = _plot_centroid(plot)
        p = p.model_copy(update={"crop": plot["crop"] or p.crop, "planting_date": plot["planting_date"] or p.planting_date,
                                 "lat": lat, "lon": lon, "location_precision": "ponto"})
    polygon = plot["geojson"] if plot else None
    key = _work_key(p.id, plot)
    shared = next((w for w in wx if _km(w["lat"], w["lon"], p.lat, p.lon) <= SAME_WEATHER_KM), None)
    if shared is None:
        shared = {"lat": p.lat, "lon": p.lon, "weather": get_weather(p.lat, p.lon, now), "climate": None, "climate_done": False}
        wx.append(shared)
        first_on_weather = True
    else:
        first_on_weather = False
    weather = shared["weather"]
    stats, ranking, map_url, relations_, climate, sem_imagem = None, [], None, None, None, False
    sat = config.rules().get("satelite", {})
    season, hist = None, None
    if p.location_precision == "ponto":
        if not shared["climate_done"]:
            try:
                shared["climate"] = get_climate_history(p.lat, p.lon, today=now)  # antes da análise: a chuva alimenta a erosão
            except Exception:  # noqa: BLE001
                log.exception("histórico de clima indisponível")
            shared["climate_done"] = True
        climate = shared["climate"]
        try:
            stats = analyze(p, rain_month_mm=mean_monthly_rain(climate), polygon=polygon, key=key)
        except Exception:  # noqa: BLE001
            log.exception("análise de satélite indisponível (produtor %s, talhão %s)", p.id, plot_id)
            sem_imagem = True
        age = None
        if stats is not None and stats.scene_date:
            age = (now.date() - datetime.fromisoformat(stats.scene_date).date()).days
            if age > sat.get("descartar_apos_dias", 60):
                stats, sem_imagem = None, True  # velha demais: não se apresenta como atual
        if stats is not None and stats.valid_fraction is not None and stats.valid_fraction < sat.get("util_minimo", 0.1):
            stats, sem_imagem = None, True  # nuvem cobrindo o talhão: sem dado de vegetação, não se finge análise
        if plot:  # safra do talhão e histórico de NDVI (a referência vem ANTES de gravar a cena de hoje)
            season = db_site.ensure_season(p.id, plot_id, p.crop, p.planting_date)
            if stats is not None:
                cycle_day = (now.date() - datetime.fromisoformat(p.planting_date).date()).days if p.planting_date else None
                hist = db_site.observation_history(p.id, plot_id, p.crop, cycle_day, season["id"] if season else None, now=now) or None
                src = "simulado"
                mf = config.work_root() / key / "meta.json"
                if mf.exists():
                    src = json.loads(mf.read_text(encoding="utf-8")).get("source", "simulado")
                db_site.save_observation(p.id, plot_id, season["id"] if season else None, stats, src)
        if stats is not None:
            month = int(p.planting_date[5:7]) if p.planting_date else None
            ranking = rank_crops(stats, climate, crop_pref=p.crop, planting_month=month, today=now)
            wb = water_balance(weather.hours)  # clima x umidade da vegetação (NDMI)
            relations_ = {**wb, "idade_cena_dias": age,
                          "cena_antiga": age is not None and age > sat.get("aviso_apos_dias", 30),
                          "atencao_agua": water_attention(stats.moisture_class, wb["saldo_mm"],
                                                          config.rules().get("agua", {}).get("balanco_deficit_mm", -5))}
    alerts = evaluate(p, weather, stats, now=now, ndvi_history=hist, plot_id=plot_id, already=already,
                      skip=None if first_on_weather else {"pulverizacao"})
    messages = []
    if full:
        rep = Report(ranking=ranking, stats=stats, crop_pref=p.crop, map_url=None, only_weather=stats is None,
                     relations=relations_, sem_imagem=sem_imagem, plot_name=label)
        messages.append({"kind": "report", "type": "relatorio", "text": render(rep, p.channel, p.lang),
                         "sms_text": render(rep, "sms", p.lang), "media_url": None, "confidence": None, "evidence": None,
                         "so_clima": stats is None and not sem_imagem})  # cadastro por município: o texto de boas-vindas já explica
    for a in alerts:
        messages.append({"kind": "alert", "type": a.type, "text": render(a, p.channel, p.lang, use_ai=_use_ai(), plot=label),
                         "sms_text": render(a, "sms", p.lang, plot=label), "confidence": a.confidence, "evidence": a.evidence})
    report_url, token = None, None
    if messages:  # há algo a enviar: guarda o relatório detalhado e põe o link depois de cada mensagem
        safras = [s for s in db_site.seasons_overview(p.id) if s["plot_id"] == plot_id] if plot else []
        report_url, token = _make_report(p, now, weather, stats, ranking, climate, alerts, relations_, messages, full, plot,
                                         extras={"referencia_vigor": hist, "safras": safras})
        for m in messages:
            m["text"] = with_link(m["text"], p.channel, p.lang, report_url)
            m["report_token"], m["plot_id"], m["plot_name"] = token, plot_id, plot_name
            if m["kind"] == "report" and stats is not None and p.channel == "whatsapp":
                map_url = m["media_url"] = f"{report_url}/img/mapa.png"  # mapa-resumo, na mesma pasta do relatório
    return {"plot": {"id": plot["id"], "nome": plot["name"], "area_ha": plot["area_ha"]} if plot else None,
            "weather_source": weather.source, "sem_imagem": sem_imagem, "stats": stats.model_dump() if stats else None,
            "relations": relations_, "ranking": [v.model_dump() for v in ranking], "alerts": [a.model_dump() for a in alerts],
            "alert_objs": alerts, "map_url": map_url, "report_url": report_url, "report_token": token, "messages": messages,
            "location_precision": p.location_precision}


def analyze_producer(pid: int, full: bool = True, now: Optional[datetime] = None) -> dict:
    """Roda M3 e M4 (se o local é um ponto), M5 e M6 para CADA talhão do produtor (mensagem e relatório por talhão; o nome
    do talhão só aparece quando há mais de um). Não registra alertas: quem envia chama db.log_alert com o plot_id.

    O clima é indispensável: se falhar, a exceção sobe (quem chama decide; run_daily pula o produtor e registra o erro).
    O satélite não: se falhar ou for velho demais, vira o estado explícito `sem_imagem` e só há aviso de clima.
    Os campos de nível superior (stats, ranking, report_url...) são os do maior talhão; `units` traz todos.
    """
    now = now or datetime.now()
    p = db.get_producer(pid)
    if p is None:
        raise KeyError(pid)
    plots = db.list_plots(p.id)  # do maior para o menor
    multi = len(plots) > 1
    wx: list = []
    units, already = [], 0
    for plot in (plots or [None]):
        u = _analyze_unit(p, plot, full, now, multi, already, wx)
        already += sum(1 for a in u["alert_objs"] if a.type != "geada")
        units.append(u)
    first = units[0]
    messages = [m for u in units for m in u["messages"]]
    token = next((u["report_token"] for u in units if u["report_token"]), None)
    url = next((u["report_url"] for u in units if u["report_url"]), None)
    result = {"producer_id": p.id, "phone": p.phone, "channel": p.channel, "lang": p.lang,
              "location_precision": first["location_precision"], "weather_source": first["weather_source"],
              "sem_imagem": any(u["sem_imagem"] for u in units), "plot": first["plot"], "stats": first["stats"],
              "relations": first["relations"], "ranking": first["ranking"],
              "alerts": [a for u in units for a in u["alerts"]], "map_url": first["map_url"], "report_url": url,
              "report_token": token, "messages": messages,
              "units": [{k: v for k, v in u.items() if k != "alert_objs"} for u in units]}
    db.save_analysis(p.id, result)
    return result


def send_first_reports(pid: int, now: Optional[datetime] = None) -> list[dict]:
    """Primeira análise depois do cadastro (site ou WhatsApp): um relatório por talhão, entregue pelo canal do produtor.
    Só os relatórios saem (alertas só no ciclo diário). Falha de clima levanta: o chamador avisa e tenta depois."""
    res = analyze_producer(pid, full=True, now=now)
    p = db.get_producer(pid)
    out = []
    for m in res["messages"]:
        if m["kind"] != "report":
            continue
        r = deliver(p.id, p.phone, p.channel, m["text"], kind="report", type_="relatorio", report_token=m.get("report_token"),
                    media_url=m.get("media_url"), proactive=True, sms_text=m["sms_text"])
        out.append({"plot_id": m.get("plot_id") or 0, "ok": r["ok"], "canal_usado": r["channel"]})
    return out


def run_daily(now: Optional[datetime] = None, errors: Optional[list] = None) -> list[dict]:
    """O ciclo diário: para cada produtor ativo, analisa, entrega (com reserva por SMS), registra e copia ao sucessor.

    Um produtor que falha (clima fora do ar, erro interno) é pulado e anotado em `errors`: os outros continuam,
    e ninguém recebe alerta feito com dado faltando.
    """
    now = now or datetime.now()
    sent = []
    for p in db.list_active():
        try:
            res = analyze_producer(p.id, full=False, now=now)
        except Exception as e:  # noqa: BLE001
            log.exception("análise diária falhou para o produtor %s", p.id)
            if errors is not None:
                errors.append({"producer_id": p.id, "erro": f"{type(e).__name__}: {e}"[:200]})
            continue
        alert_msgs = [m for m in res["messages"] if m["kind"] == "alert"]
        for a, m in zip(res["alerts"], alert_msgs):
            r = deliver(p.id, p.phone, p.channel, m["text"], kind="alert", type_=a["type"], confidence=a["confidence"],
                        evidence=a["evidence"], report_token=m.get("report_token") or res["report_token"], proactive=True,
                        sms_text=m["sms_text"])
            if r["ok"]:  # só entra no silêncio o que foi entregue, no talhão de origem
                db.log_alert(p.id, a["type"], now.isoformat(timespec="seconds"), m.get("plot_id") or 0)
                for c in db.list_contacts(p.id, only_active=True):  # o sucessor aceitou por conta própria: recebe cópia
                    deliver(p.id, c["phone"], p.channel, m["text"], kind="alert_copia", type_=a["type"],
                            confidence=a["confidence"], report_token=m.get("report_token") or res["report_token"],
                            proactive=True, sms_text=m["sms_text"])
            sent.append({"producer_id": p.id, "phone": p.phone, "channel": p.channel, "canal_usado": r["channel"],
                         "ok": r["ok"], "type": a["type"], "text": m["text"], "confidence": a["confidence"],
                         "plot_id": m.get("plot_id") or 0})
    return sent
