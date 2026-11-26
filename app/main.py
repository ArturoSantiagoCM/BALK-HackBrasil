"""FastAPI: só rotas finas. A lógica está nos módulos (testáveis); o n8n só chama estes endpoints.

Três grupos de rotas:
- internas (n8n, painel): exigem a chave BALK_API_KEY (header X-API-Key ou Bearer);
- públicas com defesa própria: webhooks (assinatura da Meta e da Twilio) e a página de relatório (token aleatório, expira);
- de demonstração (simulador, /maps, /docs): só existem fora de BALK_ENV=production.
"""
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from app import config, db, db_site, report, security, site_api, webhooks  # noqa: E402
from app.channels import OUTBOX, get_channel  # noqa: E402
from app.data import simulated  # noqa: E402
from app.ingest.conversation import handle_message  # noqa: E402
from app.ingest.csv_import import ingest_rows, parse_csv_text  # noqa: E402
from app.delivery import deliver  # noqa: E402
from app.logistics import load_destinations, plan_route  # noqa: E402
from app.logistics.forecast import coop_forecast  # noqa: E402
from app.message import render  # noqa: E402
from app.service import analyze_producer, run_daily  # noqa: E402

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
log = logging.getLogger("balk")
ROOT = config.ROOT

internal = APIRouter(dependencies=[Depends(security.require_api_key)])
public = APIRouter()
demo = APIRouter(dependencies=[Depends(security.require_api_key_outside_demo)])  # em BALK_ENV=demo abre sem chave
report_limiter = security.RateLimiter(60, 60)
webhook_limiter = security.RateLimiter(600, 60)
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
IMG_RE = re.compile(r"^[a-z0-9_]{1,32}\.png$")


async def observe(request: Request, call_next):
    """Log em uma linha por requisição (sem token de relatório e sem telefone) e cabeçalhos de segurança."""
    rid = request.headers.get("x-request-id", "")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", rid):  # valor do cliente só se for inofensivo
        rid = uuid.uuid4().hex[:12]
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001
        log.exception(json.dumps({"evt": "erro_interno", "rid": rid, "path": _safe_path(request.url.path)}))
        response = JSONResponse({"erro": "erro interno", "id": rid}, status_code=500)
    response.headers.setdefault("X-Request-ID", rid)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    path = request.url.path
    # as páginas do mapa mandam só a origem (o MapTiler pode restringir a chave por domínio); o resto não manda nada
    response.headers.setdefault("Referrer-Policy", "strict-origin" if path == "/" or path.startswith("/app") else "no-referrer")
    if config.public_base_url().startswith("https://"):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if path == "/" or path.startswith(("/app", "/m/")):
        response.headers.setdefault("Content-Security-Policy", _site_csp())
        response.headers.setdefault("X-Frame-Options", "DENY")
    if path.startswith(("/api", "/m/")):
        response.headers.setdefault("Cache-Control", "no-store")
    log.info(json.dumps({"evt": "req", "rid": rid, "m": request.method, "path": _safe_path(request.url.path),
                         "st": response.status_code, "ms": round((time.perf_counter() - t0) * 1000)}))
    return response


def _safe_path(path: str) -> str:
    return re.sub(r"^/(r|h|m)/[^/]+", r"/\1/***", path)


class ConversationIn(BaseModel):
    phone: str
    text: str = ""
    channel: str = "whatsapp"
    lat: Optional[float] = None
    lon: Optional[float] = None
    source: str = "direto"


class AlertLogIn(BaseModel):
    producer_id: int
    type: str
    sent_at: Optional[str] = None


class LogisticsIn(BaseModel):
    producer_id: int
    destination_id: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    now: Optional[str] = None


