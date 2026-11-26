"""API do site (/api/*): cadastro com código de verificação, mapa para desenhar talhões, conta e histórico por safra.

A identidade é o número de WhatsApp verificado (app/auth.py). Toda rota de conta exige a sessão e só enxerga dados do
produtor da sessão (a propriedade é conferida em cada consulta). A geometria é validada AQUI, mesmo que o navegador já
tenha validado (Turf): nunca se confia só no cliente.
"""
import json
import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from app import auth, config, db, db_site, plots as plots_mod, security
from app.data import geocode as geo
from app.delivery import deliver
from app.models import Producer

log = logging.getLogger("balk.site")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
INVITES_PER_DAY = 3
REPORTS_PER_DAY = 3
invite_limiter = security.RateLimiter(INVITES_PER_DAY, 86400)  # por produtor
report_limiter_site = security.RateLimiter(REPORTS_PER_DAY, 86400)  # por produtor
api = APIRouter(prefix="/api")
pages = APIRouter()
signup_limiter = security.RateLimiter(20, 3600)  # por IP: pedidos de código (além dos limites por telefone, em auth.py)
verify_limiter = security.RateLimiter(30, 600)
geocode_limiter = security.RateLimiter(60, 60)
link_limiter = security.RateLimiter(30, 60)


def _session(request: Request) -> dict:
    return auth.require_session(request)


Session = Depends(_session)


def _producer(s: dict) -> Producer:
    p = db.get_producer(s["producer_id"])
    if p is None:
        raise HTTPException(401, "Conta não encontrada.")
    return p


def _plot_out(x: dict) -> dict:
    return {"id": x["id"], "name": x["name"], "area_ha": x["area_ha"], "crop": x["crop"], "planting_date": x["planting_date"],
            "geometry": x["geojson"]}


# ------------------------------------------------------------------ públicas
@api.get("/config")
def site_config():
    """Tudo que a tela precisa saber antes do login: textos de consentimento (com versão), fundo do mapa, limites, culturas."""
    from app.ingest.conversation import crop_names
    c = config.consent()
    return {"consentimento": {"versao": c["versao"], "dados_localizacao": c["finalidades"]["dados_localizacao"],
                              "mensagens": c["finalidades"]["mensagens"], "status": c.get("status", "")},
            "mapa": config.map_tiles(), "limites": plots_mod.limits(), "culturas": crop_names(),
            "brasil_bbox": plots_mod.BRASIL_BBOX}


class SignupStart(BaseModel):
    name: str = Field("", max_length=80)
    phone: str = Field(..., max_length=30)
    consent_dados: bool = False
    consent_mensagens: bool = False


class SignupVerify(BaseModel):
    phone: str = Field(..., max_length=30)
    code: str = Field(..., max_length=12)


@api.post("/signup/start")
def signup_start(body: SignupStart, request: Request):
    """Passo 1: nome, telefone e OS DOIS consentimentos (marcados separadamente). Manda o código de 6 dígitos pelo WhatsApp."""
    if not (body.consent_dados and body.consent_mensagens):
        raise HTTPException(422, "Para continuar, aceite os dois itens: o uso do telefone e da localização, e o recebimento dos avisos.")
    ip = security.client_ip(request)
    if not signup_limiter.check(ip):
        raise HTTPException(429, "Muitos pedidos deste acesso. Tente de novo mais tarde.")
    try:
        return auth.start_signup(body.phone, body.name, ["dados_localizacao", "mensagens"], ip)
    except auth.AuthError as e:
        raise HTTPException(e.status, e.message)


@api.post("/signup/verify")
def signup_verify(body: SignupVerify, request: Request, response: Response):
    """Passo 2: confere o código. Cria (ou reabre) a conta, grava os consentimentos e abre a sessão."""
    if not verify_limiter.check(security.client_ip(request)):
        raise HTTPException(429, "Muitas tentativas. Aguarde alguns minutos.")
    try:
        v = auth.verify_signup(body.phone, body.code)
    except auth.AuthError as e:
        raise HTTPException(e.status, e.message)
    phone = db.norm_phone(body.phone)
    if db.get_contact_by_phone(phone) and not db.get_producer_by_phone(phone):
        raise HTTPException(409, "Este número já recebe os avisos de outra pessoa.")
    name = v["name"] or None
    p = db.get_producer_by_phone(phone)
    if p is None:
        p = db.create_producer(Producer(phone=phone, channel="whatsapp", source="site", consent=True, active=True,
                                        state="AGUARDA_TALHAO", name=name, location_precision="ponto"))
    else:
        state = "ATIVO" if db.list_plots(p.id) else "AGUARDA_TALHAO"
        p = db.update_producer(p.id, consent=True, active=True, state=state, **({"name": name} if name else {}))
    if not (db.has_consent(phone, "mensagens") and db.has_consent(phone, "dados_localizacao")):
        db.record_consents(phone, p.id, json.loads(v["consents_json"]), v["text_version"], "site")
    auth.open_session(response, p.id)
    return {"ok": True, "estado": p.state, "talhoes": len(db.list_plots(p.id))}


