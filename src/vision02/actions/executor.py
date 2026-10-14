"""Executor de ações sem interpretação de comandos pelo shell."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
from urllib.parse import urlsplit

from vision02.profiles.models import Action


class ActionExecutionError(RuntimeError):
    """Falha ao iniciar uma ação configurada."""


_wayland_lock = threading.Lock()
_wayland_keyboard = None


def _get_wayland_keyboard():
    """Cria um backend somente no primeiro atalho Wayland."""
    global _wayland_keyboard
    with _wayland_lock:
        if _wayland_keyboard is None:
            from vision02.actions.wayland_portal import WaylandPortalKeyboard
            _wayland_keyboard = WaylandPortalKeyboard()
        return _wayland_keyboard


def close_wayland_keyboard() -> None:
    """Libera a autorização e encerra a conexão D-Bus do processo."""
    global _wayland_keyboard
    with _wayland_lock:
        keyboard, _wayland_keyboard = _wayland_keyboard, None
    if keyboard is not None:
        keyboard.close()


def execute_action(action: Action) -> None:
    """Executa uma ação previamente validada.

    Perfis devem ser carregados de fontes confiáveis.
    """

    if action.type == "command":
        if not action.argv:
            raise ActionExecutionError(
                "Ação command sem argumentos"
            )

        try:
            subprocess.Popen(
                list(action.argv),
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as exc:
            raise ActionExecutionError(
                f"Falha ao iniciar comando: {action.argv[0]}"
            ) from exc

        return

    if action.type == "script":
        script = action.script_path
        if script is None or not script.is_file():
            raise ActionExecutionError("Script não encontrado")
        programs = {"bash": "bash", "python3": sys.executable}
        program = programs.get(action.interpreter)
        if program is None:
            raise ActionExecutionError("Interpretador de script inválido")
        try:
            subprocess.Popen(
                [program, str(script), *action.argv],
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as exc:
            raise ActionExecutionError(f"Falha ao iniciar script: {script}") from exc
        return

    if action.type == "hotkey":
        keys = action.keys
        if (
            not 1 <= len(keys) <= 5
            or not all(
                isinstance(key, str)
                and re.fullmatch(r"[A-Za-z0-9_]+", key)
                for key in keys
            )
        ):
            raise ActionExecutionError("Teclas do atalho inválidas")
        session = os.environ.get("XDG_SESSION_TYPE", "").lower()
        if session == "wayland":
            try:
                _get_wayland_keyboard().send(keys)
            except (ImportError, OSError, RuntimeError) as exc:
                raise ActionExecutionError(
                    f"Falha no atalho GNOME Wayland: {exc}"
                ) from exc
            return
        if session != "x11":
            raise ActionExecutionError(
                f"Sessão gráfica não suportada para atalhos: {session!r}"
            )
        xdotool = shutil.which("xdotool")
        if not xdotool:
            raise ActionExecutionError("xdotool não encontrado; instale xdotool")
        try:
            subprocess.run(
                [xdotool, "key", "--clearmodifiers", "+".join(keys)],
                shell=False,
                check=True,
                timeout=5,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ActionExecutionError("Falha no atalho de teclado") from exc
        return

    if action.type == "url":
        if not action.url:
            raise ActionExecutionError(
                "Ação url sem endereço"
            )

        try:
            parsed = urlsplit(action.url)
            valid = (
                parsed.scheme in {"http", "https"}
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
            )
            if valid:
                parsed.port
        except ValueError:
            valid = False

        if not valid:
            raise ActionExecutionError(
                "URL inválida ou protocolo não permitido"
            )

        if not webbrowser.open(action.url):
            raise ActionExecutionError(
                "Nenhum navegador disponível para abrir a URL"
            )

        return

    raise ActionExecutionError(
        f"Tipo de ação não suportado: {action.type!r}"
    )