def _now(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


def _conversation(body: ConversationIn) -> dict:
    loc = (body.lat, body.lon) if body.lat is not None and body.lon is not None else None
    reply = handle_message(body.phone, body.text, body.channel, location=loc, source=body.source)
    messages = [{"kind": "reply", "text": reply.text}]
    if reply.became_active:  # primeira análise ao virar ATIVO (M3 + M4), em segundos
        try:
            res = analyze_producer(reply.producer_id, full=True)
            messages += [m for m in res["messages"] if m["kind"] == "report"]
        except Exception:  # noqa: BLE001  (clima fora do ar: o cadastro vale e o relatório vem no próximo ciclo)
            log.exception("primeira análise falhou")
            messages.append({"kind": "reply", "text": "Tive um problema para buscar os dados agora. Seu cadastro está feito e eu aviso assim que conseguir."})
    for phone, text, channel in reply.notify:  # convite ao sucessor (outra pessoa): sai pelo canal e aparece no simulador
        deliver(reply.producer_id, phone, channel, text, kind="convite", proactive=True)
        messages.append({"kind": "notify", "to": phone, "text": text})
    return {"reply": reply.text, "became_active": reply.became_active, "producer_id": reply.producer_id,
            "messages": messages}


# ------------------------------------------------------------------ públicas
@public.get("/health")
def health():
    """Vivo? (para o balanceador e o Docker). Em production não revela configuração."""
    if config.is_production():
        return {"ok": True}
    return {"ok": True, "data_mode": config.data_mode(), "engine": config.engine_name()}


@internal.get("/ready")
def ready():
    """Pronto para uso real? Mostra a configuração (sem segredos) e o que falta."""
    try:
        with db.connect() as con:
            con.execute("SELECT 1")
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"ok": db_ok, "env": config.env(), "data_mode": config.data_mode(), "engine": config.engine_name(),
            "pendencias": config.production_problems(),
            "canais": {"whatsapp": bool(os.getenv("WHATSAPP_TOKEN")), "sms": bool(os.getenv("TWILIO_ACCOUNT_SID")),
                       "ia_redacao": bool(os.getenv("ANTHROPIC_API_KEY"))}}


@public.get("/webhooks/whatsapp")
def whatsapp_verify(request: Request):
    """Verificação do webhook pela Meta (hub.challenge)."""
    q = request.query_params
    token = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
    if q.get("hub.mode") == "subscribe" and token and q.get("hub.verify_token") == token:
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403, "verificação negada")


@public.post("/webhooks/whatsapp", dependencies=[security.limiter_dependency(webhook_limiter)])
async def whatsapp_inbound(request: Request, tasks: BackgroundTasks):
    """Mensagens do WhatsApp. Valida X-Hub-Signature-256; responde 200 logo e processa depois (a Meta reenvia se demorar)."""
    raw = await request.body()
    secret = os.getenv("WHATSAPP_APP_SECRET", "")
    if secret:
        if not security.verify_meta_signature(raw, request.headers.get("x-hub-signature-256"), secret):
            raise HTTPException(401, "assinatura inválida")
    elif config.is_production():
        raise HTTPException(503, "WHATSAPP_APP_SECRET não configurado")
    try:
        payload = json.loads(raw or b"{}")
        msgs = webhooks.parse_meta_payload(payload)
        statuses = webhooks.parse_meta_statuses(payload)
    except (ValueError, TypeError):
        raise HTTPException(400, "corpo inválido")
    for mid, state, err in statuses:  # enviada, entregue, lida ou falhou: atualiza o registro da mensagem
        db.update_message_state_by_provider(mid, state, err)
    for m in msgs:
        tasks.add_task(webhooks.process_whatsapp, m)
    return {"recebidas": len(msgs), "status_atualizados": len(statuses)}


@public.post("/sms/inbound", dependencies=[security.limiter_dependency(webhook_limiter)])
async def sms_inbound(request: Request):
    """SMS recebido. Twilio (formulário, com X-Twilio-Signature; responde TwiML) ou JSON {from, body} (n8n, só sem Twilio).
    1 = recebido, 2 = ajuda."""
    ctype = request.headers.get("content-type", "")
    is_json = "json" in ctype
    d = await request.json() if is_json else dict(await request.form())
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if token and not is_json:
        url = config.public_base_url() + request.url.path
        if not security.verify_twilio_signature(url, {k: str(v) for k, v in d.items()}, request.headers.get("x-twilio-signature"), token):
            raise HTTPException(401, "assinatura inválida")
    elif config.is_production():  # em produção nada entra sem assinatura
        raise HTTPException(401, "assinatura obrigatória")
    phone = d.get("From") or d.get("from") or ""
    text = d.get("Body") or d.get("body") or ""
    if not phone:
        raise HTTPException(422, "campo From/from ausente")
    r = handle_message(phone, text, channel="sms")
    out = {"reply": r.text, "became_active": r.became_active, "producer_id": r.producer_id}
    texts = [r.text]
    for phone_to, text_to, channel_to in r.notify:  # convite ao sucessor
        deliver(r.producer_id, phone_to, channel_to, text_to, kind="convite", proactive=True)
    if r.became_active:
        out["messages"] = [m for m in analyze_producer(r.producer_id, full=True)["messages"] if m["kind"] == "report"]
        texts += [m["text"] for m in out["messages"]]
    if not is_json:
        return Response(webhooks.twiml(texts), media_type="application/xml")
    return out


