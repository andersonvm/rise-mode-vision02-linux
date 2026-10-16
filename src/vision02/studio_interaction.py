"""Detecção de clique duplo sem interferir no Gtk.Button.

O Gtk.Button já emite clicked; contar clicks ali evita competir com os
controladores Gtk.GestureClick internos do widget.
"""
from __future__ import annotations

import time
from collections.abc import Callable


class DoubleClickDetector:
    def __init__(self, *, interval_seconds: float = 0.6,
                 clock: Callable[[], float] = time.monotonic):
        if not (0.15 <= interval_seconds <= 2.0):
            raise ValueError('Intervalo de clique duplo inválido')
        self.interval = interval_seconds
        self.clock = clock
        self.last_key: int | None = None
        self.last_time: float | None = None

    def click(self, key_id: int) -> bool:
        if type(key_id) is not int or not 1 <= key_id <= 15:
            raise ValueError('Tecla física inválida')
        now = self.clock()
        double = (self.last_key == key_id and self.last_time is not None
                  and 0 <= now - self.last_time <= self.interval)
        if double:
            self.last_key = None
            self.last_time = None
            return True
        self.last_key = key_id
        self.last_time = now
        return False
