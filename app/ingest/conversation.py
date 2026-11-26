"""M1: máquina de estados do cadastro. INICIO -> PEDE_LOCAL -> PEDE_CULTURA -> PEDE_PLANTIO -> ATIVO.

Canal SMS: mensagem única "BALK soja 20/10 Sorriso MT" (estado extra AGUARDA_SIM para o consentimento).
"""
import difflib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from app import config, db
from app.data.geocode import geocode
from app.models import Producer

CONSENT = ("Olá, sou o BALK. Envio orientações curtas sobre clima e lavoura. "
           "Responda SIM para aceitar ou SAIR para parar.")
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
SMS_CONSENT = "BALK: responda SIM para receber alertas de clima e lavoura. SAIR para parar."
SMS_OK = "BALK: cadastro ok. Voce recebera alertas de clima por SMS. Para analise da lavoura envie o pin pelo WhatsApp."
SMS_HELP = "BALK: envie assim: BALK soja 20/10 Sorriso MT (cultura, data do plantio, municipio e UF)."

LAT_RANGE, LON_RANGE = (-56.0, 72.0), (-170.0, -30.0)  # Américas


@dataclass
class Reply:
    text: str
    became_active: bool = False
    producer_id: Optional[int] = None


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


def _active_reply(p: Producer, t: str) -> Reply:
    if t == "1":
        return Reply(ACK, producer_id=p.id)
    if t == "2":
        db.add_escalation(p.id, p.phone, "produtor pediu ajuda (resposta 2)")
        return Reply(HELP_ESCALATE, producer_id=p.id)
    return Reply(IDLE, producer_id=p.id)


def handle_message(phone: str, text: str, channel: str = "whatsapp", location: Optional[tuple[float, float]] = None,
                   today: Optional[date] = None, source: str = "direto") -> Reply:
    """Uma mensagem recebida: lê o estado, valida a entrada, grava e devolve a próxima pergunta."""
    if channel == "sms":
        return handle_sms(phone, text, today, source)
    t = norm(text)
    p = db.get_producer_by_phone(phone)
    if t == "sair":
        if p:
            db.update_producer(p.id, active=False, consent=False, state="SAIU")
        return Reply(BYE, producer_id=p.id if p else None)
    if p is None or p.state == "SAIU":
        p = _start(phone, channel, source)
        return Reply(CONSENT, producer_id=p.id)

    if p.state == "INICIO":
        if t == "sim":
            db.update_producer(p.id, consent=True, state="PEDE_LOCAL")
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

    return _active_reply(p, t)


def handle_sms(phone: str, text: str, today: Optional[date] = None, source: str = "direto") -> Reply:
    t = norm(text)
    p = db.get_producer_by_phone(phone)
    if t == "sair":
        if p:
            db.update_producer(p.id, active=False, consent=False, state="SAIU")
        return Reply("BALK: cadastro cancelado. Nao enviaremos mais mensagens.", producer_id=p.id if p else None)
    if p and p.state == "AGUARDA_SIM":
        if t == "sim":
            db.update_producer(p.id, consent=True, active=True, state="ATIVO")
            return Reply(SMS_OK, became_active=True, producer_id=p.id)
        return Reply(SMS_CONSENT, producer_id=p.id)
    if p and p.state == "ATIVO" and t in ("1", "2"):
        return _active_reply(p, t)
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
