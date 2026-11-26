"""FastAPI: só rotas finas. A lógica está nos módulos (testáveis); o n8n só chama estes endpoints.

MVP sem autenticação: proteger as rotas antes de qualquer uso real (há telefones no banco).
"""
import logging
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from app import config, db  # noqa: E402
from app.channels import OUTBOX  # noqa: E402
from app.data import simulated  # noqa: E402
from app.ingest.conversation import handle_message  # noqa: E402
from app.ingest.csv_import import ingest_rows, parse_csv_text  # noqa: E402
from app.logistics import load_destinations, plan_route  # noqa: E402
from app.logistics.forecast import coop_forecast  # noqa: E402
from app.message import render  # noqa: E402
from app.service import analyze_producer, run_daily  # noqa: E402

log = logging.getLogger("balk")
app = FastAPI(title="BALK", description="Orientação agronômica curta por WhatsApp e SMS (MVP)", version="0.1.0")
ROOT = config.ROOT


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


@app.get("/health")
def health():
    return {"ok": True, "data_mode": config.data_mode(), "engine": config.engine_name()}


def _conversation(body: ConversationIn) -> dict:
    loc = (body.lat, body.lon) if body.lat is not None and body.lon is not None else None
    reply = handle_message(body.phone, body.text, body.channel, location=loc, source=body.source)
    messages = [{"kind": "reply", "text": reply.text}]
    if reply.became_active:  # primeira análise ao virar ATIVO (M3 + M4), em segundos
        res = analyze_producer(reply.producer_id, full=True)
        messages += [m for m in res["messages"] if m["kind"] == "report"]
    return {"reply": reply.text, "became_active": reply.became_active, "producer_id": reply.producer_id,
            "messages": messages}


@app.post("/conversation")
def conversation(body: ConversationIn):
    """Recebe a mensagem do canal (n8n WF1) e devolve a resposta."""
    return _conversation(body)


@app.post("/simulate")
def simulate(body: ConversationIn):
    """Igual a /conversation, para o simulador web (sem canal real)."""
    return _conversation(body)


@app.post("/ingest/producers")
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
    if analisar:
        for pid in out["ids"]:
            res = analyze_producer(pid, full=True)
            out["relatorios"].append({"producer_id": pid, "phone": res["phone"], "channel": res["channel"],
                                      "messages": res["messages"]})
    return out


@app.get("/producers/active")
def producers_active():
    return [p.model_dump() for p in db.list_active()]


@app.get("/producers")
def producers_all():
    return [p.model_dump() for p in db.list_all()]


@app.post("/analyze/{pid}")
def analyze_route(pid: int, full: bool = False, now: Optional[str] = None):
    try:
        return analyze_producer(pid, full=full, now=_now(now))
    except KeyError:
        raise HTTPException(404, "produtor não encontrado")


@app.post("/alerts/log")
def alerts_log(body: AlertLogIn):
    db.log_alert(body.producer_id, body.type, body.sent_at)
    return {"ok": True}


@app.post("/logistics/plan")
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


@app.post("/sms/inbound")
async def sms_inbound(request: Request):
    """Provedor de SMS (Twilio: campos From e Body) ou JSON {from, body}. 1 = recebido, 2 = ajuda."""
    ctype = request.headers.get("content-type", "")
    if "json" in ctype:
        d = await request.json()
    else:
        d = dict(await request.form())
    phone = d.get("From") or d.get("from") or ""
    text = d.get("Body") or d.get("body") or ""
    if not phone:
        raise HTTPException(422, "campo From/from ausente")
    r = handle_message(phone, text, channel="sms")
    out = {"reply": r.text, "became_active": r.became_active, "producer_id": r.producer_id}
    if r.became_active:
        out["messages"] = [m for m in analyze_producer(r.producer_id, full=True)["messages"] if m["kind"] == "report"]
    return out


@app.get("/cooperative/{coop_id}/forecast")
def cooperative_forecast(coop_id: str, now: Optional[str] = None):
    return coop_forecast(coop_id, _now(now))


@app.post("/simulate/daily")
def simulate_daily(hora: Optional[int] = 10):
    """Roda o que o WF2 faz às 06:05, mas na hora pedida (padrão 10h, fora do horário quieto)."""
    now = datetime.now().replace(hour=hora, minute=0, second=0, microsecond=0)
    return {"enviados": run_daily(now)}


@app.post("/simulate/reset")
def simulate_reset():
    db.reset_all()
    OUTBOX.clear()
    return {"ok": True}


@app.get("/maps/{pid}.png")
def maps(pid: int):
    f = config.work_root() / str(pid) / "mapa.png"
    if not f.exists():
        raise HTTPException(404, "mapa ainda não gerado")
    return FileResponse(f, media_type="image/png")


@app.get("/destinos")
def destinos():
    return load_destinations()


@app.get("/pontos-demo")
def pontos_demo():
    return simulated.DEMO_POINTS


@app.get("/")
def index():
    return FileResponse(ROOT / "demo" / "index.html")


app.mount("/demo", StaticFiles(directory=str(ROOT / "demo")), name="demo")
