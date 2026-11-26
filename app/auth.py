"""Identidade do site: o número de WhatsApp VERIFICADO é a conta (sem senha).

Fluxo: o produtor informa nome e telefone e marca os dois consentimentos -> o BALK manda um código de 6 dígitos pelo
WhatsApp (SMS se falhar) -> ele digita o código -> a sessão abre (cookie opaco). O mesmo vale para o link de uso único que o
BALK manda no WhatsApp ("MAPA"): abre o site já identificado.

Defesas: código aleatório (secrets), guardado só como HMAC com segredo do servidor; vale 10 min e uma única vez; 5 tentativas;
limite por telefone (3 por hora, 1 por minuto) e por IP (10 por hora); sessão = token aleatório guardado só como hash;
cookie HttpOnly + SameSite=Lax (+ Secure em https); chamadas que alteram dados exigem a mesma origem (anti-CSRF).
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

from fastapi import HTTPException, Request, Response

from app import config, db, db_site
from app.delivery import deliver

COOKIE = "balk_session"
CODE_TTL_MIN = 10
MAX_ATTEMPTS = 5
PER_PHONE_HOUR = 3
PER_IP_HOUR = 10
COOLDOWN_S = 60
SESSION_DAYS = 30
CODE_RE = __import__("re").compile(r"^\d{6}$")


class AuthError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_code(phone: str, code: str) -> str:
    """HMAC do código com o segredo do servidor e o telefone (não dá para testar códigos contra uma cópia do banco)."""
    msg = f"{db.norm_phone(phone)}:{code}".encode()
    return hmac.new(config.auth_secret().encode(), msg, hashlib.sha256).hexdigest()


def code_message(code: str, lang: str = "pt") -> str:
    return {"pt": f"BALK: seu código de verificação é {code}. Vale por {CODE_TTL_MIN} minutos. Não passe a ninguém.",
            "es": f"BALK: su código de verificación es {code}. Vale {CODE_TTL_MIN} minutos. No lo comparta.",
            "en": f"BALK: your verification code is {code}. Valid for {CODE_TTL_MIN} minutes. Do not share it."}[lang]


def start_signup(phone: str, name: str, consents: list[str], ip: str, channel: str = "whatsapp") -> dict:
    """Valida limites e manda o código. Nada pessoal é enviado antes de o número provar que é dele."""
    digits = "".join(c for c in phone if c.isdigit())
    if not 10 <= len(digits) <= 15:
        raise AuthError(422, "Informe o telefone com DDD, só números (ex.: 65 99999-0000).")
    phone_n = db.norm_phone(phone)
    now = datetime.now()
    if db.get_contact_by_phone(phone_n) and not db.get_producer_by_phone(phone_n):
        # número que recebe os avisos de outra pessoa: resposta igual à de sucesso e nenhum código enviado (não revela quem está no BALK)
        return {"enviado": True, "canal": "whatsapp", "expira_em_min": CODE_TTL_MIN}
    last = db_site.last_verification_at(phone_n)
    if last and (now - last).total_seconds() < COOLDOWN_S:
        raise AuthError(429, f"Aguarde {COOLDOWN_S} segundos para pedir outro código.")
    hour = now - timedelta(hours=1)
    if db_site.count_verifications(phone=phone_n, since=hour) >= PER_PHONE_HOUR:
        raise AuthError(429, "Muitos códigos pedidos para este número. Tente de novo em 1 hora.")
    if db_site.count_verifications(ip=ip, since=hour) >= PER_IP_HOUR:
        raise AuthError(429, "Muitos pedidos deste acesso. Tente de novo em 1 hora.")
    code = new_code()
    version = config.consent()["versao"]
    db_site.create_verification(phone_n, (name or "").strip()[:80], hash_code(phone_n, code), consents, version, CODE_TTL_MIN, ip)
    p = db.get_producer_by_phone(phone_n)
    res = deliver(p.id if p else None, phone_n, channel, code_message(code), kind="codigo", proactive=True,
                  sms_text=code_message(code), log_text="BALK: código de verificação (omitido do registro)", purpose="code")
    return {"enviado": res["ok"], "canal": res["channel"], "expira_em_min": CODE_TTL_MIN}


def verify_signup(phone: str, code: str) -> dict:
    """Confere o código. Devolve a verificação usada (nome, consentimentos). Erros genéricos: não dizem o que falhou."""
    phone_n = db.norm_phone(phone)
    v = db_site.open_verification(phone_n)
    generic = AuthError(400, "Código inválido ou expirado. Peça um novo.")
    if v is None:
        raise generic
    if not db_site.take_attempt(v["id"], MAX_ATTEMPTS):  # atômico: nem pedidos simultâneos passam de 5 palpites
        raise AuthError(429, "Muitas tentativas. Peça um novo código.")
    if not CODE_RE.match(code or "") or not hmac.compare_digest(hash_code(phone_n, code), v["code_hash"]):
        raise generic
    if not db_site.use_verification(v["id"]):  # corrida: dois envios do mesmo código ao mesmo tempo
        raise generic
    return v


# ---------------------------------------------------------------- sessão (cookie)
def secure_cookie() -> bool:
    return config.public_base_url().startswith("https://")


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=secure_cookie(), path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def open_session(response: Response, producer_id: int) -> None:
    set_session_cookie(response, db_site.create_session(producer_id, "site", SESSION_DAYS))


def same_origin(request: Request) -> bool:
    """Anti-CSRF para chamadas que alteram dados: Origin (ou, na falta, Referer) precisa ser deste mesmo site."""
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        return not secure_cookie()  # sem cabeçalho: só aceito em desenvolvimento (testes, curl)
    o = urlparse(origin)
    host = request.headers.get("host", "")
    allowed = {host, urlparse(config.public_base_url()).netloc}
    return o.netloc in allowed


def require_session(request: Request) -> dict:
    """Dependência das rotas do produtor logado: devolve {producer_id, token}. 401 sem sessão; 403 se a origem não confere."""
    token = request.cookies.get(COOKIE, "")
    s = db_site.get_session(token)
    if s is None:
        raise HTTPException(401, "Entre de novo pelo seu número de WhatsApp.")
    if request.method not in ("GET", "HEAD", "OPTIONS") and not same_origin(request):
        raise HTTPException(403, "Origem não permitida.")
    if db.get_producer(s["producer_id"]) is None:
        raise HTTPException(401, "Conta não encontrada.")
    return {"producer_id": s["producer_id"], "token": token}


def map_link(producer_id: int) -> str:
    """Link de uso único (30 min) que abre o mapa já identificado. É o que o BALK manda no WhatsApp."""
    return f"{config.public_base_url()}/m/{db_site.create_magic_link(producer_id, 'map', 30)}"
