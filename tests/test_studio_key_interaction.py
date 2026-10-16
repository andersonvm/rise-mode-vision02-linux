"""Testes offline de edição direta e indicador HID via IPC, sem GTK e sem USB."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

from vision02.control_ipc import _validate_request, ControlServer, request
from vision02.editor_navigation import editor_args, parse_editor_target
from vision02.key_activity import KeyActivity

ROOT = Path(__file__).resolve().parents[1]


def test_editor_target_round_trip_unicode():
    args = editor_args('OBS — Cenas', 15)
    assert args == ['--profile', 'OBS — Cenas', '--key', '15']
    assert parse_editor_target(args) == ('OBS — Cenas', 15)


def test_editor_default():
    assert parse_editor_target([]) == (None, 1)
    assert parse_editor_target(['--key', '6']) == (None, 6)


@pytest.mark.parametrize('key', [0, -5, 16, 99, True, '1', None])
def test_editor_bad_key_rejected(key):
    with pytest.raises(ValueError):
        editor_args('OBS — Controle', key)


@pytest.mark.parametrize('profile', ['', ' A', 'A ', None, 123, 'a' * 129])
def test_editor_bad_profile_rejected(profile):
    with pytest.raises(ValueError):
        editor_args(profile, 2)


@pytest.mark.parametrize('argv', [
    ['--key', '16'], ['--key', '1.5'], ['--key'],
    ['--profile', ' OBS'], ['--unknown'], ['--profile'],
])
def test_editor_invalid_command_line_rejected(argv):
    with pytest.raises(ValueError):
        parse_editor_target(argv)


def test_press_release_and_last_press_expiry():
    now = [10.0]
    activity = KeyActivity(clock=lambda: now[0])
    assert activity.snapshot() == {'pressed_keys': [], 'last_key': None, 'sequence': 0}
    activity.record(7, True)
    assert activity.snapshot() == {'pressed_keys': [7], 'last_key': 7, 'sequence': 1}
    now[0] += 0.4
    activity.record(7, False)
    assert activity.snapshot()['last_key'] == 7
    assert activity.snapshot()['pressed_keys'] == []
    now[0] += 1.41
    assert activity.snapshot()['last_key'] is None
    assert activity.snapshot()['sequence'] == 1


def test_press_multiple_keys_and_order():
    activity = KeyActivity(clock=lambda: 1.)
    activity.record(10, True)
    activity.record(2, True)
    assert activity.snapshot()['pressed_keys'] == [2, 10]
    assert activity.snapshot()['last_key'] == 2
    assert activity.snapshot()['sequence'] == 2
    activity.record(2, False)
    assert activity.snapshot()['pressed_keys'] == [10]
    activity.reset()
    assert activity.snapshot()['pressed_keys'] == []
    assert activity.snapshot()['last_key'] == 2


@pytest.mark.parametrize('key,pressed', [(0, True), (16, True), (2, 'True'), (True, True), (1, 1)])
def test_invalid_activity_rejected(key, pressed):
    with pytest.raises(ValueError):
        KeyActivity().record(key, pressed)


def test_key_activity_ipc_only_read_no_payload():
    assert _validate_request({'command': 'key_activity'}) == ('key_activity', None)
    with pytest.raises(ValueError):
        _validate_request({'command': 'key_activity', 'target': 'A'})


def test_studio_backend_only_proxies_key_activity(monkeypatch):
    spec = importlib.util.spec_from_file_location('studio_backend_extra', ROOT / 'apps/vision02_studio_backend.py')
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ipc = Mock(return_value={'ok': True, 'pressed_keys': [5], 'last_key': 5, 'sequence': 2})
    monkeypatch.setattr(module, 'ipc_request', ipc)
    assert module.run('key_activity')['pressed_keys'] == [5]
    ipc.assert_called_once_with('key_activity', timeout=7)
    with pytest.raises(ValueError):
        module.run('key_activity', {'pressed_keys': [2]})


def test_studio_does_not_execute_key_press_actions():
    src = (ROOT / 'apps/vision02_studio.py').read_text(encoding='utf-8')
    assert 'editor_args(profile, key_id)' in src
    assert "self._call('key_activity')" in src
    assert "button.add_css_class('vision02-key-pressed')" in src
    assert "status_label.set_text('PRESSIONADA'" in src
    assert 'Vision02(' not in src
    assert "self._launch('teclas', profile=self._current, key_id=self._selected_key)" in src


def test_editor_reuses_gtk_app_and_checks_unsaved_changes():
    src = (ROOT / 'apps/vision02_editor.py').read_text(encoding='utf-8')
    assert 'Gio.ApplicationFlags.HANDLES_COMMAND_LINE' in src
    assert 'if self.busy or self.dirty:' in src
    assert 'win.navigate_to(profile, key_id)' in src


def test_controller_records_physical_events_and_exposes_ipc():
    src = (ROOT / 'src/vision02/cli.py').read_text(encoding='utf-8')
    assert 'key_activity.record(key_id, pressed)' in src
    assert 'return key_activity.snapshot()' in src
    assert 'key_activity.reset()' in src