_SEC = {"Cache-Control": "private, max-age=300", "X-Robots-Tag": "noindex, nofollow",
        "Content-Security-Policy": "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"}


def _load_report(token: str, request: Request) -> dict:
    if not report_limiter.check(security.client_ip(request)):
        raise HTTPException(429, "muitas requisições")
    data = db.get_report(token) if TOKEN_RE.match(token) else None
    if data is None:  # mesmo erro para "não existe" e "expirou": não revela nada
        raise HTTPException(404, "Link inválido ou expirado.")
    return data


@public.get("/r/{token}", response_class=HTMLResponse)
def report_page(token: str, request: Request):
    """Relatório detalhado: dados coletados, mapas, a conta da nota e o porquê de cada alerta."""
    data = _load_report(token, request)
    out = report.ensure_images(data)
    data["imagens"] = report.load_images_meta(out)
    return HTMLResponse(report.render_page(data, out, f"/r/{token}/img", inline=False, expires_at=data["_expires_at"]),
                        headers=_SEC)


@public.get("/h/{token}", response_class=HTMLResponse)
def history_page(token: str, request: Request):
    """Histórico dos avisos, SOMENTE LEITURA (feito para o sucessor): o que foi avisado, o porquê, a confiança e a data."""
    if not report_limiter.check(security.client_ip(request)):
        raise HTTPException(429, "muitas requisições")
    link = db.get_link(token, "history") if TOKEN_RE.match(token) else None
    if link is None:
        raise HTTPException(404, "Link inválido ou expirado.")
    items = db.list_messages(link["producer_id"], kind="alert", direction="out", limit=200)
    base = config.public_base_url()
    return HTMLResponse(report.render_history(items, base), headers=_SEC)


@public.get("/r/{token}/img/{name}")
def report_image(token: str, name: str, request: Request):
    data = _load_report(token, request)
    if not IMG_RE.match(name):
        raise HTTPException(404, "imagem não encontrada")
    f = report.report_dir(data["_producer_id"], token) / name
    if not f.exists():
        report.ensure_images(data)
    if not f.exists():
        raise HTTPException(404, "imagem não encontrada")
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": "private, max-age=3600", "X-Robots-Tag": "noindex"})


@public.get("/r/{token}/baixar")
def report_download(token: str, request: Request):
    """O mesmo relatório em UM arquivo .html (imagens dentro), para guardar ou mandar a um agrônomo."""
    data = _load_report(token, request)
    out = report.ensure_images(data)
    data["imagens"] = report.load_images_meta(out)
    html = report.render_page(data, out, "", inline=True, expires_at=data["_expires_at"])
    return HTMLResponse(html, headers={**_SEC, "Content-Disposition": 'attachment; filename="balk-relatorio.html"'})


# ------------------------------------------------------------------ internas (chave de API)
@internal.post("/conversation")
def conversation(body: ConversationIn):
    """Recebe a mensagem do canal (n8n WF1) e devolve a resposta."""
    return _conversation(body)


@internal.post("/ingest/producers")
async def ingest_producers(request: Request, analisar: bool = True):
    """JSON (lista ou {"producers": [...]}) ou CSV (text/csv) com telefone, lat, lon, cultura, data_plantio, canal, origem."""
    ctype = request.headers.get("content-type", "")
    raw = (await request.body()).decode("utf-8", errors="replace")
    if "json" in ctype:
        data = await request.json()
        rows = data.get("producers", [data]) if isinstance(data, dict) else data
        if isinstance(data, dict) and "csv" in data:
            rows = parse_csv_text(data["csv"])
    else:
        rows = parse_csv_text(raw)
    out = ingest_rows(rows)
    out["relatorios"] = []
    out["convites_enviados"] = 0
    for inv in out["optin_pendentes"]:  # cadastrados por cooperativa: convite de aceite (nada mais é enviado antes do SIM)
        try:
            ch = get_channel(inv["channel"])
            ch.send(inv["phone"], inv["text"], None, proactive=True)
            db.log_message(inv["producer_id"], inv["phone"], "out", inv["channel"], "optin", inv["text"], state="sent")
            out["convites_enviados"] += 1
        except Exception:  # noqa: BLE001
            log.exception("falha ao enviar convite")
    if analisar:
        for pid in out["ids_ativos"]:
            res = analyze_producer(pid, full=True)
            out["relatorios"].append({"producer_id": pid, "phone": res["phone"], "channel": res["channel"],
                                      "messages": res["messages"]})
    return out