@pages.get("/m/{token}", response_class=HTMLResponse)
def magic_page(token: str, request: Request):
    """Página intermediária do link do WhatsApp. O GET NÃO consome o link (robôs de pré-visualização do WhatsApp também fazem
    GET); quem consome é o POST, que só o navegador de verdade faz (o script abre sozinho; há também um botão)."""
    if not link_limiter.check(security.client_ip(request)):
        raise HTTPException(429, "muitas requisições")
    if not TOKEN_RE.match(token):  # nada vindo da URL entra no HTML
        raise HTTPException(404, "Link inválido, já usado ou expirado. Peça outro escrevendo MAPA no WhatsApp.")
    html = ('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex"><title>BALK: abrir o mapa</title>'
            '<link rel="stylesheet" href="/app/css/site.css"><body class="center"><main class="card">'
            '<h1>BALK</h1><p>Toque para abrir o mapa da sua lavoura.</p>'
            '<form method="post"><button class="btn" type="submit">Abrir o mapa</button></form>'  # sem action: posta para a própria URL
            '<script src="/app/js/auto-submit.js"></script></main></body></html>')
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


@pages.post("/m/{token}")
def magic_consume(token: str, request: Request):
    if not link_limiter.check(security.client_ip(request)):
        raise HTTPException(429, "muitas requisições")
    if not auth.same_origin(request):  # contra "login CSRF": outro site não pode logar a vítima na conta do atacante
        raise HTTPException(403, "Origem não permitida.")
    link = db_site.consume_magic_link(token) if TOKEN_RE.match(token) else None
    if link is None or db.get_producer(link["producer_id"]) is None:
        raise HTTPException(404, "Link inválido, já usado ou expirado. Peça outro escrevendo MAPA no WhatsApp.")
    resp = RedirectResponse("/app/mapa.html", status_code=303)
    auth.open_session(resp, link["producer_id"])
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ------------------------------------------------------------------ da conta (sessão)
class MeIn(BaseModel):
    name: Optional[str] = Field(None, max_length=80)
    farm_name: Optional[str] = Field(None, max_length=80)
    delivery_name: Optional[str] = Field(None, max_length=80)
    delivery_lat: Optional[float] = Field(None, ge=-34.0, le=5.5)
    delivery_lon: Optional[float] = Field(None, ge=-74.5, le=-34.0)


def _me(p: Producer) -> dict:
    farm = db_site.get_farm(p.id)
    return {"id": p.id, "name": p.name, "phone_final": p.phone[-4:], "state": p.state, "channel": p.channel,
            "farm": {"name": farm["name"], "delivery_name": farm["delivery_name"], "delivery_lat": farm["delivery_lat"],
                     "delivery_lon": farm["delivery_lon"]},
            "plots": len(db.list_plots(p.id)),
            "contacts": [{"phone_final": c["phone"][-4:], "phone": c["phone"], "state": c["state"]} for c in db.list_contacts(p.id)
                         if c["state"] != "SAIU"]}


@api.get("/me")
def me_get(s: dict = Session):
    return _me(_producer(s))


@api.put("/me")
def me_put(body: MeIn, s: dict = Session):
    p = _producer(s)
    if body.name is not None:
        p = db.update_producer(p.id, name=body.name.strip() or None)
    if (body.delivery_lat is None) != (body.delivery_lon is None):
        raise HTTPException(422, "Informe latitude e longitude do ponto de entrega juntas.")
    farm = db_site.get_farm(p.id)
    db_site.save_farm(p.id, name=body.farm_name if body.farm_name is not None else farm["name"],
                      delivery_name=body.delivery_name if body.delivery_name is not None else farm["delivery_name"],
                      delivery_lat=body.delivery_lat if body.delivery_lat is not None else farm["delivery_lat"],
                      delivery_lon=body.delivery_lon if body.delivery_lon is not None else farm["delivery_lon"])
    return _me(p)


