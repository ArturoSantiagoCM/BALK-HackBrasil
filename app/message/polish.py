"""M6: IA de redação (opcional) + validador em código. Se a IA falhar ou o validador reprovar, vale o texto fixo."""
import json
import os
import re
import unicodedata
from typing import Callable, Optional

import requests

FORBIDDEN = ["garantido", "garantia", "garantimos", "dose", "doses", "dosagem", "l/ha", "kg/ha", "ml/ha",
             "glifosato", "roundup", "produto", "produtos", "marca", "fungicida", "herbicida", "inseticida"]
NUM = re.compile(r"\d+(?:[.,]\d+)?")
SYSTEM = ("Você reescreve mensagens agrícolas curtas em {idioma}, em tom simples e respeitoso.\n"
          "Use SÓ os números do JSON. Não cite produtos, marcas nem doses. Não dê garantias.\n"
          "Mantenha duas linhas no topo (o que fazer e o motivo) e \"Por quê\" abaixo. Máximo de {N} caracteres. "
          "Se faltar dado, diga que não há dado suficiente.")
IDIOMAS = {"pt": "português do Brasil", "es": "español", "en": "English"}


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _numbers(s: str) -> set[str]:
    out = set()
    for m in NUM.findall(s):
        v = m.replace(",", ".")
        if "." in v:
            v = v.rstrip("0").rstrip(".")
        out.add(v)
    return out


def _flatten(d) -> str:
    return json.dumps(d, ensure_ascii=False, default=str)


def validate_polished(original: str, polished: str, data: dict, max_chars: Optional[int] = None) -> tuple[bool, str]:
    """(a) números existem na entrada; (b) tamanho; (c) lista proibida; (d) ação e janela presentes."""
    allowed = _numbers(original) | _numbers(_flatten(data))
    extra = _numbers(polished) - allowed
    if extra:
        return False, f"número inventado: {sorted(extra)[0]}"
    if max_chars is not None and len(polished) > max_chars:
        return False, f"texto com {len(polished)} caracteres (limite {max_chars})"
    words = set(re.findall(r"[a-z/]+", _norm(polished)))
    bad = [w for w in FORBIDDEN if w in words]
    if bad:
        return False, f"palavra proibida: {bad[0]}"
    window = data.get("window")
    if window and not _numbers(str(window)) <= _numbers(polished):
        return False, "janela ausente"
    action = data.get("action")
    if action:
        stem = _norm(action.split()[0])[:4]
        if stem and stem not in _norm(polished):
            return False, "ação ausente"
    return True, "ok"


def _anthropic_llm(system: str, user: str, timeout: float = 5.0) -> Optional[str]:
    """Chama a API de mensagens da Anthropic. Sem ANTHROPIC_API_KEY devolve None (usa o texto fixo)."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=timeout,
                      headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                      json={"model": os.getenv("POLISH_MODEL", "claude-haiku-5-5"), "max_tokens": 400,
                            "system": system, "messages": [{"role": "user", "content": user}]})
    r.raise_for_status()
    return r.json()["content"][0]["text"].strip()


def polish(text: str, data: dict, lang: str, max_chars: int, llm: Optional[Callable] = None) -> str:
    """Reescreve com IA; volta ao texto fixo se a IA falhar, demorar mais de 5 s ou o validador reprovar."""
    llm = llm or _anthropic_llm
    try:
        out = llm(SYSTEM.format(idioma=IDIOMAS.get(lang, "português"), N=max_chars),
                  json.dumps({"texto": text, "dados": data}, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001
        return text
    if not out:
        return text
    ok, _ = validate_polished(text, out, data, max_chars)
    return out if ok else text
