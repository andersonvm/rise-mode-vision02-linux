"""Interação da composição no Studio: zoom, alças, alinhamento e histórico.

Independente de GTK, USB/HID, arquivos de perfis e side effects. A única fonte
para renderizar e persistir continua sendo o renderizador YAML existente.
"""
from __future__ import annotations

from dataclasses import dataclass, field

FIELDS = ('image_x', 'image_y', 'image_scale', 'offset_x', 'offset_y')
DEFAULT = (0, 0, 100, 0, 0)
ZOOMS = (1.0, 1.5, 2.0)


def state_from_fields(spins) -> tuple[int, ...]:
    return tuple(int(spins[key].get_value()) for key in FIELDS)


def apply_state(spins, state: tuple[int, ...]) -> None:
    if len(state) != len(FIELDS) or any(type(value) is not int for value in state):
        raise ValueError('Estado de composição inválido')
    for key, value in zip(FIELDS, state):
        spins[key].set_value(value)


@dataclass
class CompositionHistory:
    limit: int = 64
    undo_stack: list[tuple[int, ...]] = field(default_factory=list)
    redo_stack: list[tuple[int, ...]] = field(default_factory=list)

    def __post_init__(self):
        if type(self.limit) is not int or self.limit < 1 or self.limit > 1000:
            raise ValueError('Limite de histórico inválido')

    def record(self, before: tuple[int, ...], after: tuple[int, ...]) -> bool:
        if len(before) != len(FIELDS) or len(after) != len(FIELDS):
            raise ValueError('Histórico de composição inválido')
        if before == after:
            return False
        self.undo_stack.append(before)
        del self.undo_stack[:-self.limit]
        self.redo_stack.clear()
        return True

    def undo(self, current: tuple[int, ...]) -> tuple[int, ...] | None:
        if not self.undo_stack:
            return None
        previous = self.undo_stack.pop()
        self.redo_stack.append(current)
        return previous

    def redo(self, current: tuple[int, ...]) -> tuple[int, ...] | None:
        if not self.redo_stack:
            return None
        subsequent = self.redo_stack.pop()
        self.undo_stack.append(current)
        return subsequent

    def clear(self):
        self.undo_stack.clear()
        self.redo_stack.clear()


def default_target(state: tuple[int, ...], target: str) -> tuple[int, ...]:
    if len(state) != 5 or target not in ('image', 'text'):
        raise ValueError('Alvo inválido')
    items = list(state)
    if target == 'image':
        items[:3] = DEFAULT[:3]
    else:
        items[3:] = DEFAULT[3:]
    return tuple(items)


def smart_snap(position: int, lower: int, upper: int, anchors: tuple[int, ...], tolerance=3):
    """Aproxima do centro/bordas somente dentro da tolerância (unidades LCD)."""
    if type(position) is not int or lower > upper or tolerance < 0:
        raise ValueError('Posição de alinhamento inválida')
    candidates = [value for value in anchors if lower <= value <= upper and abs(position-value) <= tolerance]
    if not candidates:
        return max(lower, min(upper, position)), None
    closest = min(candidates, key=lambda a: (abs(position-a), abs(a)))
    return closest, closest


def anchors_for_target(target: str, image_scale: int) -> tuple[int, ...]:
    if target == 'text':
        return (-40, 0, 40)
    if target != 'image' or not 25 <= image_scale <= 200:
        raise ValueError('Alvo ou escala inválida')
    margin = round((100 - image_scale) / 2)
    return tuple(sorted(set((margin, 0, -margin))))


def display_geometry(width: int, height: int, zoom: float) -> tuple[float, float, float]:
    """Origem e pixels de widget por unidade LCD (zoom centralizado)."""
    if width <= 0 or height <= 0 or zoom not in ZOOMS:
        raise ValueError('Geometria inválida')
    extent = min(width, height)
    return (width/2, height/2, extent/100 * zoom)


def image_handle_position(width: int, height: int, image_x: int, image_y: int,
                          scale: int, zoom: float) -> tuple[float, float]:
    cx, cy, unit = display_geometry(width, height, zoom)
    return cx + (image_x + scale/2) * unit, cy + (image_y + scale/2) * unit


def visible_handle_position(width: int, height: int, image_x: int, image_y: int,
                            scale: int, zoom: float) -> tuple[float, float]:
    hx, hy = image_handle_position(width, height, image_x, image_y, scale, zoom)
    return (max(12, min(width-12, hx)), max(12, min(height-12, hy)))


def hit_image_handle(x: float, y: float, width: int, height: int,
                     image_x: int, image_y: int, scale: int, zoom: float,
                     radius: float = 15) -> bool:
    hx, hy = visible_handle_position(width, height, image_x, image_y, scale, zoom)
    return abs(x-hx) <= radius and abs(y-hy) <= radius


def resize_image_scale(initial: int, dx: float, dy: float, unit: float,
                       lower: int = 25, upper: int = 200) -> int:
    if unit <= 0 or lower > upper or type(initial) is not int:
        raise ValueError('Parâmetros de redimensionamento inválidos')
    # Arrastar canto inferior direito: movimento diagonal de 24px, com
    # canvas=240px, zoom 1x, aumenta aproximadamente 20 pontos percentuais.
    change = round((dx + dy) / unit)
    return max(lower, min(upper, initial + change))