@api.get("/geocode")
def geocode_search(q: str, request: Request, s: dict = Session):
    """Busca por município ou endereço para o mapa centrar. O GPS do aparelho só centra o mapa; nunca define os limites."""
    if not geocode_limiter.check(security.client_ip(request)):
        raise HTTPException(429, "Muitas buscas. Aguarde um instante.")
    return {"resultados": geo.search(q)}


# ---- talhões
class PlotBody(BaseModel):
    name: str = Field(..., max_length=60)
    geometry: dict
    crop: Optional[str] = Field(None, max_length=40)
    planting_date: Optional[str] = Field(None, max_length=12)


@api.get("/plots")
def plots_get(s: dict = Session):
    return {"talhoes": [_plot_out(x) for x in db.list_plots(s["producer_id"])]}


@api.post("/plots")
def plots_post(body: PlotBody, s: dict = Session):
    pid = s["producer_id"]
    others = [x["geojson"] for x in db.list_plots(pid)]
    chk = plots_mod.check_plot_input(body.geometry, body.name, body.crop, body.planting_date, others)
    if chk["errors"]:
        raise HTTPException(422, {"erros": chk["errors"]})
    plot = db.create_plot(pid, chk["name"], chk["geometry"], chk["area_ha"], chk["crop"], chk["planting_date"])
    return _plot_out(plot)


@api.put("/plots/{plot_id}")
def plots_put(plot_id: int, body: PlotBody, s: dict = Session):
    pid = s["producer_id"]
    if db.get_plot(plot_id, pid) is None:
        raise HTTPException(404, "Talhão não encontrado.")
    others = [x["geojson"] for x in db.list_plots(pid) if x["id"] != plot_id]  # não se sobrepõe a si mesmo
    chk = plots_mod.check_plot_input(body.geometry, body.name, body.crop, body.planting_date, others)
    if chk["errors"]:
        raise HTTPException(422, {"erros": chk["errors"]})
    plot = db.update_plot(plot_id, pid, name=chk["name"], geojson=chk["geometry"], area_ha=chk["area_ha"], crop=chk["crop"],
                          planting_date=chk["planting_date"])
    return _plot_out(plot)


@api.delete("/plots/{plot_id}")
def plots_delete(plot_id: int, s: dict = Session):
    if db.delete_plot(plot_id, s["producer_id"]) == 0:
        raise HTTPException(404, "Talhão não encontrado.")
    return {"ok": True}


class FinishIn(BaseModel):
    enviar_relatorio: bool = False


def _first_reports(pid: int) -> None:
    from app.service import send_first_reports
    try:
        send_first_reports(pid)
    except Exception:  # noqa: BLE001  (clima fora do ar: o cadastro vale e o relatório vem no próximo ciclo)
        log.exception("primeira análise falhou (produtor %s)", pid)
        p = db.get_producer(pid)
        if p:
            deliver(p.id, p.phone, p.channel, "Seu cadastro está pronto. Tive um problema para buscar os dados agora; "
                    "aviso assim que conseguir.", kind="reply", proactive=True)


@api.post("/finish")
def finish(body: FinishIn, tasks: BackgroundTasks, s: dict = Session):
    """Conclui o cadastro: precisa de ao menos 1 talhão. Passa a ATIVO e manda o primeiro relatório de CADA talhão."""
    p = _producer(s)
    plots = db.list_plots(p.id)
    if not plots:
        raise HTTPException(422, "Desenhe pelo menos um talhão no mapa antes de concluir.")
    if not (db.has_consent(p.phone, "mensagens") and db.has_consent(p.phone, "dados_localizacao")):
        raise HTTPException(403, "Falta o seu aceite. Refaça o cadastro pelo número de WhatsApp.")
    c = __import__("shapely.geometry", fromlist=["shape"]).shape(plots[0]["geojson"]).centroid  # o maior talhão fixa o ponto
    first = p.state != "ATIVO"
    db.update_producer(p.id, lat=c.y, lon=c.x, location_precision="ponto", state="ATIVO", active=True, consent=True,
                       crop=plots[0]["crop"] or p.crop, planting_date=plots[0]["planting_date"] or p.planting_date)
    send = first or body.enviar_relatorio
    if send and not report_limiter_site.check(f"p{p.id}"):  # cada relatório consulta clima e satélite e manda mensagem
        raise HTTPException(429, f"No máximo {REPORTS_PER_DAY} envios de relatório por dia.")
    if send:
        tasks.add_task(_first_reports, p.id)
    return {"ok": True, "talhoes": len(plots), "relatorio_a_caminho": send}


