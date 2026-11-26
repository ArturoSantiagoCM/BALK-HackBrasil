"""M1: máquina de estados do cadastro. INICIO -> PEDE_LOCAL -> PEDE_CULTURA -> PEDE_PLANTIO -> ATIVO.

Canal SMS: mensagem única "BALK soja 20/10 Sorriso MT" (estado extra AGUARDA_SIM para o consentimento).
"""
import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from app import config, db
from app.data.geocode import geocode
from app.models import Producer

CONSENT = config.consent()["texto_pt"]  # textos e versão em consent.yaml (v0 provisório)
PURPOSES = ["dados_localizacao", "mensagens"]
HIST_LABEL = "Histórico dos avisos (só leitura)"
SUCCESSOR_ONLY_READS = "Só o produtor altera dados. Você pode pedir HISTORICO ou responder SAIR para parar de receber."
SUCCESSOR_OK = "Pronto, você vai receber os avisos desta propriedade. Responda HISTORICO para ver o que já foi enviado."
SUCCESSOR_ASKED = "Enviei o convite. Quando a pessoa responder SIM, ela passa a receber os avisos."
SUCCESSOR_BAD = "Não entendi o número. Escreva assim: SUCESSOR 5565999990000 (com DDD)."
ASK_LOCAL = "Obrigado! Envie o pin de localização da sua lavoura (ou escreva lat,lon, ou o nome do município)."
ASK_LOCAL_AGAIN = "Não consegui entender o local. Envie o pin de localização, lat,lon (ex.: -12.54,-55.72) ou o município."
ASK_CROP = "Qual cultura você planta? Responda: soja, milho, café, feijão, hortaliça ou 'não sei'."
ASK_CROP_AGAIN = "Não reconheci a cultura. Responda: soja, milho, café, feijão, hortaliça ou 'não sei'."
ASK_DATE = "Quando plantou? Envie a data (dd/mm ou AAAA-MM-DD) ou 'não sei'."
ASK_DATE_AGAIN = "Data inválida ou no futuro. Envie dd/mm ou AAAA-MM-DD, ou 'não sei'."
DONE = "Cadastro pronto! Vou analisar sua área e já envio o primeiro relatório."
MUNI_NOTE = ("Atenção: pelo município eu só consigo enviar alertas de clima. "
             "Para a análise da lavoura, envie depois o pin de localização.")
BYE = "Tudo bem, não vou mais enviar mensagens. Para voltar, escreva qualquer coisa."
ACK = "Registrado, obrigado."
HELP_ESCALATE = "Certo, vou chamar um agrônomo da equipe para falar com você."
IDLE = "Estou acompanhando sua área. Responda SAIR para parar."
SMS_CONSENT = config.consent()["texto_sms"]
SMS_OK = "BALK: cadastro ok. Voce recebera alertas de clima por SMS. Para analise da lavoura envie o pin pelo WhatsApp."
SMS_HELP = "BALK: envie assim: BALK soja 20/10 Sorriso MT (cultura, data do plantio, municipio e UF)."

LAT_RANGE, LON_RANGE = (-56.0, 72.0), (-170.0, -30.0)  # Américas


@dataclass
class Reply:
    text: str
    became_active: bool = False
    producer_id: Optional[int] = None
    notify: list = field(default_factory=list)  # [(telefone, texto, canal)]: mensagens para OUTRAS pessoas (convite do sucessor)


def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()


def crop_names() -> list[str]:
    return list(config.crops_cfg()["culturas"].keys())


def match_crop(text: str, cutoff: float = 0.7) -> Optional[str]:
    """Cultura da lista (aceita acento e erro de digitação). None se não achar."""
    t = norm(text)
    if t in crop_names():
        return t
    m = difflib.get_close_matches(t, crop_names(), n=1, cutoff=cutoff)
    return m[0] if m else None


def parse_date(text: str, today: Optional[date] = None) -> str:
    """'dd/mm', 'dd/mm/aaaa' ou 'AAAA-MM-DD' -> 'AAAA-MM-DD'. Levanta ValueError se inválida ou no futuro."""
    today = today or date.today()
    t = text.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        d = date.fromisoformat(t)
    else:
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?", t)
        if not m:
            raise ValueError("formato de data")
        day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
        if year:
            y = int(year) + (2000 if len(year) == 2 else 0)
            d = date(y, month, day)
        else:
            d = date(today.year, month, day)
            if d > today:
                d = date(today.year - 1, month, day)  # sem ano: a última ocorrência passada
    if d > today:
        raise ValueError("data no futuro")
    return d.isoformat()


