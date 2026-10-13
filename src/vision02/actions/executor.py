"""Executor de ações sem interpretação de comandos pelo shell."""

from __future__ import annotations

import subprocess
import webbrowser
from urllib.parse import urlsplit

from vision02.profiles.models import Action


class ActionExecutionError(RuntimeError):
    """Falha ao iniciar uma ação configurada."""


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
