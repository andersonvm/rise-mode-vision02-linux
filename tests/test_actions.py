"""Testes do executor de ações sem iniciar processos reais."""

from unittest.mock import patch

import pytest

from vision02.actions import (
    ActionExecutionError,
    execute_action,
)
from vision02.profiles.models import Action


def test_execute_command():
    action = Action(
        type="command",
        argv=("echo", "teste"),
    )

    with patch(
        "vision02.actions.executor.subprocess.Popen"
    ) as popen:
        execute_action(action)

    args, kwargs = popen.call_args

    assert args[0] == ["echo", "teste"]
    assert kwargs["shell"] is False


def test_execute_url():
    action = Action(
        type="url",
        url="https://github.com",
    )

    with patch(
        "vision02.actions.executor.webbrowser.open",
        return_value=True,
    ) as open_url:
        execute_action(action)

    open_url.assert_called_once_with(
        "https://github.com"
    )


def test_command_without_arguments_rejected():
    action = Action(type="command")

    with pytest.raises(
        ActionExecutionError,
        match="sem argumentos",
    ):
        execute_action(action)


def test_unsupported_action_rejected():
    action = Action(type="shell")

    with pytest.raises(
        ActionExecutionError,
        match="não suportado",
    ):
        execute_action(action)


def test_command_start_failure():
    action = Action(
        type="command",
        argv=("programa-inexistente",),
    )

    with patch(
        "vision02.actions.executor.subprocess.Popen",
        side_effect=FileNotFoundError(),
    ):
        with pytest.raises(
            ActionExecutionError,
            match="Falha ao iniciar",
        ):
            execute_action(action)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://",
        "http://example.com:invalid",
    ],
)
def test_unsafe_url_rejected(url):
    action = Action(type="url", url=url)

    with patch(
        "vision02.actions.executor.webbrowser.open"
    ) as open_url:
        with pytest.raises(ActionExecutionError):
            execute_action(action)

    open_url.assert_not_called()
