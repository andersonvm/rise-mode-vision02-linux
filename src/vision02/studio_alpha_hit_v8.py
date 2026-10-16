"""Seleção precisa de imagem/texto pelas máscaras RGBA locais da v7.

Sem GTK, Pillow, arquivo, YAML, IPC ou hardware. Cada máscara é uma sequência
linear de 100x100 bytes alfa; zeros não são selecionáveis. A seleção respeita
zoom centralizado e a visibilidade apenas da prévia GTK.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

from .studio_composition_v2 import display_geometry
from .studio_visual_selection import VisualRegion

LCD_WIDTH = 100
LCD_HEIGHT = 100
MASK_LENGTH = LCD_WIDTH * LCD_HEIGHT
DEFAULT_THRESHOLD = 32
ORDER = ('image', 'text')


def extract_alpha(pixels: bytes, width: int, height: int, rowstride: int,
                  channels: int, *, has_alpha: bool = True) -> bytes:
    """Converte bytes RGBA de um Pixbuf para 100x100 alfa sem ignorar stride.

    A validação é estrita: um PNG RGB ou truncado não pode virar uma máscara
    opaca por engano. GUI trata ValueError como fallback geométrico.
    """
    if (type(width) is not int or type(height) is not int or
        (width, height) != (LCD_WIDTH, LCD_HEIGHT) or
        type(channels) is not int or channels != 4 or
        type(has_alpha) is not bool or not has_alpha or
        type(rowstride) is not int or rowstride < width * channels):
        raise ValueError('Formato RGBA incompatível com LCD 100x100')
    if not isinstance(pixels, (bytes, bytearray, memoryview)):
        raise ValueError('Buffer de pixel inválido')
    data = memoryview(pixels)
    if len(data) < (height - 1) * rowstride + width * channels:
        raise ValueError('Buffer RGBA truncado')
    result = bytearray(MASK_LENGTH)
    for row in range(height):
        start = row * rowstride + 3
        result[row * width:(row + 1) * width] = data[start:start + width * 4:4]
    return bytes(result)


def widget_pixel(x: float, y: float, width: int, height: int,
                 zoom: float) -> tuple[int, int] | None:
    """Transforma coordenadas do gesto GTK no pixel exato do LCD virtual."""
    if (not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or
        not math.isfinite(x) or not math.isfinite(y) or
        type(width) is not int or type(height) is not int or
        width <= 0 or height <= 0):
        return None
    if x < 0 or y < 0 or x >= width or y >= height:
        return None
    cx, cy, unit = display_geometry(width, height, zoom)
    ix = math.floor((x - cx) / unit + LCD_WIDTH / 2)
    iy = math.floor((y - cy) / unit + LCD_HEIGHT / 2)
    if not (0 <= ix < LCD_WIDTH and 0 <= iy < LCD_HEIGHT):
        return None
    return ix, iy


def mask_candidates(masks: Mapping[str, bytes], x: float, y: float,
                    width: int, height: int, zoom: float, *,
                    visible: Mapping[str, bool] | None = None,
                    threshold: int = DEFAULT_THRESHOLD) -> tuple[str, ...]:
    """Retorna imagem/texto apenas quando o pixel tem alfa suficiente."""
    if type(threshold) is not int or not 1 <= threshold <= 255:
        raise ValueError('Limiar alfa inválido')
    point = widget_pixel(x, y, width, height, zoom)
    if point is None:
        return ()
    index = point[1] * LCD_WIDTH + point[0]
    result = []
    for key in ORDER:
        if visible is not None and not visible.get(key, True):
            continue
        alpha = masks.get(key)
        if isinstance(alpha, (bytes, bytearray)) and len(alpha) == MASK_LENGTH:
            if alpha[index] >= threshold:
                result.append(key)
    return tuple(result)


def choose_mask_layer(candidates: tuple[str, ...], prefer: str = 'text') -> str | None:
    """No cruzamento exato, mantém preferência manual da v3."""
    if prefer not in ORDER:
        raise ValueError('Preferência de seleção inválida')
    if prefer in candidates:
        return prefer
    other = 'image' if prefer == 'text' else 'text'
    return other if other in candidates else None


def next_mask_layer(candidates: tuple[str, ...], current: str) -> str | None:
    """Alterna somente onde os dois canais possuem alfa visível."""
    if current not in ORDER:
        raise ValueError('Camada selecionada inválida')
    if candidates != ORDER:
        return None
    return 'text' if current == 'image' else 'image'


def mask_regions(masks: Mapping[str, bytes], width: int, height: int,
                 zoom: float, *, visible: Mapping[str, bool] | None = None,
                 threshold: int = DEFAULT_THRESHOLD) -> dict[str, VisualRegion]:
    """Molduras apertadas em torno dos pixels opacos, recortadas no viewport."""
    if type(threshold) is not int or not 1 <= threshold <= 255:
        raise ValueError('Limiar alfa inválido')
    if width <= 0 or height <= 0:
        return {}
    cx, cy, unit = display_geometry(width, height, zoom)
    result = {}
    for key in ORDER:
        if visible is not None and not visible.get(key, True):
            continue
        alpha = masks.get(key)
        if not isinstance(alpha, (bytes, bytearray)) or len(alpha) != MASK_LENGTH:
            continue
        indices = (index for index, value in enumerate(alpha) if value >= threshold)
        first = next(indices, None)
        if first is None:
            continue
        xs = [first % LCD_WIDTH]
        ys = [first // LCD_WIDTH]
        for index in indices:
            xs.append(index % LCD_WIDTH)
            ys.append(index // LCD_WIDTH)
        x0 = max(0.0, cx + (min(xs) - 50) * unit)
        y0 = max(0.0, cy + (min(ys) - 50) * unit)
        x1 = min(float(width), cx + (max(xs) + 1 - 50) * unit)
        y1 = min(float(height), cy + (max(ys) + 1 - 50) * unit)
        if x1 > x0 and y1 > y0:
            result[key] = VisualRegion(x0, y0, x1 - x0, y1 - y0)
    return result
