"""Segurança: chave de API, limite de requisições, assinatura dos webhooks (Meta e Twilio), máscara de telefone."""
import base64
import hashlib
import hmac
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import Depends, HTTPException, Request

from app import config


def require_api_key(request: Request) -> None:
    """Rotas internas (n8n, painel). Em production a chave é obrigatória; em dev, se BALK_API_KEY existir, também vale."""
    key = config.api_key()
    if not key:
        if config.is_production():
            raise HTTPException(503, "servidor sem BALK_API_KEY configurada")
        return
    sent = request.headers.get("x-api-key", "")
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        sent = sent or auth[7:]
    if not hmac.compare_digest(sent.encode(), key.encode()):
        raise HTTPException(401, "chave de API inválida")


def require_api_key_outside_demo(request: Request) -> None:
    """Rotas do simulador: abertas em BALK_ENV=demo (os avaliadores usam sem chave); fora da demo, igual a require_api_key."""
    if config.is_demo():
        return
    require_api_key(request)


class RateLimiter:
    """Janela deslizante em memória, por IP. Basta para um processo só; com vários, use um proxy (nginx) na frente."""

    def __init__(self, limit: int, per_s: int = 60):
        self.limit, self.per_s = limit, per_s
        self.hits: dict[str, deque] = defaultdict(deque)

    MAX_KEYS = 50_000

    def check(self, key: str) -> bool:
        now = time.monotonic()
        if len(self.hits) > self.MAX_KEYS:  # chaves antigas não podem crescer sem fim
            for k in [k for k, v in self.hits.items() if not v or now - v[-1] > self.per_s]:
                del self.hits[k]
        q = self.hits[key]
        while q and now - q[0] > self.per_s:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True

    def reset(self) -> None:
        self.hits.clear()


def client_ip(request: Request) -> str:
    """IP de quem conectou. NÃO lê X-Forwarded-For: o cliente pode forjá-lo e anular todos os limites. Atrás de proxy, o
    uvicorn (--proxy-headers) já troca request.client pelo IP real, mas só para os proxies listados em FORWARDED_ALLOW_IPS."""
    return request.client.host if request.client else "?"


def limiter_dependency(limiter: RateLimiter):
    def dep(request: Request):
        if not limiter.check(client_ip(request)):
            raise HTTPException(429, "muitas requisições; tente de novo em instantes")
    return Depends(dep)


# ---- webhooks ----
def verify_meta_signature(body: bytes, header: Optional[str], app_secret: str) -> bool:
    """X-Hub-Signature-256: sha256=<HMAC-SHA256 do corpo bruto com o segredo do app da Meta>."""
    if not header or not header.startswith("sha256=") or not app_secret:
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[7:])


def twilio_signature(url: str, params: dict, auth_token: str) -> str:
    """Assinatura da Twilio: HMAC-SHA1 de (URL + parâmetros do POST ordenados por nome, nome e valor colados), em base64."""
    data = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    return base64.b64encode(hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def verify_twilio_signature(url: str, params: dict, header: Optional[str], auth_token: str) -> bool:
    if not header or not auth_token:
        return False
    return hmac.compare_digest(twilio_signature(url, params, auth_token), header)


def mask_phone(phone: str) -> str:
    """Telefone nos logs: só os 4 últimos dígitos."""
    d = "".join(c for c in phone if c.isdigit())
    return "***" + d[-4:] if d else "***"
