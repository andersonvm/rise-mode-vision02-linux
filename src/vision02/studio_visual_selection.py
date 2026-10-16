"""Geometria de seleção local dos elementos da composição do Vision 02.

A prévia é um PNG já composto: não contém bounding boxes nem máscaras.
As regiões são estimativas determinísticas para um LCD lógico 100x100 e
servem *tanto* para destacar quanto para identificar os elementos.
Este módulo não acessa GTK, perfis, arquivos, IPC ou dispositivos HID.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from .studio_composition_v2 import display_geometry


@dataclass(frozen=True)
class VisualRegion:
    """Retângulo em coordenadas do widget, limitado à superfície visível."""

    x: float
    y: float
    width: float
    height: float

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x <= self.x + self.width and self.y <= y <= self.y + self.height


def _clipped_region(left: float, top: float, right: float, bottom: float,
                    width: int, height: int) -> VisualRegion | None:
    x0, y0 = max(0.0, left), max(0.0, top)
    x1, y1 = min(float(width), right), min(float(height), bottom)
    if x0 >= x1 or y0 >= y1:
        return None
    return VisualRegion(x0, y0, x1 - x0, y1 - y0)


def visual_element_regions(
    width: int, height: int, zoom: float, *,
    image_present: bool, image_x: int, image_y: int, image_scale: int,
    text: str, show_text: bool, offset_x: int, offset_y: int,
    font_size: int, horizontal: str, vertical: str,
) -> dict[str, VisualRegion]:
    """Calcula regiões *aproximadas* de imagem/texto após zoom e recorte.

    Não estima pixels transparentes nem mede a fonte real do renderizador.
    Em especial, uma imagem com ``contain`` pode ocupar menos pixels.
    """
    if width <= 0 or height <= 0:
        return {}
    cx, cy, unit = display_geometry(width, height, zoom)
    result: dict[str, VisualRegion] = {}

    if image_present and 25 <= image_scale <= 200:
        half = image_scale / 2
        region = _clipped_region(
            cx + (image_x - half) * unit,
            cy + (image_y - half) * unit,
            cx + (image_x + half) * unit,
            cy + (image_y + half) * unit,
            width, height,
        )
        if region is not None:
            result['image'] = region

    if show_text and text.strip():
        if horizontal not in ('left', 'center', 'right') or vertical not in ('top', 'center', 'bottom'):
            raise ValueError('Alinhamento de texto inválido')
        if not 8 <= font_size <= 36:
            raise ValueError('Fonte inválida')
        lines = text.splitlines() or [text]
        maximum = max(len(line) for line in lines)
        estimated_width = min(96.0, max(18.0, maximum * font_size * .52))
        estimated_lines = max(len(lines), math.ceil(maximum * font_size * .52 / 94))
        estimated_height = min(96.0, max(16.0, font_size * 1.35 * estimated_lines))
        tx = offset_x + {'left': -46.0 + estimated_width / 2,
                         'center': 0.0,
                         'right': 46.0 - estimated_width / 2}[horizontal]
        ty = offset_y + {'top': -46.0 + estimated_height / 2,
                         'center': 0.0,
                         'bottom': 46.0 - estimated_height / 2}[vertical]
        # Inclui margem de toque de 3 unidades do LCD.
        half_w, half_h = estimated_width / 2 + 3, estimated_height / 2 + 3
        region = _clipped_region(
            cx + (tx - half_w) * unit,
            cy + (ty - half_h) * unit,
            cx + (tx + half_w) * unit,
            cy + (ty + half_h) * unit,
            width, height,
        )
        if region is not None:
            result['text'] = region
    return result


def hit_visual_element(
    x: float, y: float, width: int, height: int, zoom: float, *,
    image_present: bool, image_x: int, image_y: int, image_scale: int,
    text: str, show_text: bool, offset_x: int, offset_y: int,
    font_size: int, horizontal: str, vertical: str,
    prefer: str = 'text',
) -> str | None:
    """Identifica elemento clicado, com prioridade configurável em sobreposição."""
    if prefer not in ('image', 'text'):
        raise ValueError('Preferência de seleção inválida')
    if width <= 0 or height <= 0 or not (math.isfinite(x) and math.isfinite(y)):
        return None
    if x < 0 or y < 0 or x > width or y > height:
        return None
    regions = visual_element_regions(
        width, height, zoom,
        image_present=image_present, image_x=image_x, image_y=image_y,
        image_scale=image_scale, text=text, show_text=show_text,
        offset_x=offset_x, offset_y=offset_y, font_size=font_size,
        horizontal=horizontal, vertical=vertical,
    )
    for target in (prefer, 'image' if prefer == 'text' else 'text'):
        region = regions.get(target)
        if region is not None and region.contains(x, y):
            return target
    return None