@internal.get("/producers/active")
def producers_active():
    return [p.model_dump() for p in db.list_active()]


@internal.get("/producers")
def producers_all():
    return [p.model_dump() for p in db.list_all()]


@internal.delete("/producers/{pid}")
def producer_delete(pid: int):
    """LGPD: apaga o produtor e todos os dados dele."""
    if db.get_producer(pid) is None:
        raise HTTPException(404, "produtor não encontrado")
    return db.delete_producer(pid)


class PlotIn(BaseModel):
    producer_id: int
    name: str
    geometry: dict  # GeoJSON Polygon (ou Feature), EPSG:4326, [longitude, latitude]
    crop: Optional[str] = None
    planting_date: Optional[str] = None


@internal.post("/plots")
def plots_create(body: PlotIn):
    """Cadastra um talhão desenhado. A geometria é validada AQUI (válida, fechada, sem autointerseção, no Brasil, área mínima e
    máxima, sem sobreposição relevante, limites de quantidade): nunca se confia só no cliente. 422 traz a lista de erros."""
    from app import plots as plots_mod
    p = db.get_producer(body.producer_id)
    if p is None:
        raise HTTPException(404, "produtor não encontrado")
    others = [x["geojson"] for x in db.list_plots(p.id)]
    chk = plots_mod.check_plot_input(body.geometry, body.name, body.crop, body.planting_date, others)
    if chk["errors"]:
        raise HTTPException(422, {"erros": chk["errors"]})
    plot = db.create_plot(p.id, chk["name"], chk["geometry"], chk["area_ha"], chk["crop"], chk["planting_date"])
    poly = chk["poly"]
    if len(others) == 0:  # o ponto do produtor passa a ser o centro do primeiro talhão (usado no clima)
        db.update_producer(p.id, lat=poly.centroid.y, lon=poly.centroid.x, location_precision="ponto")
    return {"id": plot["id"], "nome": plot["name"], "area_ha": plot["area_ha"], "crop": chk["crop"]}


@internal.get("/producers/{pid}/plots")
def plots_list(pid: int):
    return [{k: v for k, v in x.items() if k != "geojson"} for x in db.list_plots(pid)]


@internal.delete("/plots/{plot_id}")
def plots_delete(plot_id: int, producer_id: int):
    if db.delete_plot(plot_id, producer_id) == 0:
        raise HTTPException(404, "talhão não encontrado para este produtor")
    return {"ok": True}


@internal.post("/analyze/{pid}")
def analyze_route(pid: int, full: bool = False, now: Optional[str] = None):
    try:
        return analyze_producer(pid, full=full, now=_now(now))
    except KeyError:
        raise HTTPException(404, "produtor não encontrado")


@internal.post("/alerts/log")
def alerts_log(body: AlertLogIn):
    db.log_alert(body.producer_id, body.type, body.sent_at)
    return {"ok": True}


@internal.post("/logistics/plan")
def logistics_plan(body: LogisticsIn):
    p = db.get_producer(body.producer_id)
    if not p:
        raise HTTPException(404, "produtor não encontrado")
    if body.destination_id:
        dest = next((d for d in load_destinations() if d["id"] == body.destination_id), None)
        if not dest:
            raise HTTPException(404, "destino não encontrado")
    elif body.lat is not None and body.lon is not None:
        dest = {"nome": "destino", "lat": body.lat, "lon": body.lon}
    else:
        raise HTTPException(422, "informe destination_id ou lat/lon")
    plan = plan_route(p, dest, _now(body.now))
    plan["text"] = render(plan, p.channel, p.lang)
    return plan


@internal.get("/cooperative/{coop_id}/forecast")
def cooperative_forecast(coop_id: str, now: Optional[str] = None):
    return coop_forecast(coop_id, _now(now))


@internal.post("/jobs/daily")
def jobs_daily():
    """O ciclo diário (o que o WF2 do n8n faz): analisa cada produtor ativo, envia e registra. Cron às 06:05.
    Produtor cuja análise falha (clima fora do ar etc.) é pulado e listado em `erros`: ninguém recebe alerta sem dado."""
    erros: list = []
    return {"enviados": run_daily(errors=erros), "erros": erros}


