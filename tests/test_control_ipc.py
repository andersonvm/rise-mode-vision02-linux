"""Testes offline do controle local: não abrem USB, não enviam teclas."""
import json
import os
from pathlib import Path
import socket
import stat
import threading
import time

import pytest

from vision02.control_ipc import ControlServer, _read_line, _validate_request, request, socket_path


def pump(server, thread, handler=None):
    handler = handler or (lambda command, target: {"active": target or "Desenvolvimento"})
    deadline = time.monotonic() + 3
    while thread.is_alive() and time.monotonic() < deadline:
        server.process_pending(handler)
        time.sleep(0.005)
    thread.join(timeout=1)
    assert not thread.is_alive()


def dispatch(server, cmd, name=None, handler=None):
    results = []
    thread = threading.Thread(target=lambda: results.append(request(cmd, name, path=server.path, timeout=4)))
    thread.start()
    pump(server, thread, handler)
    return results[0]


def test_status_no_hid(tmp_path):
    server = ControlServer(tmp_path / "vision02" / "control.sock")
    server.start()
    try:
        result = dispatch(server, "status", handler=lambda op, target: {"connected": True, "active": "Desenvolvimento"})
        assert result == {"ok": True, "connected": True, "active": "Desenvolvimento"}
    finally:
        server.close()


def test_switch_is_run_on_owner_thread(tmp_path):
    server = ControlServer(tmp_path / "vision02" / "control.sock")
    server.start()
    owner = threading.get_ident()
    seen = []
    try:
        def handler(op, target):
            seen.append((threading.get_ident(), op, target))
            return {"active": target, "changed": True}
        result = dispatch(server, "switch", "Observabilidade", handler)
        assert result["active"] == "Observabilidade"
        assert seen == [(owner, "switch", "Observabilidade")]
    finally:
        server.close()


def test_profiles_list(tmp_path):
    with_server = ControlServer(tmp_path / "vision02" / "control.sock")
    with_server.start()
    try:
        result = dispatch(with_server, "profiles", handler=lambda op, target: {"profiles": ["A", "B"]})
        assert result["profiles"] == ["A", "B"]
    finally:
        with_server.close()


def test_handler_failure_returns_error_and_server_recovers(tmp_path):
    server = ControlServer(tmp_path / "vision02" / "control.sock")
    server.start()
    try:
        reply = dispatch(server, "switch", "Inexistente", lambda op, target: (_ for _ in ()).throw(ValueError("perfil inexistente")))
        assert reply == {"ok": False, "error": "perfil inexistente"}
        assert dispatch(server, "status")["ok"]
    finally:
        server.close()


@pytest.mark.parametrize("body", [
    {"command": "run", "argv": ["rm", "-rf"]},
    {"command": "switch"},
    {"command": "switch", "target": ""},
    {"command": "switch", "target": " A"},
    {"command": "status", "target": "A"},
    [],
    {},
])
def test_reject_unknown_or_malformed_commands(body):
    with pytest.raises(ValueError):
        _validate_request(body)


def test_socket_is_private_and_removed(tmp_path):
    path = tmp_path / "vision02" / "control.sock"
    server = ControlServer(path)
    server.start()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    server.close()
    assert not path.exists()


def test_no_second_server(tmp_path):
    path = tmp_path / "vision02" / "control.sock"
    first = ControlServer(path)
    first.start()
    try:
        second = ControlServer(path)
        with pytest.raises(RuntimeError, match="já possui servidor"):
            second.start()
        assert path.exists()
    finally:
        first.close()


def test_recover_stale_socket(tmp_path):
    path = tmp_path / "vision02" / "control.sock"
    path.parent.mkdir()
    sock = socket.socket(socket.AF_UNIX)
    sock.bind(str(path))
    sock.close()  # Stale socket left behind by killed process
    server = ControlServer(path)
    server.start()
    assert path.exists()
    server.close()


def test_reject_symlink(tmp_path):
    path = tmp_path / "vision02" / "control.sock"
    path.parent.mkdir()
    path.symlink_to(tmp_path / "target")
    server = ControlServer(path)
    with pytest.raises(RuntimeError, match="symlink"):
        server.start()
    assert path.is_symlink()


def test_client_without_running_server(tmp_path):
    with pytest.raises(ConnectionError, match="indisponível"):
        request("status", path=tmp_path / "missing.sock")


def test_runtime_path(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert socket_path() == tmp_path / "vision02" / "control.sock"


def test_runtime_required(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    with pytest.raises(RuntimeError, match="XDG_RUNTIME_DIR"):
        socket_path()


def test_max_bytes_rejected():
    a, b = socket.socketpair()
    try:
        b.sendall(b"x" * 5000)
        with pytest.raises(ValueError, match="limite"):
            _read_line(a)
    finally:
        a.close()
        b.close()
