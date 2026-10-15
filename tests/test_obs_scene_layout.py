"""Correções de múltiplas cenas OBS — offline; não acessa WebSocket nem USB."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

from vision02.obs_control import (
    OBSSnapshot, resolved_scene, scene_claims, scene_render_queue,
    obs_image, perform_action,
)
from vision02.obs_websocket import OBSError
from vision02.profiles import load_profile
from vision02.profiles.models import Action

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('obs_batch_backend', ROOT / 'apps/vision02_obs_panel_backend.py')
BACK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACK)


def scene_action(name):
    return Action(type='obs', obs_operation='scene_name', obs_scene=name)


def legacy(slot):
    return Action(type='obs', obs_operation='scene_slot', obs_slot=slot)


def fixture_profile(tmp_path, monkeypatch):
    config = tmp_path / 'config'
    folder = config / 'vision02' / 'profiles'
    folder.mkdir(parents=True)
    (folder / 'sistema.yaml').write_text('version: 1\nname: Sistema\nkeys: {}\n')
    obs = {
        'version': 1, 'name': 'OBS Studio', 'keys': {
            4: {'label': 'Mic', 'action': {'type': 'obs', 'operation': 'toggle_mic'}},
            6: {'label': 'Cena 1', 'action': {'type': 'obs', 'operation': 'scene_slot', 'slot': 1},
                'appearance': {'background': '#123456'}},
            7: {'label': 'Cena 2', 'action': {'type': 'obs', 'operation': 'scene_slot', 'slot': 2}},
            8: {'label': 'Cena 3', 'action': {'type': 'obs', 'operation': 'scene_slot', 'slot': 3}},
            9: {'label': 'Próxima', 'action': {'type': 'obs', 'operation': 'next_scene'}},
            10: {'label': 'Anterior', 'action': {'type': 'obs', 'operation': 'previous_scene'}},
            15: {'label': 'Voltar', 'action': {'type': 'profile', 'target': 'Sistema'}},
        }
    }
    path = folder / 'obs-studio.yaml'
    path.write_text(yaml.safe_dump(obs, sort_keys=False, allow_unicode=True))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(config))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    return path


def assign(request_info, count=5, start=6):
    return {'sha256': request_info['sha256'], 'assignments': [
        {'key_id': start+i, 'scene': f'Cena {i+1}'} for i in range(count)
    ]}


def test_batch_five_scenes_migrates_legacy(tmp_path, monkeypatch):
    path = fixture_profile(tmp_path, monkeypatch)
    old = path.read_bytes()
    info = BACK.profile_info(ROOT)
    result = BACK.save_scene_assignments(ROOT, assign(info))
    profile = load_profile(path)
    assert result['count'] == 5
    assert Path(result['backup']).read_bytes() == old
    assert [profile.keys[k].action.obs_scene for k in range(6, 11)] == [f'Cena {i}' for i in range(1, 6)]
    assert all(profile.keys[k].action.obs_operation == 'scene_name' for k in range(6, 11))
    assert profile.keys[6].appearance.background == '#123456'
    assert profile.keys[4].action.obs_operation == 'toggle_mic'
    assert profile.keys[15].action.target == 'Sistema'


def test_five_mappings_do_not_change_if_obs_reorders(tmp_path, monkeypatch):
    path = fixture_profile(tmp_path, monkeypatch)
    BACK.save_scene_assignments(ROOT, assign(BACK.profile_info(ROOT)))
    actions = {k: load_profile(path).keys[k].action for k in range(6, 11)}
    reordered = ('Cena 5', 'Cena 4', 'Cena 3', 'Cena 2', 'Cena 1')
    snapshot = OBSSnapshot(connected=True, scene='Cena 5', scenes=reordered)
    assert resolved_scene(actions[10], snapshot) == 'Cena 5'
    assert scene_claims(actions, snapshot) == set(range(6, 11))


def test_batch_can_assign_14_scenes(tmp_path, monkeypatch):
    path = fixture_profile(tmp_path, monkeypatch)
    BACK.save_scene_assignments(ROOT, assign(BACK.profile_info(ROOT), 14, 1))
    profile = load_profile(path)
    assert profile.keys[14].action.obs_scene == 'Cena 14'
    assert profile.keys[15].action.type == 'profile'


@pytest.mark.parametrize('rows', [
    [],
    [{'key_id': 15, 'scene': 'Cena 1'}],
    [{'key_id': 0, 'scene': 'Cena 1'}],
    [{'key_id': 6, 'scene': 'Cena 1'}, {'key_id': 6, 'scene': 'Cena 2'}],
    [{'key_id': 6, 'scene': 'Cena 1'}, {'key_id': 7, 'scene': 'Cena 1'}],
    [{'key_id': 6, 'scene': ''}],
    [{'key_id': 6, 'scene': '\n'}],
    [{'key_id': 6, 'scene': 'A'*129}],
    [{'key_id': '6', 'scene': 'Cena 1'}],
    [{'key_id': True, 'scene': 'Cena 1'}],
    'invalid',
])
def test_batch_invalid_is_non_destructive(tmp_path, monkeypatch, rows):
    path = fixture_profile(tmp_path, monkeypatch)
    before = path.read_bytes()
    info = BACK.profile_info(ROOT)
    with pytest.raises(ValueError):
        BACK.save_scene_assignments(ROOT, {'sha256': info['sha256'], 'assignments': rows})
    assert path.read_bytes() == before


def test_batch_rejects_stale_yaml(tmp_path, monkeypatch):
    path = fixture_profile(tmp_path, monkeypatch)
    request = assign(BACK.profile_info(ROOT))
    path.write_text(path.read_text() + '\n# concorrente\n')
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match='mudou no disco'):
        BACK.save_scene_assignments(ROOT, request)
    assert path.read_bytes() == before


def test_batch_rejects_scene_already_on_another_named_key(tmp_path, monkeypatch):
    path = fixture_profile(tmp_path, monkeypatch)
    data = yaml.safe_load(path.read_text())
    data['keys'][11] = {'label': 'Outra', 'action': {'type': 'obs', 'operation': 'scene_name', 'scene': 'Cena 1'}}
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    before = path.read_bytes()
    with pytest.raises(ValueError, match='tecla 11'):
        BACK.save_scene_assignments(ROOT, assign(BACK.profile_info(ROOT)))
    assert path.read_bytes() == before


def test_single_save_rejects_duplicate_named_scene(tmp_path, monkeypatch):
    path = fixture_profile(tmp_path, monkeypatch)
    BACK.save_scene_assignments(ROOT, assign(BACK.profile_info(ROOT)))
    info = BACK.profile_info(ROOT)
    before = path.read_bytes()
    with pytest.raises(ValueError, match='já está vinculada'):
        BACK.save_mapping(ROOT, {'sha256': info['sha256'], 'key_id': 11,
                                 'operation': 'scene_name', 'scene': 'Cena 3', 'label': 'Outro'})
    assert path.read_bytes() == before


def test_claims_priority_and_order_for_legacy_duplicates():
    mapping = {6: legacy(2), 7: scene_action('Teste'), 8: scene_action('Outro')}
    snap = OBSSnapshot(connected=True, scene='Teste', scenes=('Outro', 'Teste'))
    assert scene_claims(mapping, snap) == {7, 8}
    rendered = scene_render_queue(mapping, snap)
    assert [key for key, _ in rendered] == [6, 8, 7]  # primeiro desativa 6/8, depois ativa 7
    assert all(image.size == (100, 100) for _, image in rendered)
    assert obs_image(scene_action('Teste'), snap, duplicate=True).tobytes() != obs_image(scene_action('Teste'), snap).tobytes()


def test_order_prioritizes_old_inactive_before_new_active():
    mapping = {6: scene_action('Nova'), 7: scene_action('Antiga')}
    snap = OBSSnapshot(connected=True, scene='Nova', scenes=('Nova', 'Antiga'))
    rendered = scene_render_queue(mapping, snap)
    assert [key for key, _ in rendered] == [7, 6]


def test_exact_scene_call_resistant_to_obs_scene_reordering():
    class Client:
        def __init__(self): self.calls = []
        def call(self, method, payload=None):
            self.calls.append((method, payload))
            if method == 'GetSceneList':
                return {'scenes': [{'sceneName': s} for s in ('Cinco', 'Três', 'Um', 'Dois', 'Quatro')]}
            return {}
    client = Client()
    perform_action(client, scene_action('Cinco'), OBSSnapshot(connected=True), {})
    assert client.calls[-1] == ('SetCurrentProgramScene', {'sceneName': 'Cinco'})


def test_name_not_in_snapshot_does_not_claim_active():
    snapshot = OBSSnapshot(connected=True, scene='Teste', scenes=('Teste',))
    assert scene_claims({6: scene_action('Inexistente')}, snapshot) == set()
