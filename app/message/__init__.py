"""M6: render(item, channel, lang) -> texto final. Fluxo: modelo fixo -> IA reescreve (opcional) -> validador -> canal."""
import os
from typing import Optional, Union

from app.message.polish import polish
from app.message.templates import Report, render as render_fixed, to_sms
from app.models import Alert


def render(item: Union[Alert, Report, dict], channel: str, lang: str = "pt", use_ai: bool = False,
           plot: Optional[str] = None) -> str:
    text = render_fixed(item, channel, lang, plot)
    if use_ai and channel != "sms" and isinstance(item, Alert):  # SMS: sempre o texto fixo (limite de 160)
        data = {**item.evidence, "action": item.action, "window": item.window}
        return polish(text, data, lang, max_chars=500)
    return text


LINK_LABEL = {"pt": "Detalhes, mapas e o porquê", "es": "Detalles, mapas y el porqué", "en": "Details, maps and the why"}


def with_link(text: str, channel: str, lang: str, link: Optional[str]) -> str:
    """Põe o link do relatório detalhado logo depois da mensagem.

    WhatsApp: sempre. SMS: só com SMS_INCLUDE_LINK=1 e se couber nos 160 caracteres (o projeto prevê SMS sem link,
    para quem tem pouca internet; por isso o padrão é não colocar).
    """
    if not link:
        return text
    if channel == "sms":
        extra = f" {link}"
        return text + extra if os.getenv("SMS_INCLUDE_LINK") == "1" and len(text) + len(extra) <= 160 else text
    return f"{text}\n\n{LINK_LABEL[lang]}: {link}"


__all__ = ["render", "with_link", "Report", "to_sms", "polish"]