@internal.post("/jobs/purge")
def jobs_purge():
    return {"relatorios_apagados": db.purge_expired_reports(), "site": db_site.purge_expired()}


# ------------------------------------------------------------------ demonstração (fora de produção)
@demo.post("/simulate")
def simulate(body: ConversationIn):
    """Igual a /conversation, para o simulador web (sem canal real)."""
    return _conversation(body)


@demo.post("/simulate/daily")
def simulate_daily(hora: Optional[int] = 10):
    """Roda o que o WF2 faz às 06:05, mas na hora pedida (padrão 10h, fora do horário quieto)."""
    now = datetime.now().replace(hour=hora, minute=0, second=0, microsecond=0)
    return {"enviados": run_daily(now)}


# a rota que apaga o banco continua exigindo a chave
@demo.post("/simulate/reset", dependencies=[Depends(security.require_api_key)])
def simulate_reset():
    """Apaga tudo. Na demo pública exige a chave, para um avaliador não apagar a demo de outro."""
    db.reset_all()
    OUTBOX.clear()
    return {"ok": True}


@demo.get("/outbox")
def outbox():
    """O que o canal de console 'enviou' (só fora de produção): a demo lê o código de verificação e os relatórios daqui."""
    return OUTBOX[-50:]


@demo.get("/maps/{pid}.png")
def maps(pid: int):
    f = config.work_root() / str(pid) / "mapa.png"
    if not f.exists():
        raise HTTPException(404, "mapa ainda não gerado")
    return FileResponse(f, media_type="image/png")


@demo.get("/destinos")
def destinos():
    return load_destinations()


@demo.get("/pontos-demo")
def pontos_demo():
    return simulated.DEMO_POINTS


@demo.get("/producers")
def demo_producers():
    return [p.model_dump() for p in db.list_all()]


@demo.get("/cooperative/{coop_id}/forecast")
def demo_forecast(coop_id: str, now: Optional[str] = None):
    return coop_forecast(coop_id, _now(now))


@demo.post("/logistics/plan")
def demo_logistics(body: LogisticsIn):
    return logistics_plan(body)


WEB = ROOT / "web"


@public.get("/", include_in_schema=False)
def landing():
    """Página inicial do site (o simulador da demo fica em /demo/index.html, só fora de produção)."""
    return FileResponse(WEB / "index.html")


def _site_csp() -> str:
    """CSP das páginas do site: só scripts e estilos do próprio servidor; imagens do mapa só do provedor de tiles configurado."""
    from urllib.parse import urlparse
    hosts = {urlparse(x["url"].replace("{s}", "a")).netloc for x in config.map_tiles()["layers"]}
    tiles = " ".join(f"https://{h}" for h in sorted(hosts) if h)
    return ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            f"img-src 'self' data: blob: {tiles}; connect-src 'self' {tiles}; worker-src 'self' blob:; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def create_app() -> FastAPI:
    """Monta a aplicação conforme BALK_ENV. Em production recusa subir com pendências e não expõe simulador nem /docs."""
    prod = config.is_production()
    if prod and config.production_problems():
        raise RuntimeError("BALK_ENV=production com pendências: " + "; ".join(config.production_problems()))
    a = FastAPI(title="BALK", description="Orientação agronômica curta por WhatsApp e SMS", version="0.2.0",
                docs_url=None if prod else "/docs", redoc_url=None, openapi_url=None if prod else "/openapi.json")
    a.middleware("http")(observe)
    a.include_router(public)
    a.include_router(site_api.api)  # /api/*: cadastro com código, talhões, histórico (sessão por cookie)
    a.include_router(site_api.pages)  # /m/{token}: link de uso único do WhatsApp
    if not prod:
        # o simulador chama estas rotas sem chave (as versões "demo" vêm primeiro e têm o mesmo caminho das internas)
        a.include_router(demo)
        a.mount("/demo", StaticFiles(directory=str(ROOT / "demo"), html=True), name="demo")
    if config.is_demo() and config.demo_problems():
        raise RuntimeError("BALK_ENV=demo com pendências: " + "; ".join(config.demo_problems()))
    a.include_router(internal)
    a.mount("/app", StaticFiles(directory=str(WEB), html=True), name="app")  # páginas do site e bibliotecas do mapa (web/vendor)
    return a


app = create_app()
