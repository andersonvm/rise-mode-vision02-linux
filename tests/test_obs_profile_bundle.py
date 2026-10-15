"""Perfis OBS especializados: testes offline sem USB, GTK ou OBS real."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml
from PIL import Image

from vision02.obs_profile_bundle import (
    CONTROL, SCENES, AUDIO, BUNDLE, FILES,
    build_bundle, create_bundle, preview,
)
from vision02.profile_catalog import ProfileCatalog
from vision02.profiles import load_profile, ProfileManager, validate_profile_targets
from vision02.profiles.models import Action
from vision02.obs_control import OBSSnapshot, obs_image, obs_mapping, scene_render_queue, collect_snapshot

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('obs_multi_backend', ROOT/'apps/vision02_obs_profiles_backend.py')
BACK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACK)


def mk_catalog(tmp_path, monkeypatch, *, legacy=True):
    config = tmp_path/'config'
    root = config/'vision02'/'profiles'
    root.mkdir(parents=True)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(config))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path/'state'))
    (root/'sistema.yaml').write_text('version: 1\nname: Sistema\nkeys: {}\n')
    if legacy:
        (root/'obs-studio.yaml').write_text('version: 1\nname: OBS Studio\nkeys: {}\n')
    return ProfileCatalog(root)


def data_keys(profile):
    return set(profile['keys'])


def test_build_has_exact_three_profiles():
    result = build_bundle(['Teste', 'Câmera'], ['Mic/Aux'])
    assert set(result) == set(BUNDLE)
    assert all(p['version'] == 1 for p in result.values())


def test_control_actions_and_navigation():
    c = build_bundle([], []) [CONTROL]['keys']
    assert c[1]['action']['operation'] == 'toggle_record'
    assert c[2]['action']['operation'] == 'toggle_pause'
    assert c[3]['action']['operation'] == 'toggle_stream'
    assert c[12]['action']['target'] == SCENES
    assert c[13]['action']['target'] == AUDIO
    assert c[14]['action']['target'] == 'OBS Studio'
    assert c[15]['action']['target'] == 'Sistema'


def test_without_legacy_profile_no_invalid_navigation():
    keys = build_bundle([], [], legacy_present=False)[CONTROL]['keys']
    assert 14 not in keys


def test_scene_names_stable_and_15_reserved():
    names = ['Câmera USB', 'Teste', 'Área de trabalho']
    keys = build_bundle(names, [])[SCENES]['keys']
    assert [keys[i]['action']['scene'] for i in range(1, 4)] == names
    assert keys[15]['action']['target'] == CONTROL
    assert data_keys(build_bundle(names, [])[SCENES]) == {1,2,3,15}


def test_audio_inputs_named_exact_and_navigation():
    keys = build_bundle([], ['Mic/Aux', 'Webcam Mic'])[AUDIO]['keys']
    assert keys[1]['action']['input'] == 'Mic/Aux'
    assert keys[2]['action']['input'] == 'Webcam Mic'
    assert keys[13]['action']['target'] == SCENES
    assert keys[14]['action']['target'] == CONTROL
    assert keys[15]['action']['target'] == 'Sistema'


def test_14_scenes_and_12_inputs():
    d = build_bundle([f'C{i}' for i in range(14)], [f'A{i}' for i in range(12)])
    assert len(d[SCENES]['keys']) == 15
    assert len(d[AUDIO]['keys']) == 15


@pytest.mark.parametrize('scenes,inputs', [
    (['A']*2, []), ([], ['Mic']*2), ([''] , []), ([ ' bad '], []),
    (['a\nb'], []), (['a'*129], []), ([*map(str, range(15))], []),
    ([], [*map(str, range(13))]), (None, []), ('A', []),
])
def test_rejects_invalid_scene_or_audio(scenes, inputs):
    with pytest.raises(ValueError):
        build_bundle(scenes, inputs)


def test_create_yaml_all_validate_with_legacy(tmp_path, monkeypatch):
    catalog = mk_catalog(tmp_path, monkeypatch)
    ver = preview(catalog)['version']
    result = create_bundle(['Mesa', 'Câmera'], ['Mic/Aux'], ver, catalog=catalog)
    assert result['ok']
    assert result['scenes'] == 2 and result['inputs'] == 1
    assert all((catalog.root/FILES[name]).is_file() for name in BUNDLE)
    profiles = ProfileManager()
    profiles.load_many(catalog.paths())
    validate_profile_targets(profiles)
    assert len(profiles.list_profiles()) == 5
    assert load_profile(catalog.root/FILES[SCENES]).keys[2].action.obs_scene == 'Câmera'


def test_create_without_legacy(tmp_path, monkeypatch):
    catalog = mk_catalog(tmp_path, monkeypatch, legacy=False)
    create_bundle(['Cena'], [], preview(catalog)['version'], catalog=catalog)
    assert len(load_profile(catalog.root/FILES[CONTROL]).keys) == 14


def test_reject_recreation_preserves_files(tmp_path, monkeypatch):
    cat = mk_catalog(tmp_path, monkeypatch)
    ver = preview(cat)['version']
    create_bundle(['A'], [], ver, catalog=cat)
    before = {path:path.read_bytes() for path in cat.paths()}
    with pytest.raises(ValueError, match='já existem'):
        create_bundle(['B'], [], preview(cat)['version'], catalog=cat)
    assert before == {path:path.read_bytes() for path in cat.paths()}


def test_stale_catalog_rejected(tmp_path, monkeypatch):
    catalog = mk_catalog(tmp_path, monkeypatch)
    old_ver = preview(catalog)['version']
    (catalog.root/'sistema.yaml').write_text('version: 1\nname: Sistema\nkeys: {}\n# edit\n')
    with pytest.raises(RuntimeError, match='alterado'):
        create_bundle(['A'], [], old_ver, catalog=catalog)
    assert not any((catalog.root/name).exists() for name in FILES.values())


def test_collision_filename_rejected(tmp_path, monkeypatch):
    cat = mk_catalog(tmp_path, monkeypatch)
    (cat.root/'obs-cenas.yaml').write_text('version: 1\nname: Qualquer outro\nkeys: {}\n')
    with pytest.raises(ValueError, match='Arquivo já existente'):
        create_bundle([], [], preview(cat)['version'], catalog=cat)


def test_collision_name_rejected(tmp_path, monkeypatch):
    cat = mk_catalog(tmp_path, monkeypatch)
    (cat.root/'nome-outro.yaml').write_text(f'version: 1\nname: {SCENES}\nkeys: {{}}\n')
    with pytest.raises(ValueError, match='Perfis já existem'):
        create_bundle([], [], preview(cat)['version'], catalog=cat)


def test_no_sistema_rejected(tmp_path, monkeypatch):
    cat = mk_catalog(tmp_path, monkeypatch)
    (cat.root/'sistema.yaml').unlink()
    with pytest.raises(ValueError, match='Sistema'):
        create_bundle([], [], preview(cat)['version'], catalog=cat)


def test_rollback_after_partial_write(tmp_path, monkeypatch):
    import vision02.obs_profile_bundle as mod
    cat = mk_catalog(tmp_path, monkeypatch)
    ver = preview(cat)['version']
    original_writer = mod._exclusive_write
    calls = []
    def fail_second(path, content):
        calls.append(path)
        if len(calls) == 2:
            raise OSError('falha simulada de disco')
        original_writer(path, content)
    monkeypatch.setattr(mod, '_exclusive_write', fail_second)
    with pytest.raises(OSError, match='falha simulada'):
        create_bundle(['Teste'], ['Mic'], ver, catalog=cat)
    assert not any((cat.root/filename).exists() for filename in FILES.values())
    assert preview(cat)['version'] == ver


def test_symlink_collision_blocked(tmp_path, monkeypatch):
    cat = mk_catalog(tmp_path, monkeypatch)
    (cat.root/'obs-audio.yaml').symlink_to(cat.root/'sistema.yaml')
    with pytest.raises(ValueError):
        create_bundle([], [], preview(cat)['version'], catalog=cat)


def test_backend_catalog_no_obs_connection(tmp_path, monkeypatch):
    mk_catalog(tmp_path, monkeypatch)
    assert BACK.run('catalog')['ok']


def test_backend_create_offline_without_network(tmp_path, monkeypatch):
    cat = mk_catalog(tmp_path, monkeypatch)
    response = BACK.run('create', {'scenes':['Teste'], 'inputs':['Mic/Aux'],
                                   'version':preview(cat)['version']})
    assert response['ok'] and response['scenes'] == 1


def test_backend_reject_missing_credentials_without_modifying_catalog(tmp_path, monkeypatch):
    cat = mk_catalog(tmp_path, monkeypatch)
    version = preview(cat)['version']
    with pytest.raises(Exception):
        BACK.run('discover')
    assert preview(cat)['version'] == version


def test_obs_mapping_any_profile_with_obs_action():
    class Key:
        def __init__(self, action):self.action=action;self.appearance=None
    class Profile:
        name = SCENES
        keys = {1: Key(Action(type='obs', obs_operation='scene_name', obs_scene='Teste'))}
    assert 1 in obs_mapping(Profile())


def test_scene_images_one_active_when_named():
    actions = {1:Action(type='obs', obs_operation='scene_name', obs_scene='A'),
               2:Action(type='obs', obs_operation='scene_name', obs_scene='B')}
    image_rows = scene_render_queue(actions, OBSSnapshot(connected=True,scene='B',scenes=('A','B')))
    assert len(image_rows)==2 and image_rows[-1][0]==2
    assert all(image.mode=='RGB' and image.size==(100,100) for _,image in image_rows)


def test_input_states_are_independent_per_source():
    snapshot = OBSSnapshot(connected=True,mic_muted=True,
                           input_mutes=(('Mic A', False), ('Mic B', True)))
    a = Action(type='obs',obs_operation='toggle_mic',obs_source='Mic A')
    b = Action(type='obs',obs_operation='toggle_mic',obs_source='Mic B')
    img_a = obs_image(a,snapshot)
    img_b = obs_image(b,snapshot)
    assert img_a.tobytes()!=img_b.tobytes()


def test_missing_audio_source_stays_unknown_not_global():
    snapshot = OBSSnapshot(connected=True,mic_muted=True)
    a = Action(type='obs',obs_operation='toggle_mic',obs_source='Ausente')
    b = Action(type='obs',obs_operation='toggle_mic',obs_source='Ausente')
    assert obs_image(a,snapshot).tobytes()==obs_image(b,snapshot).tobytes()


def test_collect_snapshot_handles_missing_input_list():
    class Client:
        def call(self, method, payload=None):
            if method=='GetRecordStatus':return {'outputActive':False}
            if method=='GetSceneList':return {'scenes':[], 'currentProgramSceneName':None}
            if method=='GetSpecialInputs':return {}
            if method=='GetInputList':raise __import__('vision02.obs_websocket', fromlist=['OBSError']).OBSError('not supported')
            return {'outputActive':False}
    s=collect_snapshot(Client(),{})
    assert s.connected and s.input_mutes == ()


def test_collect_snapshot_each_input_mute():
    class Client:
        def call(self,method,payload=None):
            if method=='GetRecordStatus':return {'outputActive':False}
            if method=='GetSceneList':return {'scenes':[]}
            if method=='GetSpecialInputs':return {}
            if method=='GetInputList':return {'inputs':[{'inputName':'A'},{'inputName':'B'}]}
            if method=='GetInputMute':return {'inputMuted':payload['inputName']=='B'}
            return {'outputActive':False}
    s=collect_snapshot(Client(),{})
    assert s.input_mutes==(('A',False),('B',True))


def test_no_gtk_import_in_backend():
    import inspect
    import vision02.obs_profile_bundle as mod
    assert 'gi.repository' not in inspect.getsource(mod)
