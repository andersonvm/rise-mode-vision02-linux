"""Geometria e transformações locais do canvas de presets v13.

Sem GTK, arquivos, YAML, IPC ou acesso USB/HID. A transformação retorna um
novo rascunho; a gravação continua exclusivamente no editor v12.
"""
from __future__ import annotations

import math

from .studio_composition_v2 import (
    ZOOMS, anchors_for_target, display_geometry, hit_image_handle,
    resize_image_scale, smart_snap,
)
from .studio_visual_selection import visual_element_regions

POSITION_LIMITS = {'image': (-100, 100), 'text': (-40, 40)}


def _style(appearance: dict) -> dict:
    if not isinstance(appearance, dict):
        raise ValueError('Aparência inválida')
    return appearance


def canvas_regions(appearance: dict, *, image_present: bool, width: int,
                   height: int, zoom: float):
    """Regiões estimadas, compatíveis com a composição v3 (não pixel-perfect)."""
    s = _style(appearance)
    return visual_element_regions(
        width, height, zoom, image_present=bool(image_present),
        image_x=s['image_x'], image_y=s['image_y'], image_scale=s['image_scale'],
        text=s.get('text') or 'Prévia', show_text=s['show_text'],
        offset_x=s['offset_x'], offset_y=s['offset_y'],
        font_size=s['font_size'], horizontal=s['horizontal'], vertical=s['vertical'],
    )


def select_at(appearance: dict, *, image_present: bool, width: int, height: int,
              zoom: float, x: float, y: float, preferred: str = 'image') -> str | None:
    """Prioriza o elemento já selecionado quando as regiões se sobrepõem."""
    if preferred not in POSITION_LIMITS or not all(math.isfinite(v) for v in (x, y)):
        raise ValueError('Seleção inválida')
    if width <= 0 or height <= 0 or zoom not in ZOOMS:
        return None
    regions = canvas_regions(appearance, image_present=image_present,
                             width=width, height=height, zoom=zoom)
    if x < 0 or y < 0 or x > width or y > height:
        return None
    for key in (preferred, 'text' if preferred == 'image' else 'image'):
        if key in regions and regions[key].contains(x, y):
            return key
    return None


def resize_hit(appearance: dict, *, image_present: bool, width: int, height: int,
               zoom: float, x: float, y: float) -> bool:
    if not image_present or width <= 0 or height <= 0 or zoom not in ZOOMS:
        return False
    s = _style(appearance)
    return hit_image_handle(x, y, width, height, s['image_x'], s['image_y'],
                            s['image_scale'], zoom, radius=15)


def transform(appearance: dict, target: str, operation: str, dx: float, dy: float,
              width: int, height: int, zoom: float, *, snap: bool = True
              ) -> tuple[dict, tuple[int | None, int | None]]:
    """Retorna (novo estilo, guias) sem alterar a entrada.

    Os deslocamentos dx/dy são relativos ao início do gesto, *não* incrementais.
    """
    if target not in POSITION_LIMITS or operation not in ('move', 'resize'):
        raise ValueError('Transformação inválida')
    if operation == 'resize' and target != 'image':
        raise ValueError('Somente imagens permitem redimensionamento')
    if type(snap) is not bool or not all(math.isfinite(v) for v in (dx, dy)):
        raise ValueError('Deslocamento inválido')
    s = _style(appearance)
    _cx, _cy, unit = display_geometry(width, height, zoom)
    result = dict(s)
    if operation == 'resize':
        result['image_scale'] = resize_image_scale(s['image_scale'], dx, dy, unit)
        return result, (None, None)
    lo, hi = POSITION_LIMITS[target]
    keys = ('image_x', 'image_y') if target == 'image' else ('offset_x', 'offset_y')
    anchors = anchors_for_target(target, s['image_scale'])
    guides = []
    for key, offset in zip(keys, (dx, dy)):
        position = max(lo, min(hi, s[key] + round(offset / unit)))
        if snap:
            position, guide = smart_snap(position, lo, hi, anchors)
        else:
            guide = None
        result[key] = position
        guides.append(guide)
    return result, (guides[0], guides[1])
