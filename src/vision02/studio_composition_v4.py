"""Ajuste fino local da composição do Vision 02 (sem GTK, YAML ou IPC).

As coordenadas usam unidades lógicas do LCD. Cada ajuste é uma operação
independente no histórico da interface; este módulo não altera estado externo.
"""
from __future__ import annotations

from .studio_composition_v2 import FIELDS, anchors_for_target

_DIRECTIONS = {'left': (-1, 0), 'right': (1, 0),
               'up': (0, -1), 'down': (0, 1)}


def nudge_state(state: tuple[int, ...], target: str, direction: str,
                step: int, bounds: tuple[int, int]) -> tuple[int, ...]:
    """Desloca o elemento em 1 ou 5 px e respeita o limite do controle GTK.

    O encaixe de arraste NÃO participa do ajuste fino: é possível chegar a
    qualquer coordenada válida, inclusive próxima de uma guia.
    """
    if (len(state) != len(FIELDS) or any(type(x) is not int for x in state)
            or target not in ('image', 'text') or direction not in _DIRECTIONS
            or type(step) is not int or step not in (1, 5)
            or len(bounds) != 2 or any(type(x) is not int for x in bounds)
            or bounds[0] > bounds[1]):
        raise ValueError('Ajuste fino de composição inválido')
    x_index, y_index = (0, 1) if target == 'image' else (3, 4)
    dx, dy = _DIRECTIONS[direction]
    result = list(state)
    for index, delta in ((x_index, dx), (y_index, dy)):
        result[index] = max(bounds[0], min(bounds[1], state[index] + delta * step))
    return tuple(result)


def guides_at_position(state: tuple[int, ...], target: str) -> tuple[int | None, int | None]:
    """Guias apenas para alinhamento exato, sem modificar coordenadas."""
    if len(state) != len(FIELDS) or target not in ('image', 'text'):
        raise ValueError('Estado de guias inválido')
    anchors = anchors_for_target(target, state[2])
    x, y = (state[0], state[1]) if target == 'image' else (state[3], state[4])
    return (x if x in anchors else None, y if y in anchors else None)


def coordinate_caption(state: tuple[int, ...], target: str) -> str:
    """Indicador legível do elemento selecionado, inclusive sem arrastar."""
    if len(state) != len(FIELDS) or target not in ('image', 'text'):
        raise ValueError('Estado de coordenadas inválido')
    if target == 'image':
        return f'Imagem: X={state[0]} px, Y={state[1]} px, escala={state[2]}%'
    return f'Texto: X={state[3]} px, Y={state[4]} px'
