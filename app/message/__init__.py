"""M6: render(item, channel, lang) -> texto final. Fluxo: modelo fixo -> IA reescreve (opcional) -> validador -> canal."""
from typing import Union

from app.message.polish import polish
from app.message.templates import Report, render as render_fixed, to_sms
from app.models import Alert


def render(item: Union[Alert, Report, dict], channel: str, lang: str = "pt", use_ai: bool = False) -> str:
    text = render_fixed(item, channel, lang)
    if use_ai and channel != "sms" and isinstance(item, Alert):  # SMS: sempre o texto fixo (limite de 160)
        data = {**item.evidence, "action": item.action, "window": item.window}
        return polish(text, data, lang, max_chars=500)
    return text


__all__ = ["render", "Report", "to_sms", "polish"]
