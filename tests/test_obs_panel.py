"""Painel OBS: testes offline, sem GTK/USB/rede real e sem credenciais."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import pytest
import yaml
from PIL import Image

from vision02.obs_control import OBSSnapshot, obs_image, perform_action, OBS_OPERATIONS
from vision02.obs_websocket import OBSError
from vision02.profiles.loader import load_profile, ProfileValidationError
from vision02.profiles.models import Action

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('vision02_obs_panel_backend', ROOT / 'apps/vision02_obs_panel_backend.py')
BACK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACK)


def profile_file(tmp_path, monkeypatch):
    config_dir = tmp_path / 'config'
    state_dir = tmp_path / 'state'
    location = config_dir / 'vision02' / 'profiles'
    location.mkdir(parents=True)
    icon = tmp_path / 'custom.png'
    Image.new('RGB', (100, 100), (5, 10, 20)).save(icon)
    data = {'version': 1, 'name': 'OBS Studio', 'keys': {
        1: {'label': 'Gravação', 'image': str(icon), 'action': {'type': 'obs', 'operation': 'toggle_record'},
            'appearance': {'background': '#081020', 'font_size': 18}},
        6: {'label': 'Cena 1', 'action': {'type': 'obs', 'operation': 'scene_slot', 'slot': 1}},
        15: {'label': 'Voltar', 'action': {'type': 'profile', 'target': 'Sistema'}},
    }}
    path = location / 'obs-studio.yaml'
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    (location / 'sistema.yaml').write_text('version: 1\nname: Sistema\nkeys: {}\n')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(config_dir))
    monkeypatch.setenv('XDG_STATE_HOME', str(state_dir))
    return path


@pytest.mark.parametrize('scene', ['Principal', 'Câmera USB', 'Desktop e Jogo', 'São Paulo'])
def test_scene_by_exact_name_roundtrip(tmp_path, scene):
    path = tmp_path / 'obs.yaml'
    path.write_text(yaml.safe_dump({'version': 1, 'name': 'OBS Studio', 'keys':
        {6: {'label': 'Cenas', 'action': {'type': 'obs', 'operation': 'scene_name', 'scene': scene}}}}))
    action = load_profile(path).keys[6].action
    assert action.obs_scene == scene and action.obs_operation == 'scene_name'


@pytest.mark.parametrize('attrs', [
    {'operation': 'scene_name'},
    {'operation': 'scene_name', 'scene': '  '},
    {'operation': 'scene_name', 'scene': 'A'*129},
    {'operation': 'scene_name', 'scene': 'nome\ncom quebra'},
    {'operation': 'scene_name', 'scene': 'A', 'slot': 1},
    {'operation': 'toggle_record', 'scene': 'Câmera'},
    {'operation': 'toggle_record', 'input': 'Mic'},
    {'operation': 'scene_slot', 'slot': 3, 'scene': 'Câmera'},
])
def test_scene_name_validation(tmp_path, attrs):
    path = tmp_path / 'bad.yaml'
    path.write_text(yaml.safe_dump({'version': 1, 'name': 'OBS Studio', 'keys':
        {6: {'label': 'Cenas', 'action': {'type': 'obs', **attrs}}}}))
    with pytest.raises(ProfileValidationError):
        load_profile(path)


@pytest.mark.parametrize('op', sorted(OBS_OPERATIONS))
def test_panel_supports_all_existing_obs_commands(op):
    extra = {'slot': 1} if op == 'scene_slot' else {'scene': 'Cena 01'} if op == 'scene_name' else {}
    result = BACK.mapping_action(op, **extra)
    assert result['type'] == 'obs' and result['operation'] == op


def test_save_scene_preserves_appearance_image_and_backups(tmp_path, monkeypatch):
    path = profile_file(tmp_path, monkeypatch)
    info = BACK.profile_info(ROOT)
    old = path.read_bytes()
    result = BACK.save_mapping(ROOT, {
        'key_id': 1, 'sha256': info['sha256'], 'label': 'Principal',
        'operation': 'scene_name', 'scene': 'Mesa Principal',
    })
    assert result['ok']
    new = load_profile(path)
    cfg = new.keys[1]
    assert cfg.action.obs_scene == 'Mesa Principal'
    assert cfg.appearance.background == '#081020'
    assert cfg.image == (tmp_path / 'custom.png')
    assert Path(result['backup']).read_bytes() == old
    assert new.keys[15].action.target == 'Sistema'
    assert new.keys[6].action.obs_slot == 1


def test_save_audio_input_exact(tmp_path, monkeypatch):
    path = profile_file(tmp_path, monkeypatch)
    info = BACK.profile_info(ROOT)
    BACK.save_mapping(ROOT, {'key_id': 4, 'sha256': info['sha256'], 'label': 'Mic',
                              'operation': 'toggle_mic', 'input': 'Mic/Aux'})
    assert load_profile(path).keys[4].action.obs_source == 'Mic/Aux'


def test_rejects_stale_yaml_without_overwriting(tmp_path, monkeypatch):
    path = profile_file(tmp_path, monkeypatch)
    info = BACK.profile_info(ROOT)
    path.write_text(path.read_text() + '\n# edição concorrente\n')
    current = path.read_bytes()
    with pytest.raises(RuntimeError, match='mudou no disco'):
        BACK.save_mapping(ROOT, {'key_id': 6, 'sha256': info['sha256'], 'label': 'Cena',
                                 'operation': 'scene_name', 'scene': 'Teste'})
    assert path.read_bytes() == current


def test_rejects_modifying_navigation_key_15(tmp_path, monkeypatch):
    path = profile_file(tmp_path, monkeypatch)
    info = BACK.profile_info(ROOT)
    old = path.read_bytes()
    with pytest.raises(ValueError, match='15'):
        BACK.save_mapping(ROOT, {'key_id': 15, 'sha256': info['sha256'],
                                  'label': 'Live', 'operation': 'toggle_stream'})
    assert path.read_bytes() == old


@pytest.mark.parametrize('payload', [
    {'operation': 'stop_stream'},
    {'operation': 'toggle_mic', 'scene': 'Falsa'},
    {'operation': 'scene_name', 'scene': ''},
    {'operation': 'refresh', 'input_name': 'Microfone'},
    {'operation': 'scene_slot', 'slot': 99},
    {'operation': 'toggle_stream', 'slot': 1},
])
def test_action_allowlist_and_field_restrictions(payload):
    with pytest.raises(ValueError):
        BACK.mapping_action(**payload)


class FakeOBS:
    def __init__(self):
        self.calls = []
        self.closed = False
    def call(self, operation, data=None):
        self.calls.append((operation, data))
        responses = {
            'GetVersion': {'obsVersion': '32.2.0', 'obsWebSocketVersion': '5.7.4'},
            'GetSceneList': {'scenes': [{'sceneName': 'Principal'}, {'sceneName': 'Câmera'}], 'currentProgramSceneName': 'Principal'},
            'GetInputList': {'inputs': [{'inputName': 'Mic/Aux', 'inputKind': 'pulse_input_capture'}, {'inputName': 'Desktop', 'inputKind': 'pulse_output_capture'}]},
            'GetSpecialInputs': {'mic1': 'Mic/Aux', 'desktop1': 'Desktop'},
            'GetRecordStatus': {'outputActive': True},
            'GetStreamStatus': {'outputActive': False},
            'GetVirtualCamStatus': {'outputActive': None},
        }
        return responses[operation]
    def close(self):
        self.closed = True


def test_discovery_only_reads_and_hides_credentials():
    fake = FakeOBS()
    result = BACK.discover(lambda _config: fake, lambda: {'password': 'SUPER_SECRET', 'host': '127.0.0.1', 'port': 4455})
    assert result['scenes'] == ['Principal', 'Câmera']
    assert result['mic_input'] == 'Mic/Aux'
    assert result['states']['recording'] is True
    assert result['obs_version'] == '32.2.0'
    assert 'SUPER_SECRET' not in repr(result)
    assert all(name.startswith('Get') for name, _ in fake.calls)
    assert fake.closed


def test_ipc_apply_only_reload():
    seen = []
    value = BACK.apply_to_device(lambda command: seen.append(command) or {'ok': True, 'reloaded': True})
    assert value['reloaded'] and seen == ['reload']


def test_ipc_error_is_reported():
    with pytest.raises(RuntimeError, match='inválido'):
        BACK.apply_to_device(lambda cmd: {'ok': False, 'error': 'YAML inválido'})


def test_scene_name_executes_exact_name_not_position():
    fake = FakeOBS()
    fake.call = lambda command, data=None: (
        {'scenes': [{'sceneName': 'Principal'}, {'sceneName': 'Câmera'}]} if command == 'GetSceneList'
        else fake.calls.append((command, data)) or {})
    action = Action(type='obs', obs_operation='scene_name', obs_scene='Câmera')
    perform_action(fake, action, OBSSnapshot(connected=True), {})
    assert fake.calls == [('SetCurrentProgramScene', {'sceneName': 'Câmera'})]


def test_missing_scene_does_not_send_set_current_scene():
    fake = FakeOBS()
    fake.call = lambda command, data=None: (
        {'scenes': [{'sceneName': 'Principal'}]} if command == 'GetSceneList'
        else fake.calls.append((command, data)) or {})
    action = Action(type='obs', obs_operation='scene_name', obs_scene='Câmera')
    with pytest.raises(OBSError, match='não existe'):
        perform_action(fake, action, OBSSnapshot(connected=True), {})
    assert fake.calls == []


def test_named_scene_image_rgb_100():
    image = obs_image(Action(type='obs', obs_operation='scene_name', obs_scene='Principal'),
                      OBSSnapshot(connected=True, scene='Principal', scenes=('Principal', 'Outra')))
    assert image.size == (100, 100) and image.mode == 'RGB'
