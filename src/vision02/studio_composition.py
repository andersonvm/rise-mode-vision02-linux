"""Pure layout helpers: GTK independent and safe for keyboard/drag editing."""
from __future__ import annotations


def clamp_drag(start: int, distance: float, pixels_per_unit: float,
               lower: int, upper: int) -> int:
    """Convert widget drag pixels to LCD units, clamped to a field range."""
    if pixels_per_unit <= 0:
        raise ValueError('Zoom inválido')
    if type(start) is not int or type(lower) is not int or type(upper) is not int or lower > upper:
        raise ValueError('Parâmetros de posição inválidos')
    return min(upper, max(lower, round(start + distance / pixels_per_unit)))


def grid_coordinate(position: int, lower: int, upper: int, step: int = 5) -> int:
    """Snap to the nearest absolute LCD grid position without going out of bounds."""
    if step < 1:
        raise ValueError('Passo inválido')
    return min(upper, max(lower, round(position / step) * step))