# ---- histórico por safra
@api.get("/history")
def history(s: dict = Session):
    pid = s["producer_id"]
    alerts = [{"type": m["type"], "text": m["content"][:400], "at": m["created_at"], "confidence": m.get("confidence")}
              for m in db.list_messages(pid, kind="alert", direction="out", limit=100)]
    return {"safras": db_site.seasons_overview(pid), "avisos": alerts}


class YieldIn(BaseModel):
    yield_t_ha: float = Field(..., gt=0, le=150)
    notes: Optional[str] = Field(None, max_length=200)


@api.post("/seasons/{season_id}/close")
def season_close(season_id: int, body: YieldIn, s: dict = Session):
    """Fecha a safra com a produtividade informada pelo produtor (t/ha). Só a safra dele."""
    if not db_site.close_season(season_id, s["producer_id"], body.yield_t_ha, notes=body.notes):
        raise HTTPException(404, "Safra não encontrada.")
    return {"ok": True}


# ---- segundo contato, saída, exportação e exclusão
class ContactIn(BaseModel):
    phone: str = Field(..., max_length=30)


@api.post("/contacts")
def contact_add(body: ContactIn, s: dict = Session):
    """Convida um segundo contato (sucessor). Ele só recebe depois de responder SIM; nunca altera dados."""
    from app.ingest.conversation import SUCCESSOR_ASKED, _active_reply
    p = _producer(s)
    digits = "".join(c for c in body.phone if c.isdigit())
    if len(digits) < 10 or digits == "".join(c for c in p.phone if c.isdigit()):
        raise HTTPException(422, "Não entendi o número. Escreva com DDD, só números.")
    other = db.get_contact_by_phone(digits)
    if db.get_producer_by_phone(digits) or (other and other["producer_id"] != p.id):
        return {"ok": True, "mensagem": SUCCESSOR_ASKED}  # resposta igual à de sucesso, sem enviar: não revela quem já usa o BALK
    if not invite_limiter.check(f"p{p.id}"):
        raise HTTPException(429, f"No máximo {INVITES_PER_DAY} convites por dia.")
    r = _active_reply(p, "sucessor", body.phone)
    if not r.notify:
        raise HTTPException(422, r.text)
    for phone, text, channel in r.notify:
        deliver(p.id, phone, channel, text, kind="convite", proactive=True, purpose="invite")
    return {"ok": True, "mensagem": r.text}


@api.delete("/contacts/{phone}")
def contact_remove(phone: str, s: dict = Session):
    if not db.remove_contact(s["producer_id"], phone):
        raise HTTPException(404, "Contato não encontrado.")
    return {"ok": True}


@api.post("/logout")
def logout(request: Request, response: Response, s: dict = Session):
    db_site.revoke_session(s["token"])
    auth.clear_session_cookie(response)
    return {"ok": True}


@api.post("/optout")
def optout(response: Response, s: dict = Session):
    """Parar de receber: revoga os consentimentos, encerra todas as sessões. Os dados ficam até o produtor pedir a exclusão."""
    p = _producer(s)
    db.update_producer(p.id, active=False, consent=False, state="SAIU")
    db.revoke_consents(p.phone)
    db_site.revoke_all_sessions(p.id)
    auth.clear_session_cookie(response)
    return {"ok": True}


@api.get("/export")
def export(s: dict = Session):
    """LGPD: tudo que guardamos do produtor, em JSON (o mesmo do comando export-producer)."""
    p = _producer(s)
    out = {"produtor": p.model_dump(), "propriedade": db_site.get_farm(p.id), "consentimentos": db.list_consents(p.phone),
           "talhoes": [_plot_out(x) for x in db.list_plots(p.id)], "safras": db_site.seasons_overview(p.id),
           "contatos_sucessor": db.list_contacts(p.id), "alertas_enviados": db.get_alert_log(p.id),
           "mensagens_enviadas": [{k: v for k, v in m.items() if k != "report_token"} for m in db.list_messages(p.id, limit=1000)],
           "exportado_em": datetime.now().isoformat(timespec="seconds")}
    return JSONResponse(out, headers={"Content-Disposition": 'attachment; filename="balk-meus-dados.json"', "Cache-Control": "no-store"})


class DeleteIn(BaseModel):
    confirmar: bool = False


@api.delete("/me")
def me_delete(body: DeleteIn, response: Response, s: dict = Session):
    """Apaga a conta e TUDO (talhões, safras, relatórios, mensagens, consentimentos). Sem volta; exige confirmação explícita."""
    if not body.confirmar:
        raise HTTPException(422, "Confirme a exclusão: isso apaga todos os seus dados e não tem volta.")
    counts = db.delete_producer(s["producer_id"])
    auth.clear_session_cookie(response)
    return {"ok": True, "apagado": counts}
