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
    if os.getenv("OPENWA_URL") and len(os.getenv("OPENWA_WEBHOOK_SECRET", "")) < 16:
        p.append("OPENWA_URL definido sem OPENWA_WEBHOOK_SECRET (16+ caracteres; o webhook do OpenWA ficaria sem assinatura)")
    if os.getenv("SMSGATE_URL") and not os.getenv("SMSGATE_WEBHOOK_KEY"):
        p.append("SMSGATE_URL definido sem SMSGATE_WEBHOOK_KEY (a chave de assinatura que aparece no app do celular)")
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


def _a(url: str, text: str) -> str:
    return f'<a href="{url}" target="_blank" rel="noopener">{text}</a>'


def map_tiles() -> dict:
    """Camadas do mapa do site. `layers` é uma lista; a primeira de tipo "base" abre selecionada.

    Tipos: "base" (o produtor escolhe uma), "overlay" (liga e desliga por cima) e "dem" (relevo que vira sombreado no navegador).
    Fontes, todas sem chave (conferidas em 27/11/2026) e só para demonstração e uso NÃO comercial até alguém decidir o contrário:
    - Esri World Imagery: satélite de alta resolução; os termos da Esri vedam uso comercial sem chave da plataforma deles.
    - EOxCloudless 2025 (Sentinel-2, 10 m): CC BY 4.0, mosaico de 2025.
    - OpenTopoMap (curvas de nível e relevo): CC BY-SA, uso moderado.
    - AWS Terrain Tiles (relevo aberto) para o sombreado.
    - OpenStreetMap (ruas): demo; uso em escala exige provedor próprio.
    Com MAPTILER_KEY, o satélite do MapTiler vira o primeiro (plano gratuito: teste e uso não comercial).
    `url`, `attribution` e `max_zoom` repetem a camada inicial, por compatibilidade. MAP_TILES_URL substitui a de ruas."""
    osm_attr = _a("https://www.openstreetmap.org/copyright", "© OpenStreetMap contributors")
    esri_attr = "Imagens: Esri, Maxar, Earthstar Geographics e a comunidade GIS"
    layers = [
        {"id": "satelite", "tipo": "base", "nome": "Satélite", "descricao": "Imagem de satélite de alta resolução (Esri)",
         "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
         "attribution": esri_attr, "max_zoom": 17},  # zoom 18 falta em boa parte do interior (vem a imagem "Map data not yet available")
        {"id": "sentinel", "tipo": "base", "nome": "Sentinel-2 (2025)", "descricao": "Satélite europeu, 10 m por pixel, mosaico de 2025 sem nuvens",
         "url": "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2025_3857/default/g/{z}/{y}/{x}.jpg",
         "attribution": _a("https://cloudless.eox.at", "EOxCloudless") + " por EOX IT Services GmbH (contém dados Copernicus Sentinel modificados, 2025)",
         "max_zoom": 14},
        {"id": "relevo", "tipo": "base", "nome": "Relevo e curvas de nível", "descricao": "Mapa topográfico (OpenTopoMap)",
         "url": "https://tile.opentopomap.org/{z}/{x}/{y}.png",
         "attribution": _a("https://opentopomap.org", "OpenTopoMap") + " (" + _a("https://creativecommons.org/licenses/by-sa/3.0/", "CC-BY-SA") + ") · " + osm_attr,
         "max_zoom": 17},
        {"id": "ruas", "tipo": "base", "nome": "Ruas", "descricao": "Mapa de ruas e estradas (OpenStreetMap)",
         "url": os.getenv("MAP_TILES_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png"),
         "attribution": os.getenv("MAP_TILES_ATTRIBUTION", osm_attr), "max_zoom": int(os.getenv("MAP_TILES_MAXZOOM", "19"))},
        {"id": "nomes", "tipo": "overlay", "nome": "Nomes e divisas", "descricao": "Cidades, estradas e limites por cima do satélite (Esri)",
         "url": "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
         "attribution": "Rótulos: Esri", "max_zoom": 17, "ligada": True},
        {"id": "sombreado", "tipo": "dem", "nome": "Sombreado do relevo", "descricao": "Realça morros e baixadas por cima do mapa (dados abertos AWS Terrain Tiles)",
         "url": "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png", "encoding": "terrarium",
         "attribution": _a("https://registry.opendata.aws/terrain-tiles/", "Terrain Tiles (AWS Open Data)"), "max_zoom": 15, "ligada": False},
    ]
    key = os.getenv("MAPTILER_KEY", "").strip()
    if key:
        layers.insert(0, {"id": "satelite_maptiler", "tipo": "base", "nome": "Satélite (MapTiler)", "descricao": "Satélite do MapTiler (precisa da chave)",
                          "url": f"https://api.maptiler.com/tiles/satellite-v2/{{z}}/{{x}}/{{y}}.jpg?key={key}",
                          "attribution": _a("https://www.maptiler.com/copyright/", "© MapTiler") + " " + osm_attr, "max_zoom": 20})
    first = next(x for x in layers if x["tipo"] == "base")
    return {**{k: first[k] for k in ("url", "attribution", "max_zoom")}, "layers": layers}


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
