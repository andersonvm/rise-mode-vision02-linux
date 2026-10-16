"""Camadas *lógicas* do editor LCD, sem GTK, YAML, IPC ou HID.

O hardware continua recebendo o PNG composto, sem edição de z-order.
A lista serve para selecionar Imagem/Texto e alternar regiões sobrepostas.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

from .studio_visual_selection import VisualRegion

LAYER_ORDER = ('image', 'text')
LAYER_TITLES = {'image': 'Imagem', 'text': 'Texto'}


def available_layers(*, image_path: str, text: str, show_text: bool) -> tuple[str, ...]:
    """Camadas editáveis presentes, em ordem visual fixa do renderizador."""
    if not isinstance(image_path, str) or not isinstance(text, str) or type(show_text) is not bool:
        raise ValueError('Dados de camadas inválidos')
    return tuple(key for key, present in (
        ('image', bool(image_path.strip())),
        ('text', bool(text.strip()) and show_text),
    ) if present)


def hit_layer_candidates(regions: Mapping[str, VisualRegion], x: float,
                         y: float) -> tuple[str, ...]:
    """Obtém todas as regiões aproximadas sob um ponto, sem impor prioridade."""
    if not (isinstance(x, (int, float)) and isinstance(y, (int, float))
            and math.isfinite(x) and math.isfinite(y)):
        return ()
    return tuple(key for key in LAYER_ORDER
                 if key in regions and regions[key].contains(x, y))


def next_overlapping_layer(regions: Mapping[str, VisualRegion], x: float,
                           y: float, current: str) -> str | None:
    """Alterna o alvo apenas quando os DOIS elementos ocupam o mesmo ponto."""
    if current not in LAYER_ORDER:
        raise ValueError('Camada selecionada inválida')
    candidates = hit_layer_candidates(regions, x, y)
    if len(candidates) != 2:
        return None
    return candidates[1] if current == candidates[0] else candidates[0]
