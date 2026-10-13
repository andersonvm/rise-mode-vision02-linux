"""Transporte Linux hidraw com descoberta por VID/PID (sem dependência hidapi)."""
from __future__ import annotations

import os
import select
import threading
import time
from pathlib import Path
from typing import Callable

from .display import encode_image, numbered_image
from .protocol import INIT_PAYLOADS, REPORT_SIZE, command, image_reports, parse_key_report, physical_key_to_display_id

HID_ID = "0003:00000A00:00001000"


def find_device(sysfs: Path = Path("/sys/class/hidraw")) -> Path:
    for entry in sorted(sysfs.glob("hidraw*")):
        uevent = entry / "device" / "uevent"
        if uevent.is_file() and f"HID_ID={HID_ID}" in uevent.read_text():
            return Path("/dev") / entry.name
    raise FileNotFoundError("Vision 02 indisponível via hidraw; desconecte-a da VM e confira usbhid")


class Vision02:
    def __init__(self, path: str | Path | None = None, *, report_delay: float = 0.005, display_delay: float = 0.1):
        self.path = Path(path) if path else None
        self.report_delay = report_delay
        self.display_delay = display_delay
        self._fd: int | None = None
        self._faulted = False
        self._last_error: OSError | None = None
        self._session_lock = threading.RLock()
        self._write_lock = threading.RLock()
        self._listeners: dict[int, list[Callable[[int], None]]] = {}
        self._release_listeners: dict[int, list[Callable[[int], None]]] = {}

    def __enter__(self) -> "Vision02":
        self.open()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def open(self) -> None:
        with self._session_lock:
            if self._fd is not None:
                if self._faulted:
                    raise RuntimeError(
                        "Sessão HID em falha; execute reconnect()"
                    )
                return

            self.path = find_device() if self.path is None else self.path
            self._fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
            self._faulted = False
            self._last_error = None

            try:
                self.initialize()
            except Exception:
                self.close()
                raise

    @property
    def faulted(self) -> bool:
        return self._faulted

    @property
    def last_error(self) -> OSError | None:
        return self._last_error

    def reconnect(self) -> None:
        with self._session_lock:
            """Reconecta explicitamente; não reenvia imagens."""
            self.close()
            self.path = None
            self.open()

    def _record_failure(self, exc: OSError) -> None:
        self._faulted = True
        self._last_error = exc

    def close(self) -> None:
        with self._session_lock:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None

    def _write(self, data: bytes) -> None:
        if self._fd is None:
            raise RuntimeError("Dispositivo não está aberto")

        if self._faulted:
            raise RuntimeError(
                "Sessão HID em falha; execute reconnect()"
            )

        if len(data) != REPORT_SIZE:
            raise ValueError("Relatório deve ter 512 bytes")

        with self._write_lock:
            deadline = time.monotonic() + 2.0

            try:
                while True:
                    try:
                        written = os.write(self._fd, data)
                        break

                    except BlockingIOError:
                        remaining = deadline - time.monotonic()

                        if remaining <= 0:
                            raise TimeoutError(
                                "Timeout aguardando escrita HID"
                            )

                        _, writable, _ = select.select(
                            [], [self._fd], [], remaining
                        )

                        if not writable:
                            raise TimeoutError(
                                "Timeout aguardando escrita HID"
                            )

                if written != REPORT_SIZE:
                    raise OSError(
                        f"Escrita HID incompleta: "
                        f"{written}/{REPORT_SIZE}"
                    )

            except OSError as exc:
                self._record_failure(exc)
                raise

    def initialize(self) -> None:
        with self._session_lock:
            for payload in INIT_PAYLOADS:
                self._write(command(payload))
                time.sleep(0.01)
            time.sleep(0.2)

    def set_image(self, display_id: int, source, *, quality: int = 90, subsampling: int = 0) -> None:
        with self._session_lock:
            jpeg = encode_image(source, quality=quality, subsampling=subsampling)
            with self._write_lock:
                for report in image_reports(display_id, jpeg):
                    self._write(report)
                    time.sleep(self.report_delay)
                self._write(command(b"STP"))
                time.sleep(self.display_delay)

    def set_image_for_key(self, physical_key: int, source, *, quality: int = 90, subsampling: int = 0) -> None:
        self.set_image(physical_key_to_display_id(physical_key), source, quality=quality, subsampling=subsampling)

    def show_numbers(self) -> None:
        for display_id in range(1, 16):
            self.set_image(display_id, numbered_image(display_id))

    def on_press(self, key_id: int, callback: Callable[[int], None]) -> None:
        self._add_listener(key_id, callback, self._listeners)

    def on_release(self, key_id: int, callback: Callable[[int], None]) -> None:
        self._add_listener(key_id, callback, self._release_listeners)

    @staticmethod
    def _add_listener(key_id: int, callback, registry) -> None:
        if not 1 <= key_id <= 15:
            raise ValueError("ID de tecla deve estar entre 1 e 15")
        registry.setdefault(key_id, []).append(callback)

    def read_event(self, timeout: float = 0.5) -> tuple[int, bool] | None:
        with self._session_lock:
            if self._fd is None:
                raise RuntimeError("Dispositivo não está aberto")
            if self._faulted:
                raise RuntimeError(
                    "Sessão HID em falha; execute reconnect()"
                )

            try:
                readable, _, _ = select.select(
                    [self._fd], [], [], timeout
                )

                if not readable:
                    return None

                try:
                    packet = os.read(self._fd, REPORT_SIZE)
                except BlockingIOError:
                    return None

                if not packet:
                    raise OSError("Vision 02 desconectada")

            except OSError as exc:
                self._record_failure(exc)
                raise

            return parse_key_report(packet)

    def run(self, stop_event: threading.Event | None = None) -> None:
        while stop_event is None or not stop_event.is_set():
            event = self.read_event(0.2)
            if event is None:
                continue
            key, pressed = event
            listeners = self._listeners if pressed else self._release_listeners
            for callback in listeners.get(key, []):
                callback(key)
