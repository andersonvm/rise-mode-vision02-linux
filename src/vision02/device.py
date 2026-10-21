"""Transporte Linux hidraw com descoberta por VID/PID (sem dependência hidapi)."""
from __future__ import annotations

import os
from contextlib import contextmanager
from hashlib import sha256
import select
import threading
import time
from pathlib import Path
from typing import Callable
from collections.abc import Mapping

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
        self._condition = threading.Condition(self._session_lock)
        self._lifecycle_lock = threading.Lock()
        self._active = 0
        self._closing = False
        self._lifecycle_owner = None
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._display_cache: dict[int, bytes] = {}
        self._listeners: dict[int, list[Callable[[int], None]]] = {}
        self._release_listeners: dict[int, list[Callable[[int], None]]] = {}

    def __enter__(self) -> "Vision02":
        self.open()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    @contextmanager
    def _operation(self):
        if getattr(self._local, "depth", 0):
            self._local.depth += 1
            try:
                yield self._fd
            finally:
                self._local.depth -= 1
            return
        with self._condition:
            if self._closing and self._lifecycle_owner != threading.get_ident():
                raise RuntimeError("Sessão HID em encerramento")
            if self._fd is None:
                raise RuntimeError("Dispositivo não está aberto")
            if self._faulted:
                raise RuntimeError("Sessão HID em falha; execute reconnect()")
            self._active += 1
            self._local.depth = 1
            fd = self._fd
        try:
            yield fd
        finally:
            with self._condition:
                self._local.depth = 0
                self._active -= 1
                self._condition.notify_all()

    @contextmanager
    def _transition(self):
        if getattr(self._local, "depth", 0):
            raise RuntimeError("Ciclo de vida chamado durante operação HID")
        with self._lifecycle_lock:
            with self._condition:
                self._closing = True
                self._lifecycle_owner = threading.get_ident()
                self._condition.notify_all()
            try:
                with self._condition:
                    while self._active:
                        self._condition.wait()
                yield
            finally:
                with self._condition:
                    self._closing = False
                    self._lifecycle_owner = None
                    self._condition.notify_all()

    def _open_session(self) -> None:
        if self._fd is not None:
            if self._faulted:
                raise RuntimeError("Sessão HID em falha; execute reconnect()")
            return
        self.path = find_device() if self.path is None else self.path
        self._fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        self._faulted = False
        self._last_error = None
        self._display_cache.clear()
        try:
            self.initialize()
        except BaseException:
            self._close_session()
            raise

    def open(self) -> None:
        with self._transition():
            self._open_session()

    @property
    def faulted(self) -> bool:
        with self._condition:
            return self._faulted

    @property
    def last_error(self) -> OSError | None:
        with self._condition:
            return self._last_error

    def reconnect(self) -> None:
        """Reconecta explicitamente; não reenvia imagens."""
        with self._transition():
            self._close_session()
            self.path = None
            self._open_session()

    def _record_failure(self, exc: OSError) -> None:
        with self._condition:
            self._faulted = True
            self._last_error = exc
            self._display_cache.clear()

    def _close_session(self) -> None:
        fd = self._fd
        self._fd = None
        self._display_cache.clear()
        if fd is not None:
            os.close(fd)

    def close(self) -> None:
        with self._transition():
            self._close_session()

    def _write(self, data: bytes) -> None:
        if len(data) != REPORT_SIZE:
            raise ValueError("Relatório deve ter 512 bytes")
        packet = b"\x00" + data
        with self._operation() as fd, self._write_lock:
            if self.faulted:
                raise RuntimeError("Sessão HID em falha; execute reconnect()")
            deadline = time.monotonic() + 2.0

            try:
                while True:
                    try:
                        written = os.write(fd, packet)
                        break

                    except BlockingIOError:
                        remaining = deadline - time.monotonic()

                        if remaining <= 0:
                            raise TimeoutError(
                                "Timeout aguardando escrita HID"
                            )

                        _, writable, _ = select.select(
                            [], [fd], [], remaining
                        )

                        if not writable:
                            raise TimeoutError(
                                "Timeout aguardando escrita HID"
                            )

                if written != len(packet):
                    raise OSError(
                        f"Escrita HID incompleta: "
                        f"{written}/{len(packet)}"
                    )

            except OSError as exc:
                self._record_failure(exc)
                raise

    @contextmanager
    def _transmission(self):
        with self._operation(), self._write_lock:
            if self.faulted:
                raise RuntimeError("Sessão HID em falha; execute reconnect()")
            try:
                yield
            except BaseException as exc:
                # A partial sequence cannot safely be resumed, even on Ctrl+C.
                if not self.faulted:
                    self._record_failure(
                        exc if isinstance(exc, OSError)
                        else OSError("Transmissão HID interrompida")
                    )
                raise

    def initialize(self) -> None:
        with self._transmission():
            for payload in INIT_PAYLOADS:
                self._write(command(payload))
                time.sleep(0.01)
            time.sleep(0.2)

    def set_images_batch(
        self,
        sources: Mapping[int, object],
        *,
        quality: int = 90,
        subsampling: int = 0,
    ) -> None:
        """Inicializa os 15 LCDs em um único lote, conforme captura Windows.

        Toda imagem é codificada antes de enviar CLE FF. O lote mantém o
        bloqueio de escrita HID até o STP final; o cache só é atualizado
        depois da conclusão. Atualizações posteriores usam set_image().
        """
        images = dict(sources)
        expected = set(range(1, 16))
        if set(images) != expected:
            raise ValueError("O lote inicial exige exatamente os displays 1 a 15")

        with self._operation():
            prepared = {
                display_id: encode_image(
                    images[display_id], quality=quality, subsampling=subsampling
                )
                for display_id in sorted(images)
            }
            digests = {
                display_id: sha256(jpeg).digest()
                for display_id, jpeg in prepared.items()
            }

            with self._transmission():
                self._write(command(b"CLE\x00\x00\x00\xff"))

                for display_id, jpeg in prepared.items():
                    for report in image_reports(display_id, jpeg):
                        self._write(report)
                        time.sleep(self.report_delay)

                self._write(command(b"STP"))
                time.sleep(self.display_delay)

                with self._condition:
                    if self._faulted:
                        raise RuntimeError(
                            "Sessão HID em falha; execute reconnect()"
                        )
                    self._display_cache.clear()
                    self._display_cache.update(digests)

    def set_image(
        self,
        display_id: int,
        source,
        *,
        quality: int = 90,
        subsampling: int = 0,
        skip_unchanged: bool = False,
    ) -> None:
        with self._operation():
            jpeg = encode_image(
                source,
                quality=quality,
                subsampling=subsampling,
            )
            digest = sha256(jpeg).digest()

            with self._transmission():
                with self._condition:
                    if self._faulted:
                        raise RuntimeError(
                            "Sessão HID em falha; execute reconnect()"
                        )
                    if (
                        skip_unchanged
                        and self._display_cache.get(display_id) == digest
                    ):
                        return

                for report in image_reports(display_id, jpeg):
                    self._write(report)
                    time.sleep(self.report_delay)

                self._write(command(b"STP"))

                time.sleep(self.display_delay)

                # Atualizar somente se a transmissão terminou
                # e nenhuma outra thread invalidou a sessão.
                with self._condition:
                    if self._faulted:
                        raise RuntimeError(
                            "Sessão HID em falha; execute reconnect()"
                        )
                    self._display_cache[display_id] = digest

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

    def read_event(self, timeout: float | None = 0.5) -> tuple[int, bool] | None:
        with self._operation() as fd:
            deadline = None if timeout is None else time.monotonic() + max(0, timeout)
            try:
                while True:
                    with self._condition:
                        if self._closing:
                            return None
                        if self._faulted:
                            raise RuntimeError("Sessão HID em falha; execute reconnect()")
                    remaining = 0.05 if deadline is None else max(0, deadline - time.monotonic())
                    readable, _, _ = select.select([fd], [], [], min(0.05, remaining))
                    if readable or (deadline is not None and time.monotonic() >= deadline):
                        break

                if not readable:
                    return None

                try:
                    packet = os.read(fd, REPORT_SIZE)
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
