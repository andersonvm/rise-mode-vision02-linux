"""Configuração visual segura das teclas, independente de GTK, USB e IPC.

Os controles representam exatamente os campos aceitos por parse_appearance.
Ausência de appearance preserva a renderização legada.
"""
from __future__ import annotations

from dataclasses import asdict

from .profiles.loader import parse_appearance
from .profiles.models import KeyAppearance

CHOICES = {
    'font_family': ('sans', 'serif', 'mono'),
    'font_weight': ('regular', 'bold'),
    'horizontal': ('left', 'center', 'right'),
    'vertical': ('top', 'center', 'bottom'),
    'image_fit': ('cover', 'contain', 'stretch'),
}
INT_RANGES = {'font_size': (8, 36), 'offset_x': (-40, 40), 'offset_y': (-40, 40)}
COLORS = ('background', 'text_color')


def ui_appearance(raw: dict | None) -> dict:
    """Exibe padrões reais sem ativar a aparência em perfis legados."""
    if raw is not None and not isinstance(raw, dict):
        raise ValueError('Aparência inválida')
    style = parse_appearance(raw)
    return asdict(style if style is not None else KeyAppearance())


def validated_appearance(enabled: bool, fields: dict) -> dict | None:
    """Não propaga campos adicionais ou tipos implicitamente convertidos."""
    if type(enabled) is not bool or not isinstance(fields, dict):
        raise ValueError('Controles de aparência inválidos')
    if not enabled:
        return None
    allowed = set(asdict(KeyAppearance())) - {'text'}
    if set(fields) != allowed:
        raise ValueError('Campos de aparência incompletos ou desconhecidos')
    result = dict(fields)
    result['text'] = None  # texto visual separado no formulário rápido
    parsed = parse_appearance(result)
    if parsed is None:
        raise ValueError('Aparência inválida')
    return asdict(parsed)


def hex_from_rgb(red: float, green: float, blue: float) -> str:
    if any(not isinstance(v, (int, float)) or not 0 <= v <= 1 for v in (red, green, blue)):
        raise ValueError('RGB inválido')
    return '#{:02X}{:02X}{:02X}'.format(*(round(v * 255) for v in (red, green, blue)))
