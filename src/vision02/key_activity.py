"""Eventos das teclas para consulta IPC somente-leitura, sem novas leituras HID."""
from __future__ import annotations

import time
from collections.abc import Callable


class KeyActivity:
    """Acesso exclusivo pela thread que já consome os eventos HID."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, highlight_seconds: float = 1.8):
        self._clock = clock
        self._highlight_seconds = highlight_seconds
        self._pressed: set[int] = set()
        self._last_key: int | None = None
        self._last_at: float | None = None
        self._sequence = 0

    def record(self, key_id: int, pressed: bool) -> None:
        if type(key_id) is not int or not 1 <= key_id <= 15 or type(pressed) is not bool:
            raise ValueError('Evento físico inválido')
        if pressed:
            self._pressed.add(key_id)
            self._last_key = key_id
            self._last_at = self._clock()
            self._sequence += 1
        else:
            self._pressed.discard(key_id)

    def reset(self) -> None:
        """Descarta retenções antigas depois de troca de perfil ou reload."""
        self._pressed.clear()

    def snapshot(self) -> dict:
        elapsed = self._clock() - self._last_at if self._last_at is not None else None
        recent = elapsed is not None and 0 <= elapsed <= self._highlight_seconds
        return {
            'pressed_keys': sorted(self._pressed),
            'last_key': self._last_key if recent else None,
            'sequence': self._sequence,
        }