def valid_coords(lat: float, lon: float) -> bool:
    return LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]


def parse_sms(text: str) -> dict:
    """'BALK soja 20/10 Sorriso MT' -> {crop, date, municipio, uf, missing: [...]}. Aceita erro de digitação."""
    tokens = text.strip().split()
    if tokens and difflib.SequenceMatcher(None, norm(tokens[0]), "balk").ratio() >= 0.7:
        tokens = tokens[1:]
    out = {"crop": None, "date": None, "municipio": None, "uf": None}
    rest = []
    for tok in tokens:
        if out["date"] is None and re.fullmatch(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?", tok):
            out["date"] = tok
        elif out["crop"] is None and match_crop(tok):
            out["crop"] = match_crop(tok)
        else:
            rest.append(tok)
    if rest and re.fullmatch(r"[A-Za-z]{2}", rest[-1]) and len(rest) > 1:
        out["uf"] = rest.pop().upper()
    out["municipio"] = " ".join(rest) or None
    names = {"crop": "cultura", "date": "data", "municipio": "municipio"}
    out["missing"] = [names[k] for k in ("crop", "date", "municipio") if not out[k]]
    return out


def _parse_latlon(text: str) -> Optional[tuple[float, float]]:
    m = re.fullmatch(r"\s*(-?\d+(?:[.,]\d+)?)\s*[,; ]\s*(-?\d+(?:[.,]\d+)?)\s*", text.replace("°", ""))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
    except ValueError:
        return None


def _start(phone: str, channel: str, source: str) -> Producer:
    p = db.get_producer_by_phone(phone)
    if p is None:
        return db.create_producer(Producer(phone=phone, channel=channel, source=source))
    return db.update_producer(p.id, active=True, consent=False, state="INICIO", channel=channel)


def _history_link(producer_id: int) -> str:
    token = db.create_link(producer_id, "history", config.report_ttl_days())
    return f"{config.public_base_url()}/h/{token}"


def grant(phone: str, producer_id: Optional[int], origin: str) -> None:
    """Grava os consentimentos (finalidade, versão do texto, origem, data) de quem aceitou."""
    db.record_consents(phone, producer_id, PURPOSES, config.consent()["versao"], origin)


def _active_reply(p: Producer, t: str, raw: str = "") -> Reply:
    if t == "1":
        return Reply(ACK, producer_id=p.id)
    if t == "2":
        db.add_escalation(p.id, p.phone, "produtor pediu ajuda (resposta 2)")
        return Reply(HELP_ESCALATE, producer_id=p.id)
    if t.startswith("historico"):
        return Reply(f"{HIST_LABEL}: {_history_link(p.id)}", producer_id=p.id)
    if t.startswith("sucessor"):  # "SUCESSOR 5565999990000": convida o segundo contato (ele precisa aceitar por conta própria)
        digits = "".join(c for c in raw if c.isdigit())
        if len(digits) < 10 or digits == "".join(c for c in p.phone if c.isdigit()):
            return Reply(SUCCESSOR_BAD, producer_id=p.id)
        phone = db.norm_phone(digits)
        if db.get_producer_by_phone(phone):
            return Reply("Esse número já tem cadastro próprio no BALK.", producer_id=p.id)
        db.add_contact(p.id, phone)
        invite = config.consent()["texto_sucessor"].format(nome=f"o produtor do número terminado em {p.phone[-4:]}")
        return Reply(SUCCESSOR_ASKED, producer_id=p.id, notify=[(phone, invite, p.channel)])
    if t.startswith("mapa"):
        return Reply(map_reply(p), producer_id=p.id)
    if t.startswith("produtividade"):
        return _yield_reply(p, raw)
    return Reply(IDLE, producer_id=p.id)


MAP_LABEL = "Abra o mapa para desenhar ou ajustar seus talhões (o link vale por 30 minutos e só abre uma vez)"
WAIT_PLOT = "Falta pouco: desenhe os limites da sua lavoura no mapa para eu começar a análise"


def map_reply(p: Producer, waiting: bool = False) -> str:
    from app import auth
    return f"{WAIT_PLOT if waiting else MAP_LABEL}: {auth.map_link(p.id)}"


def _parse_yield(raw: str) -> tuple[Optional[float], str]:
    """'PRODUTIVIDADE 3,4 Talhão Norte' -> (3.4, 'talhao norte'). (None, ...) se não houver número válido."""
    m = re.match(r"\s*produtividade\s+(\d+(?:[.,]\d+)?)\s*(?:t/?ha|ton\w*|sc\w*)?\s*(.*)$", raw, re.I | re.S)
    if not m:
        return None, ""
    v = float(m.group(1).replace(",", "."))
    return (v if 0 < v <= 150 else None), norm(m.group(2))


def _yield_reply(p: Producer, raw: str) -> Reply:
    """Fecha a safra aberta com a produtividade informada (t/ha). Com mais de um talhão, o nome diz qual."""
    from app import db_site
    value, wanted = _parse_yield(raw)
    if value is None:
        return Reply("Não entendi. Escreva assim: PRODUTIVIDADE 3,4 (toneladas por hectare) e, se tiver mais de um talhão, o nome dele.",
                     producer_id=p.id)
    seasons = db_site.open_seasons(p.id)
    if not seasons:
        return Reply("Não há safra aberta para registrar. Ela abre sozinha quando o talhão tem cultura e data de plantio.", producer_id=p.id)
    names = {x["id"]: x["name"] for x in db.list_plots(p.id)}
    if len(seasons) > 1:
        match = [s for s in seasons if wanted and wanted in norm(names.get(s["plot_id"], ""))]
        if len(match) != 1:
            lista = ", ".join(names.get(s["plot_id"], "lavoura") for s in seasons)
            return Reply(f"Qual talhão? Escreva PRODUTIVIDADE {str(value).replace('.', ',')} e o nome: {lista}.", producer_id=p.id)
        seasons = match
    s = seasons[0]
    db_site.close_season(s["id"], p.id, value)
    return Reply(f"Registrado: {names.get(s['plot_id'], 'lavoura')} fechou a safra de {s['crop']} com "
                 f"{str(value).replace('.', ',')} t/ha. Obrigado, isso melhora os próximos avisos.", producer_id=p.id)


def _handle_contact(c: dict, phone: str, t: str) -> Reply:
    """Sucessor: aceita ou recusa por conta própria; depois só LÊ (histórico) e pode sair. Nunca altera dados."""
    pid = c["producer_id"]
    if t == "sair":
        db.set_contact_state(phone, "SAIU")
        db.revoke_consents(phone)
        return Reply(BYE, producer_id=pid)
    if c["state"] == "AGUARDA_SIM":
        if t == "sim":
            db.set_contact_state(phone, "ATIVO")
            grant(phone, pid, "sucessor")
            return Reply(SUCCESSOR_OK, producer_id=pid)
        return Reply(config.consent()["texto_sucessor"].format(nome="o produtor"), producer_id=pid)
    if c["state"] == "ATIVO" and t.startswith("historico"):
        return Reply(f"{HIST_LABEL}: {_history_link(pid)}", producer_id=pid)
    return Reply(SUCCESSOR_ONLY_READS, producer_id=pid)


def handle_message(phone: str, text: str, channel: str = "whatsapp", location: Optional[tuple[float, float]] = None,
                   today: Optional[date] = None, source: str = "direto") -> Reply:
    """Uma mensagem recebida: lê o estado, valida a entrada, grava e devolve a próxima pergunta."""
    if channel == "sms":
        return handle_sms(phone, text, today, source)
    t = norm(text)
    p = db.get_producer_by_phone(phone)
    if p is None and (c := db.get_contact_by_phone(phone)):  # o número é de um sucessor: papel diferente, poder menor
        return _handle_contact(c, phone, t)
    if t == "sair":
        if p:
            db.update_producer(p.id, active=False, consent=False, state="SAIU")
        db.revoke_consents(phone)
        return Reply(BYE, producer_id=p.id if p else None)
    if p is None or p.state == "SAIU":
        p = _start(phone, channel, source)
        return Reply(CONSENT, producer_id=p.id)

    if p.state == "AGUARDA_TALHAO":  # verificou o número no site e ainda não desenhou a lavoura
        return Reply(map_reply(p, waiting=True), producer_id=p.id)

    if p.state == "AGUARDA_SIM":  # cadastrado por cooperativa/CSV: só vira ativo quando a própria pessoa aceita
        if t == "sim":
            db.update_producer(p.id, consent=True, active=True, state="ATIVO")
            grant(phone, p.id, f"optin:{p.source}")
            return Reply(DONE, became_active=True, producer_id=p.id)
        return Reply(optin_text(p.source), producer_id=p.id)

    if p.state == "INICIO":
        if t == "sim":
            db.update_producer(p.id, consent=True, state="PEDE_LOCAL")
            grant(phone, p.id, channel)
            return Reply(ASK_LOCAL, producer_id=p.id)
        return Reply(CONSENT, producer_id=p.id)

    if p.state == "PEDE_LOCAL":
        pos, precision = location or _parse_latlon(text), "ponto"
        if pos is None and text.strip():
            pos, precision = geocode(text.strip()), "municipio"
        if pos is None or not valid_coords(*pos):
            return Reply(ASK_LOCAL_AGAIN, producer_id=p.id)
        db.update_producer(p.id, lat=pos[0], lon=pos[1], location_precision=precision, state="PEDE_CULTURA")
        return Reply((MUNI_NOTE + " " if precision == "municipio" else "") + ASK_CROP, producer_id=p.id)

    if p.state == "PEDE_CULTURA":
        if norm(text) in ("nao sei", "nao", "ns", "n sei"):
            crop = None
        else:
            crop = match_crop(text)
            if crop is None:
                return Reply(ASK_CROP_AGAIN, producer_id=p.id)
        db.update_producer(p.id, crop=crop, state="PEDE_PLANTIO")
        return Reply(ASK_DATE, producer_id=p.id)

    if p.state == "PEDE_PLANTIO":
        if norm(text) in ("nao sei", "nao", "ns", "n sei"):
            planting = None
        else:
            try:
                planting = parse_date(text, today)
            except ValueError:
                return Reply(ASK_DATE_AGAIN, producer_id=p.id)
        db.update_producer(p.id, planting_date=planting, state="ATIVO")
        return Reply(DONE, became_active=True, producer_id=p.id)

    return _active_reply(p, t, text)


def optin_text(origin: str, sms: bool = False) -> str:
    """Convite de quem foi cadastrado por uma cooperativa. Sem resposta SIM nada é enviado."""
    if sms:
        return f"BALK: a {origin} cadastrou voce para receber alertas de clima e lavoura. Responda SIM para aceitar ou SAIR."
    return (f"Olá, sou o BALK. A {origin} cadastrou você para receber avisos curtos de clima e lavoura da sua propriedade. "
            "Responda SIM para aceitar ou SAIR para não receber.")


def handle_sms(phone: str, text: str, today: Optional[date] = None, source: str = "direto") -> Reply:
    t = norm(text)
    p = db.get_producer_by_phone(phone)
    if p is None and (c := db.get_contact_by_phone(phone)):
        return _handle_contact(c, phone, t)
    if t == "sair":
        if p:
            db.update_producer(p.id, active=False, consent=False, state="SAIU")
        db.revoke_consents(phone)
        return Reply("BALK: cadastro cancelado. Nao enviaremos mais mensagens.", producer_id=p.id if p else None)
    if p and p.state == "AGUARDA_SIM":
        if t == "sim":
            db.update_producer(p.id, consent=True, active=True, state="ATIVO")
            grant(phone, p.id, "sms" if p.source == "direto" else f"optin:{p.source}")
            return Reply(SMS_OK, became_active=True, producer_id=p.id)
        return Reply(SMS_CONSENT if p.source == "direto" else optin_text(p.source, sms=True), producer_id=p.id)
    if p and p.state == "ATIVO" and (t in ("1", "2") or t.startswith(("historico", "sucessor", "mapa", "produtividade"))):
        return _active_reply(p, t, text)
    if t.startswith("balk") or difflib.SequenceMatcher(None, t.split()[0] if t else "", "balk").ratio() >= 0.75:
        d = parse_sms(text)
        if d["missing"]:
            return Reply(f"BALK: faltou {', '.join(d['missing'])}. Envie: BALK soja 20/10 Sorriso MT", producer_id=p.id if p else None)
        try:
            planting = parse_date(d["date"], today)
        except ValueError:
            return Reply("BALK: data invalida. Use dd/mm, ex.: 20/10.", producer_id=p.id if p else None)
        pos = geocode(d["municipio"], d["uf"])
        if pos is None:
            return Reply("BALK: nao achei o municipio. Reenvie com o nome correto.", producer_id=p.id if p else None)
        if p is None:
            p = db.create_producer(Producer(phone=phone, channel="sms", source=source))
        p = db.update_producer(p.id, lat=pos[0], lon=pos[1], location_precision="municipio", crop=d["crop"],
                               planting_date=planting, channel="sms", consent=False, active=True, state="AGUARDA_SIM")
        return Reply(SMS_CONSENT, producer_id=p.id)
    return Reply(SMS_HELP, producer_id=p.id if p else None)
