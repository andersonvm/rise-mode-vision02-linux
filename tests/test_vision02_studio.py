"""Teste offline do Studio, sem GTK, USB/HID ou rede OBS."""
from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('studio_backend', ROOT / 'apps/vision02_studio_backend.py')
assert SPEC and SPEC.loader
BACKEND = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACKEND)


def test_status_uses_ipc_not_hid(monkeypatch):
    calls = []
    monkeypatch.setattr(BACKEND, 'ipc_request', lambda *a, **kw: (calls.append((a, kw)) or {'ok': True, 'active': 'Sistema'}))
    assert BACKEND.run('status')['active'] == 'Sistema'
    assert calls == [(('status',), {'timeout': 7})]


def test_switch_uses_ipc_target(monkeypatch):
    ipc = Mock(return_value={'ok': True, 'active': 'OBS — Cenas'})
    monkeypatch.setattr(BACKEND, 'ipc_request', ipc)
    assert BACKEND.run('switch', {'target': 'OBS — Cenas'})['ok']
    ipc.assert_called_once_with('switch', 'OBS — Cenas', timeout=12)


def test_reload_uses_ipc(monkeypatch):
    ipc = Mock(return_value={'ok': True, 'reloaded': True})
    monkeypatch.setattr(BACKEND, 'ipc_request', ipc)
    assert BACKEND.run('reload')['reloaded']
    ipc.assert_called_once_with('reload', timeout=25)


@pytest.mark.parametrize('cmd,payload', [
    ('switch', {}), ('switch', {'target': 4}), ('switch', {'target': 'Ok', 'bad': True}),
    ('status', {'extra': True}), ('reload', {'extra': True}),
    ('icons', {'file': '/etc/passwd'}), ('previews', {'profile': 'x'}),
    ('obs', {'command': 'ToggleStream'}), ('system', {'run': 'echo'}),
    ('import_icon', {}), ('import_icon', {'path': '/tmp/a.png', 'extra': 1}),
    ('arbitrary_shell', {}),
])
def test_disallows_unknown_or_invalid_requests(cmd, payload):
    with pytest.raises(ValueError):
        BACKEND.run(cmd, payload)


def test_previews_uses_shared_builder(monkeypatch, tmp_path):
    monkeypatch.setattr(BACKEND, 'default_profile_paths', lambda project: [tmp_path/'x.yaml'])
    builder = Mock(return_value={'profiles': {'Teste': {'keys': []}}})
    monkeypatch.setattr(BACKEND, 'build_metadata', builder)
    result = BACKEND.run('previews', project=tmp_path)
    assert result == {'ok': True, 'profiles': {'Teste': {'keys': []}}}
    builder.assert_called_once_with(tmp_path, [tmp_path/'x.yaml'])


def test_icons_read_only(monkeypatch):
    reader = Mock(return_value=[{'name': 'OBS', 'path': '/tmp/icon.png'}])
    monkeypatch.setattr(BACKEND, 'list_icons', reader)
    assert BACKEND.run('icons')['icons'][0]['name'] == 'OBS'
    reader.assert_called_once_with()


def test_import_icon_explicit_only(monkeypatch):
    importer = Mock(return_value={'name': 'Python', 'imported': True})
    monkeypatch.setattr(BACKEND, 'import_icon', importer)
    response = BACKEND.run('import_icon', {'path': '/tmp/python.png'})
    assert response['icon']['imported'] is True
    importer.assert_called_once_with(Path('/tmp/python.png'))


def test_system_samples_twice(monkeypatch):
    class Sample:
        cpu = 42.0
        ram = 30.0
        gpu = None
    # Use the actual dataclass to exercise asdict().
    from vision02.system_dashboard import Snapshot
    sampler = Mock()
    sampler.collect.side_effect = [Snapshot(cpu=None), Snapshot(cpu=42.0, ram=30.0)]
    monkeypatch.setattr(BACKEND, 'LinuxSampler', lambda: sampler)
    monkeypatch.setattr(BACKEND.time, 'sleep', lambda delay: None)
    result = BACKEND.run('system')
    assert result['metrics']['cpu'] == 42.0
    assert sampler.collect.call_count == 2


def test_obs_only_uses_discovery(monkeypatch):
    # OBS import in the application modules: never call the command API here.
    import vision02_obs_panel_backend
    reader = Mock(return_value={'connected': True, 'scenes': ['A', 'B']})
    monkeypatch.setattr(vision02_obs_panel_backend, 'discover', reader)
    result = BACKEND.run('obs')
    assert result['obs']['scenes'] == ['A', 'B']
    reader.assert_called_once_with()


def test_studio_scripts_do_not_launch_hid():
    launcher = (ROOT / 'scripts/vision02-studio').read_text(encoding='utf-8')
    gtk = (ROOT / 'apps/vision02_studio.py').read_text(encoding='utf-8')
    assert '/usr/bin/python3' in launcher
    assert 'vision02_studio.py' in launcher
    assert 'hidraw' not in gtk
    assert 'subprocess.Popen' in gtk


def test_backend_main_returns_json_on_failure(monkeypatch, capsys):
    monkeypatch.setattr(BACKEND.sys, 'argv', ['backend', '--command', 'switch'])
    monkeypatch.setattr(BACKEND.sys, 'stdin', Mock(isatty=lambda: True, closed=False))
    result = BACKEND.main()
    assert result == 1
    assert json.loads(capsys.readouterr().out)['ok'] is False


def test_live_preview_only_reads_owner_ipc(monkeypatch):
    ipc = Mock(return_value={'ok': True, 'active': 'Sistema', 'revision': 12, 'images': {}})
    monkeypatch.setattr(BACKEND, 'ipc_request', ipc)
    result = BACKEND.run('live_preview')
    assert result['revision'] == 12
    ipc.assert_called_once_with('display_preview', timeout=7)


def test_live_preview_rejects_arguments():
    with pytest.raises(ValueError):
        BACKEND.run('live_preview', {'target': 'OBS'})


def test_live_preview_source_never_opens_hid():
    gtk = (ROOT / 'apps/vision02_studio.py').read_text(encoding='utf-8')
    assert "self._call('live_preview')" in gtk
    assert 'Gdk.Texture.new_from_bytes' in gtk
    assert 'Vision02(' not in gtk
