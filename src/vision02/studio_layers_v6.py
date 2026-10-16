"""Operações locais de camadas v6: bloqueio e centralização aproximada.

Não acessa GTK, YAML, renderizador, IPC ou USB/HID.
A centralização de texto usa a mesma caixa estimada da seleção v3; não mede
os glifos reais, portanto a centralização é aproximada.
"""
from __future__ import annotations

from collections.abc import Mapping

from .studio_composition_v2 import FIELDS
from .studio_visual_selection import visual_element_regions

LAYERS = ('image', 'text')
AXES = ('x', 'y')


def is_layer_locked(locks: Mapping[str, bool], layer: str) -> bool:
    if layer not in LAYERS:
        raise ValueError('Camada inválida')
    return locks.get(layer, False) is True


def center_layer_axis(
    state: tuple[int, ...], layer: str, axis: str,
    bounds: tuple[int, int], *, text: str = '', font_size: int = 16,
    horizontal: str = 'center', vertical: str = 'center',
) -> tuple[int, ...]:
    """Posiciona centro visual estimado no eixo solicitado, com clamp GTK.

    Imagem usa o centro de sua caixa (image_x/y=0). Texto pode estar alinhado
    à esquerda, direita, topo ou base: calcula o deslocamento necessário a
    partir da *mesma* aproximação geométrica usada no overlay de seleção.
    """
    if (len(state) != len(FIELDS) or any(type(value) is not int for value in state)
            or layer not in LAYERS or axis not in AXES
            or len(bounds) != 2 or any(type(value) is not int for value in bounds)
            or bounds[0] > bounds[1] or not isinstance(text, str)):
        raise ValueError('Centralização inválida')
    index = (0 if axis == 'x' else 1) + (0 if layer == 'image' else 3)
    if layer == 'image':
        target = 0
    else:
        if not text.strip():
            raise ValueError('Não há texto para centralizar')
        region = visual_element_regions(
            240, 240, 1.0,
            image_present=False, image_x=0, image_y=0, image_scale=100,
            text=text, show_text=True, offset_x=0, offset_y=0,
            font_size=font_size, horizontal=horizontal, vertical=vertical,
        )['text']
        # display_geometry(240, 240, 1) == (120, 120, 2.4)
        midpoint = (region.x + region.width / 2 if axis == 'x'
                    else region.y + region.height / 2)
        target = round((120.0 - midpoint) / 2.4)
    target = max(bounds[0], min(bounds[1], target))
    result = list(state)
    result[index] = target
    return tuple(result)
