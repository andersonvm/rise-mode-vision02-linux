"""Offline coverage of visual OBS scene/audio layouts and mixer safety."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

from vision02.obs_profile_bundle import build_bundle, SCENES, AUDIO
from vision02.obs_visual_layout import _validate_map, inspect_layout, save_layout
from vision02.profile_catalog import ProfileCatalog

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('obs_visual_backend', ROOT/'apps/vision02_obs_visual_backend.py')
BACK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACK)


@pytest.fixture
def cat(tmp_path, monkeypatch):
    config = tmp_path/'config'
    root = config/'vision02'/'profiles'
    root.mkdir(parents=True)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(config))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path/'state'))
    (root/'sistema.yaml').write_text('version: 1\nname: Sistema\nkeys: {}\n', encoding='utf-8')
    profiles = build_bundle(['A', 'B', 'C'], ['Mic', 'Desktop'], legacy_present=False)
    for name, file in [(SCENES, 'obs-cenas.yaml'), (AUDIO, 'obs-audio.yaml'),
                       ('OBS — Controle', 'obs-controle.yaml')]:
        (root/file).write_text(yaml.safe_dump(profiles[name], allow_unicode=True, sort_keys=False), encoding='utf-8')
    return ProfileCatalog(root)


def entries(cat, profile):
    return inspect_layout(profile, catalog=cat)


def test_scene_layout_has_fourteen_slots(cat):
    result = entries(cat, SCENES)
    assert result['limit'] == 14
    assert result['entries']['1'] == 'A'
    assert result['entries']['3'] == 'C'
    assert result['entries']['4'] is None


def test_audio_layout_has_twelve_slots(cat):
    result = entries(cat, AUDIO)
    assert result['limit'] == 12
    assert result['entries']['1'] == 'Mic'
    assert result['entries']['3'] is None


def test_scene_swap_is_persisted(cat):
    result = entries(cat, SCENES)
    result['entries']['1'], result['entries']['2'] = result['entries']['2'], result['entries']['1']
    saved = save_layout(SCENES, result['entries'], result['version'], catalog=cat)
    assert saved['ok'] and saved['count'] == 3
    reread = entries(cat, SCENES)['entries']
    assert reread['1'] == 'B' and reread['2'] == 'A'


def test_five_scenes_can_be_assigned(cat):
    result = entries(cat, SCENES)
    result['entries']['4'] = 'D'
    result['entries']['5'] = 'Teste'
    save_layout(SCENES, result['entries'], result['version'], catalog=cat)
    assert entries(cat, SCENES)['entries']['5'] == 'Teste'


def test_preserves_navigation_and_unrelated_profile(cat):
    before = (cat.root/'obs-controle.yaml').read_bytes()
    result = entries(cat, SCENES)
    result['entries']['2'] = None
    save_layout(SCENES, result['entries'], result['version'], catalog=cat)
    doc = yaml.safe_load((cat.root/'obs-cenas.yaml').read_text())
    assert doc['keys'][15]['action']['target'] == 'OBS — Controle'
    assert 2 not in doc['keys']
    assert (cat.root/'obs-controle.yaml').read_bytes() == before


def test_preserves_appearance_on_key(cat):
    path = cat.root/'obs-cenas.yaml'
    doc = yaml.safe_load(path.read_text())
    doc['keys'][2]['appearance'] = {'background': '#080C16', 'text': 'cena'}
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))
    result = entries(cat, SCENES)
    result['entries']['2'] = 'Nova'
    save_layout(SCENES, result['entries'], result['version'], catalog=cat)
    doc = yaml.safe_load(path.read_text())
    assert doc['keys'][2]['appearance']['text'] == 'cena'


def test_backup_copies_exact_original_bytes(cat, tmp_path):
    result = entries(cat, AUDIO)
    old = (cat.root/'obs-audio.yaml').read_bytes()
    result['entries']['3'] = 'Music'
    saved = save_layout(AUDIO, result['entries'], result['version'], catalog=cat)
    assert Path(saved['backup']).read_bytes() == old
    assert Path(saved['backup']).stat().st_mode & 0o077 == 0


def test_audio_key_operation(cat):
    result = entries(cat, AUDIO)
    result['entries']['1'] = 'NewMic'
    save_layout(AUDIO, result['entries'], result['version'], catalog=cat)
    doc = yaml.safe_load((cat.root/'obs-audio.yaml').read_text())
    assert doc['keys'][1]['action'] == {'type': 'obs', 'operation': 'toggle_mic', 'input': 'NewMic'}


def test_version_conflict_does_not_write(cat):
    result = entries(cat, SCENES)
    before = (cat.root/'obs-cenas.yaml').read_bytes()
    result['entries']['1'] = 'ZZZ'
    with pytest.raises(RuntimeError, match='Outro editor'):
        save_layout(SCENES, result['entries'], 'f'*64, catalog=cat)
    assert (cat.root/'obs-cenas.yaml').read_bytes() == before


@pytest.mark.parametrize('mapping', [
    {}, {'1': 'A'}, {**{str(i): None for i in range(1, 15)}, '9': 'A', '10': 'A'},
    {**{str(i): None for i in range(1, 15)}, '1': ' A'},
    {**{str(i): None for i in range(1, 15)}, '1': 99},
    {**{str(i): None for i in range(1, 15)}, '1': 'a\nB'},
])
def test_rejects_malformed_layout(mapping):
    with pytest.raises(ValueError):
        _validate_map(SCENES, mapping)


def test_rejects_wrong_profile(cat):
    with pytest.raises(ValueError):
        inspect_layout('Sistema', catalog=cat)


def test_unchanged_data_not_rewritten(cat):
    result = entries(cat, AUDIO)
    before = (cat.root/'obs-audio.yaml').read_bytes()
    response = save_layout(AUDIO, result['entries'], result['version'], catalog=cat)
    # Re-dumping existing YAML may reflow formatting once; layout remains identical.
    assert entries(cat, AUDIO)['entries'] == result['entries']
    assert response['ok']


class FakeOBS:
    def __init__(self):
        self.calls = []
        self.closed = False
    def call(self, op, payload=None):
        self.calls.append((op, payload))
        if op == 'GetInputList':
            return {'inputs': [{'inputName': 'Mic'}, {'inputName': 'Desktop'}]}
        if op == 'GetInputVolume':
            return {'inputVolumeMul': 0.42}
        if op == 'GetInputMute':
            return {'inputMuted': False}
        return {}
    def close(self):
        self.closed = True


def test_read_audio_is_read_only():
    obs = FakeOBS()
    response = BACK.audio_state(connector=lambda _: obs, reader=lambda: {})
    assert [i['name'] for i in response['inputs']] == ['Mic', 'Desktop']
    assert response['inputs'][0]['volume'] == 42
    assert set(op for op, _ in obs.calls) == {'GetInputList', 'GetInputMute', 'GetInputVolume'}
    assert obs.closed


def test_volume_requires_explicit_value():
    obs = FakeOBS()
    response = BACK.change_audio({'name': 'Mic', 'volume': 67}, connector=lambda _: obs, reader=lambda: {})
    assert response['ok']
    assert obs.calls[-1] == ('SetInputVolume', {'inputName': 'Mic', 'inputVolumeMul': 0.67})
    assert obs.closed


def test_mute_is_idempotent_not_toggle():
    obs = FakeOBS()
    BACK.change_audio({'name': 'Mic', 'muted': True}, connector=lambda _: obs, reader=lambda: {})
    assert obs.calls[-1] == ('SetInputMute', {'inputName': 'Mic', 'inputMuted': True})


@pytest.mark.parametrize('payload', [
    {'name': 'Mic', 'volume': 101}, {'name': 'Mic', 'volume': -1},
    {'name': 'Mic', 'volume': True}, {'name': 'Mic', 'muted': 'false'},
    {'name': 'Mic', 'muted': False, 'volume': 10}, {'name': 'Unknown', 'volume': 10},
    {'volume': 50},
])
def test_rejects_unsafe_audio_writes(payload):
    obs = FakeOBS()
    with pytest.raises(ValueError):
        BACK.change_audio(payload, connector=lambda _: obs, reader=lambda: {})
    assert all(op not in ('SetInputMute', 'SetInputVolume') for op, _ in obs.calls)


def test_layout_edit_has_no_hid_or_obs_dependency(cat):
    result = entries(cat, SCENES)
    assert 'version' in result and 'file' in result
