"""Regressão: scripts e atalhos, sem subprocessos reais e sem USB."""
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from vision02.actions import ActionExecutionError, execute_action
from vision02.profiles import ProfileValidationError, load_profile
from vision02.profiles.models import Action


def profile(tmp_path, action):
    path = tmp_path / "perfil.yaml"
    path.write_text(
        "version: 1\nname: Teste\nkeys:\n  1:\n"
        "    label: Acao\n    action:\n" + action,
        encoding="utf-8",
    )
    return path


def test_valid_script_relative_path_and_args(tmp_path):
    script = tmp_path / "job.sh"
    script.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    action = load_profile(profile(
        tmp_path,
        "      type: script\n      path: job.sh\n"
        "      interpreter: bash\n      args: [abc, '42']\n",
    )).keys[1].action
    assert action.type == "script"
    assert action.script_path == script.resolve()
    assert action.interpreter == "bash"
    assert action.argv == ("abc", "42")


def test_valid_python_script(tmp_path):
    script = tmp_path / "job.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    action = load_profile(profile(
        tmp_path,
        "      type: script\n      path: job.py\n"
        "      interpreter: python3\n",
    )).keys[1].action
    assert action.argv == ()
    assert action.script_path == script.resolve()


@pytest.mark.parametrize("fragment", [
    "      type: script\n      path: missing.sh\n      interpreter: bash\n",
    "      type: script\n      path: foo.sh\n      interpreter: zsh\n",
    "      type: script\n      path: foo.sh\n      interpreter: bash\n      args: 'x; rm -rf /'\n",
    "      type: script\n      path: foo.sh\n      interpreter: bash\n      extra: yes\n",
])
def test_invalid_script_rejected(tmp_path, fragment):
    (tmp_path / 'foo.sh').write_text('exit 0\n', encoding='utf-8')
    with pytest.raises(ProfileValidationError):
        load_profile(profile(tmp_path, fragment))


def test_valid_hotkey(tmp_path):
    action = load_profile(profile(
        tmp_path,
        "      type: hotkey\n      keys: [ctrl, shift, t]\n",
    )).keys[1].action
    assert action.type == 'hotkey'
    assert action.keys == ('ctrl', 'shift', 't')


@pytest.mark.parametrize('keys', [
    '[]', "'ctrl+alt+t'", '[ctrl, "shift;echo"]', '[ctrl, ""]',
    '[ctrl, shift, alt, super, a, b]',
])
def test_invalid_hotkey_rejected(tmp_path, keys):
    with pytest.raises(ProfileValidationError):
        load_profile(profile(
            tmp_path,
            f"      type: hotkey\n      keys: {keys}\n",
        ))


def test_hotkey_unknown_field_rejected(tmp_path):
    with pytest.raises(ProfileValidationError, match='desconhecidos'):
        load_profile(profile(
            tmp_path,
            "      type: hotkey\n      keys: [ctrl, a]\n      command: injected\n",
        ))


def test_script_execution_uses_explicit_interpreter_without_shell(tmp_path):
    script = tmp_path / 'job.sh'
    script.write_text('echo ok\n', encoding='utf-8')
    action = Action(type='script', script_path=script, interpreter='bash', argv=('hello world',))
    with patch('vision02.actions.executor.subprocess.Popen') as popen:
        execute_action(action)
    args, kwargs = popen.call_args
    assert args[0] == ['bash', str(script), 'hello world']
    assert kwargs['shell'] is False
    assert kwargs['stdin'] == __import__('subprocess').DEVNULL


def test_python_script_uses_project_python(tmp_path):
    script = tmp_path / 'job.py'
    script.write_text('pass\n', encoding='utf-8')
    action = Action(type='script', script_path=script, interpreter='python3')
    with patch('vision02.actions.executor.subprocess.Popen') as popen:
        execute_action(action)
    assert popen.call_args.args[0] == [sys.executable, str(script)]


def test_script_missing_at_execution_rejected(tmp_path):
    action = Action(type='script', script_path=tmp_path / 'deleted.sh', interpreter='bash')
    with pytest.raises(ActionExecutionError, match='não encontrado'):
        execute_action(action)


def test_hotkey_on_x11(monkeypatch):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'x11')
    action = Action(type='hotkey', keys=('ctrl', 'shift', 't'))
    with (
        patch('vision02.actions.executor.shutil.which', return_value='/usr/bin/xdotool'),
        patch('vision02.actions.executor.subprocess.run') as run,
    ):
        execute_action(action)
    assert run.call_args.args[0] == ['/usr/bin/xdotool', 'key', '--clearmodifiers', 'ctrl+shift+t']
    assert run.call_args.kwargs['check'] is True
    assert run.call_args.kwargs['timeout'] == 5


def test_hotkey_wayland_uses_portal(monkeypatch):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'wayland')
    with (
        patch('vision02.actions.executor._get_wayland_keyboard') as portal,
        patch('vision02.actions.executor.subprocess.run') as run,
    ):
        execute_action(Action(type='hotkey', keys=('ctrl', 'shift', 't')))
    portal.return_value.send.assert_called_once_with(('ctrl', 'shift', 't'))
    run.assert_not_called()


def test_hotkey_without_xdotool_rejected(monkeypatch):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'x11')
    with patch('vision02.actions.executor.shutil.which', return_value=None):
        with pytest.raises(ActionExecutionError, match='xdotool'):
            execute_action(Action(type='hotkey', keys=('ctrl', 't')))


def test_hotkey_invalid_direct_action_rejected(monkeypatch):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'x11')
    with patch('vision02.actions.executor.subprocess.run') as run:
        with pytest.raises(ActionExecutionError, match='inválidas'):
            execute_action(Action(type='hotkey', keys=('ctrl', 'a;echo')))
    run.assert_not_called()


def test_hotkey_os_error_is_wrapped(monkeypatch):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'x11')
    with (
        patch('vision02.actions.executor.shutil.which', return_value='/usr/bin/xdotool'),
        patch('vision02.actions.executor.subprocess.run', side_effect=OSError('simulado')),
    ):
        with pytest.raises(ActionExecutionError, match='Falha no atalho'):
            execute_action(Action(type='hotkey', keys=('ctrl', 't')))
