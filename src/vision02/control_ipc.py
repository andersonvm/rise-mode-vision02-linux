"""Canal local de controle da Vision 02 (sem abrir USB/HID).

O processo que controla o HID publica um socket Unix privado; chamadas
remotas são encaminhadas à sua thread principal para serializar as trocas.
"""
from __future__ import annotations

import errno
import fcntl
import json
import os
from pathlib import Path
import queue
import socket
import stat
import struct
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

MAX_BYTES = 4096
RESPONSE_TIMEOUT = 45.0


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        raise RuntimeError("XDG_RUNTIME_DIR não definido na sessão gráfica")
    return Path(runtime) / "vision02" / "control.sock"


def _encode(obj: dict[str, Any]) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _read_line(connection: socket.socket) -> bytes:
    result = bytearray()
    while len(result) <= MAX_BYTES:
        chunk = connection.recv(min(1024, MAX_BYTES + 1 - len(result)))
        if not chunk:
            raise ValueError("Requisição encerrada sem newline")
        result.extend(chunk)
        if b"\n" in chunk:
            content, _, trailing = result.partition(b"\n")
            if trailing:
                raise ValueError("Apenas uma mensagem é permitida")
            if len(content) > MAX_BYTES:
                raise ValueError("Mensagem excede limite")
            return bytes(content)
    raise ValueError("Mensagem excede limite")


def _validate_request(raw: Any) -> tuple[str, str | None]:
    if not isinstance(raw, dict):
        raise ValueError("Mensagem deve ser um objeto JSON")
    command = raw.get("command")
    if command in ("status", "profiles") and set(raw) == {"command"}:
        return command, None
    if command == "switch" and set(raw) == {"command", "target"}:
        target = raw["target"]
        if isinstance(target, str) and 1 <= len(target) <= 128 and target.strip() == target:
            return command, target
    raise ValueError("Comando inválido; use status, profiles ou switch(target)")


@dataclass
class _Request:
    command: str
    target: str | None
    finished: threading.Event = field(default_factory=threading.Event)
    reply: dict[str, Any] = field(default_factory=dict)


class ControlServer:
    """Socket Unix com permissões locais e fila processada pela thread HID."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else socket_path()
        self._requests: queue.Queue[_Request] = queue.Queue(maxsize=16)
        self._closing = threading.Event()
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None
        self._lock_fd: int | None = None
        self._inode: int | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Servidor já iniciado")
        root = self.path.parent
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise PermissionError("Diretório IPC inválido ou de outro usuário")
        root.chmod(0o700)

        lock_path = root / "control.lock"
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(lock_path, flags, 0o600)
        self._lock_fd = fd
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.close()
            raise RuntimeError("A Vision 02 já possui servidor IPC ativo") from exc
        os.fchmod(fd, 0o600)

        try:
            if self.path.is_symlink():
                raise RuntimeError("Socket IPC não pode ser symlink")
            if self.path.exists():
                entry = self.path.lstat()
                if not stat.S_ISSOCK(entry.st_mode) or entry.st_uid != os.getuid():
                    raise PermissionError("Caminho IPC existente não é socket próprio")
                # Lock exclusivo garante que a instância anterior morreu.
                self.path.unlink()
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock = sock
            sock.bind(str(self.path))
            self.path.chmod(0o600)
            self._inode = self.path.stat().st_ino
            sock.listen(8)
            sock.settimeout(0.2)
            self._thread = threading.Thread(target=self._serve, name="vision02-ipc", daemon=True)
            self._thread.start()
        except BaseException:
            self.close()
            raise

    def _serve(self) -> None:
        assert self._sock is not None
        while not self._closing.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._closing.is_set():
                    break
                continue
            with conn:
                try:
                    conn.settimeout(1.0)
                    if hasattr(socket, "SO_PEERCRED"):
                        credentials = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                        _, uid, _ = struct.unpack("3i", credentials)
                        if uid != os.getuid():
                            raise PermissionError("Usuário não autorizado")
                    command, target = _validate_request(json.loads(_read_line(conn)))
                    req = _Request(command, target)
                    try:
                        self._requests.put_nowait(req)
                    except queue.Full:
                        raise RuntimeError("Fila IPC cheia")
                    if not req.finished.wait(RESPONSE_TIMEOUT):
                        raise TimeoutError("Controlador demorou a responder")
                    response = req.reply
                except (ValueError, UnicodeError, PermissionError, RuntimeError, TimeoutError, OSError) as exc:
                    response = {"ok": False, "error": str(exc)}
                try:
                    conn.sendall(_encode(response))
                except OSError:
                    pass

    def process_pending(self, handler: Callable[[str, str | None], dict[str, Any]], limit: int = 8) -> None:
        """Chamar APENAS na thread que também lê e escreve HID."""
        for _ in range(limit):
            try:
                request = self._requests.get_nowait()
            except queue.Empty:
                break
            try:
                data = handler(request.command, request.target)
                request.reply = {"ok": True, **data}
            except Exception as exc:
                request.reply = {"ok": False, "error": str(exc)}
            finally:
                request.finished.set()

    def close(self) -> None:
        self._closing.set()
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        # Desbloqueia clientes pendentes no encerramento.
        while True:
            try:
                req = self._requests.get_nowait()
            except queue.Empty:
                break
            req.reply = {"ok": False, "error": "Controlador encerrado"}
            req.finished.set()
        if self._inode is not None:
            try:
                if self.path.lstat().st_ino == self._inode:
                    self.path.unlink()
            except FileNotFoundError:
                pass
            self._inode = None
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None


def request(command: str, target: str | None = None, *, path: Path | None = None, timeout: float = 50.0) -> dict[str, Any]:
    """Cliente para CLI ou GUI: não abre dispositivo, nem subprocessos."""
    payload: dict[str, Any] = {"command": command}
    if target is not None:
        payload["target"] = target
    _validate_request(payload)
    target_path = path if path is not None else socket_path()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        try:
            conn.connect(str(target_path))
        except (FileNotFoundError, ConnectionRefusedError) as exc:
            raise ConnectionError("Controlador Vision 02 indisponível; confira vision02.service") from exc
        conn.sendall(_encode(payload))
        data = _read_line(conn)
    response = json.loads(data)
    if not isinstance(response, dict) or not isinstance(response.get("ok"), bool):
        raise ValueError("Resposta IPC inválida")
    return response
