"""Seleção geométrica local de imagem/texto no preview do Vision 02.

O preview é um PNG composto: seus pixels não trazem IDs de elementos.
As regiões aqui são aproximações determinísticas derivadas dos controles
existentes (LCD lógico 100 x 100). Sem GTK, YAML, HID ou IPC.
"""
from __future__ import annotations

import math

from .studio_composition_v2 import display_geometry


def hit_visual_element(
    x: float, y: float, width: int, height: int, zoom: float, *,
    image_present: bool, image_x: int, image_y: int, image_scale: int,
    text: str, show_text: bool, offset_x: int, offset_y: int,
    font_size: int, horizontal: str, vertical: str,
) -> str | None:
    """Identifica a região clicada; texto tem prioridade sobre a imagem.

    A tipografia real, quebra de linha e recorte vêm do renderizador externo;
    este hit-test é aproximado. Fora dos elementos, retorna None.
    """
    if width <= 0 or height <= 0:
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    if x < 0 or y < 0 or x > width or y > height:
        return None
    cx, cy, unit = display_geometry(width, height, zoom)
    lx, ly = (x-cx)/unit, (y-cy)/unit

    # A âncora textual segue o alinhamento do usuário mais os deslocamentos.
    # Área aproximada: suficientemente ampla para clique, mas sem ocupar
    # desnecessariamente a imagem atrás do texto.
    if show_text and text.strip():
        if horizontal not in ('left', 'center', 'right') or vertical not in ('top', 'center', 'bottom'):
            raise ValueError('Alinhamento de texto inválido')
        if not 8 <= font_size <= 36:
            raise ValueError('Fonte inválida')
        lines = text.splitlines() or [text]
        estimated_width = min(96.0, max(18.0, max(len(line) for line in lines) * font_size * 0.52))
        # Uma linha longa pode quebrar no LCD de 100px.
        estimated_lines = max(len(lines), math.ceil(max(len(line) for line in lines) * font_size * .52 / 94))
        estimated_height = min(96.0, max(16.0, font_size * 1.35 * estimated_lines))
        text_x = offset_x + {'left': -46.0 + estimated_width / 2,
                             'center': 0.0,
                             'right': 46.0 - estimated_width / 2}[horizontal]
        text_y = offset_y + {'top': -46.0 + estimated_height / 2,
                             'center': 0.0,
                             'bottom': 46.0 - estimated_height / 2}[vertical]
        if abs(lx-text_x) <= estimated_width/2 + 3 and abs(ly-text_y) <= estimated_height/2 + 3:
            return 'text'

    if image_present and 25 <= image_scale <= 200:
        half = image_scale / 2
        if image_x-half <= lx <= image_x+half and image_y-half <= ly <= image_y+half:
            return 'image'
    return None
