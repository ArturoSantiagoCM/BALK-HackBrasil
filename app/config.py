"""Configuração: variáveis de ambiente e arquivos YAML (lidos a cada chamada de função)."""

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def data_mode() -> str:
    """simulado = só dados fixos; real = APIs; auto = tenta real, cai para cache e depois para simulado (só fora de produção).

    Em BALK_ENV=production o "auto" vale como "real": NUNCA se troca dado real por simulado em silêncio (princípio da SPEC
    do projeto). Se a fonte real falhar, o sistema fica sem dado, diz isso e não gera alerta.
    """
    mode = os.getenv("DATA_MODE", "auto").lower()
    return "real" if mode == "auto" and is_production() else mode


def engine_name() -> str:
    return os.getenv("ENGINE", "python").lower()


def work_root() -> Path:
    return Path(os.getenv("BALK_WORK", ROOT / "work"))


def db_path() -> Path:
    return Path(os.getenv("BALK_DB", ROOT / "balk.db"))


def env() -> str:
    """dev (padrão), demo ou production.

    - production: chave de API obrigatória, simulador e /docs desligados.
    - demo: demonstração pública para os avaliadores (simulador ligado, dados simulados, nada sai por canal real);
      a rota que apaga o banco exige a chave.
    """
    v = os.getenv("BALK_ENV", "dev").strip().lower()
    if v not in (
        "dev",
        "demo",
        "production",
    ):  # um erro de digitação ("prod", "Production ") NÃO pode ligar a demo em silêncio
        raise RuntimeError(
            f"BALK_ENV inválido: {v!r}. Use 'dev', 'demo' ou 'production'."
        )
    return v


def is_production() -> bool:
    return env() == "production"


def is_demo() -> bool:
    return env() == "demo"


def api_key() -> str:
    return os.getenv("BALK_API_KEY", "")


def production_problems() -> list[str]:
    """O que impede de rodar de verdade com segurança. Lista vazia = pronto (só vale em BALK_ENV=production)."""
    p = []
    if len(api_key()) < 24:
        p.append("BALK_API_KEY ausente ou curta (use 24+ caracteres aleatórios)")
    base = public_base_url()
    if not base.startswith("https://") or "localhost" in base or "127.0.0.1" in base:
        p.append(
            "PUBLIC_BASE_URL precisa ser o endereço https público (os links do relatório saem dele)"
        )
    if len(os.getenv("BALK_AUTH_SECRET", "")) < 24:
        p.append(
            "BALK_AUTH_SECRET ausente ou curto (24+ caracteres aleatórios; protege os códigos de verificação do site)"
        )
    if data_mode() == "simulado":
        p.append(
            "DATA_MODE=simulado: os relatórios mostrariam dados simulados (use auto ou real)"
        )
    if os.getenv("WHATSAPP_TOKEN") and not (
        os.getenv("WHATSAPP_APP_SECRET") and os.getenv("WHATSAPP_VERIFY_TOKEN")
    ):
        p.append(
            "WHATSAPP_TOKEN definido sem WHATSAPP_APP_SECRET e WHATSAPP_VERIFY_TOKEN (webhook sem assinatura)"
        )
    if os.getenv("TWILIO_ACCOUNT_SID") and not os.getenv("TWILIO_AUTH_TOKEN"):
        p.append("TWILIO_ACCOUNT_SID definido sem TWILIO_AUTH_TOKEN")
    return p


def demo_problems() -> list[str]:
    """O que impede de publicar a demonstração com segurança. Lista vazia = pronto (só vale em BALK_ENV=demo)."""
    p = []
    if len(api_key()) < 24:
        p.append("BALK_API_KEY ausente ou curta (protege as rotas internas e o botão que apaga o banco)")
    base = public_base_url()
    if not base.startswith("https://") or "localhost" in base or "127.0.0.1" in base:
        p.append("PUBLIC_BASE_URL precisa ser o endereço https público da demo")
    if len(os.getenv("BALK_AUTH_SECRET", "")) < 24:
        p.append("BALK_AUTH_SECRET ausente ou curto (24+ caracteres aleatórios)")
    if data_mode() == "real":
        p.append("DATA_MODE=real na demo: use simulado ou auto")
    for k in ("WHATSAPP_TOKEN", "TWILIO_ACCOUNT_SID"):
        if os.getenv(k):
            p.append(f"{k} definido: a demo não envia mensagens reais, remova a credencial")
    return p


def public_base_url() -> str:
    """Endereço público do BALK, usado nos links de relatório enviados ao produtor."""
    return os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")


def auth_secret() -> str:
    """Segredo do HMAC dos códigos de verificação. Em dev, sem variável, usa um valor fixo de desenvolvimento."""
    return os.getenv("BALK_AUTH_SECRET") or "balk-dev-only-secret-not-for-production"


def map_tiles() -> dict:
    """Fundos do mapa do site. `layers` = lista de camadas escolhíveis (a primeira é a inicial).

    Ruas: OpenStreetMap (demo; uso em escala exige provedor próprio, ver OPERACAO). Satélite: MapTiler, só se houver
    MAPTILER_KEY (plano gratuito do MapTiler é para teste e uso não comercial). `url`, `attribution` e `max_zoom` repetem a
    camada inicial, por compatibilidade. MAP_TILES_URL (se definido) substitui a camada de ruas.
    """
    osm = {
        "id": "ruas",
        "nome": "Ruas",
        "url": os.getenv(
            "MAP_TILES_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        ),
        "attribution": os.getenv(
            "MAP_TILES_ATTRIBUTION", "© OpenStreetMap contributors"
        ),
        "max_zoom": int(os.getenv("MAP_TILES_MAXZOOM", "19")),
    }
    layers = [osm]
    key = os.getenv("MAPTILER_KEY", "").strip()
    if key:
        sat = {
            "id": "satelite",
            "nome": "Satélite",
            "url": f"https://api.maptiler.com/tiles/satellite-v2/{{z}}/{{x}}/{{y}}.jpg?key={key}",
            "attribution": '<a href="https://www.maptiler.com/copyright/" target="_blank" rel="noopener">© MapTiler</a> '
            '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors</a>',
            "max_zoom": 20,
        }
        layers = [sat, osm]
    return {
        **{k: layers[0][k] for k in ("url", "attribution", "max_zoom")},
        "layers": layers,
    }


def report_ttl_days() -> int:
    return int(os.getenv("REPORT_TTL_DAYS", "30"))


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    with open(ROOT / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def consent() -> dict:
    """Textos e versão do consentimento (consent.yaml)."""
    return load_yaml("consent.yaml")


def csv_requires_optin() -> bool:
    """CSV de cooperativa: em produção, cada produtor só recebe mensagens depois de responder SIM (LGPD). Em dev, a
    declaração de consentimento da cooperativa basta (é o que a demo usa). Pode ser forçado com CSV_REQUIRES_OPTIN=1/0.
    """
    v = os.getenv("CSV_REQUIRES_OPTIN")
    return is_production() if v is None else v == "1"


def rules() -> dict:
    return load_yaml("rules.yaml")


def crops_cfg() -> dict:
    return load_yaml("crops.yaml")
