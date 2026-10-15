"""Protocol OBS 5.x, carregador, comandos, dashboard: offline sem HID."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
from unittest.mock import Mock

import pytest
from vision02.obs_websocket import (OBSConnection, OBSError, make_auth, read_config)
from vision02.obs_control import (OBSSnapshot, OBSWorker, perform_action,
                                  collect_snapshot, obs_image, obs_mapping)
from vision02.profiles.models import Action
from vision02.profiles.loader import load_profile, ProfileValidationError
from vision02.system_dashboard import Dashboard


def action(op, *, slot=None, source=None):
    return Action('obs', obs_operation=op, obs_slot=slot, obs_source=source)


def yaml_action(tmp_path, lines):
    p = tmp_path / 'obs.yaml'
    p.write_text('version: 1\nname: OBS Studio\nkeys:\n  1:\n    label: Teste\n    action:\n' + lines)
    return load_profile(p).keys[1].action


@pytest.mark.parametrize('op', ['toggle_record', 'toggle_pause', 'toggle_stream',
    'toggle_mic', 'toggle_desktop', 'next_scene', 'previous_scene',
    'toggle_virtualcam', 'save_replay', 'screenshot', 'refresh'])
def test_load_obs_actions(tmp_path, op):
    act = yaml_action(tmp_path, f'      type: obs\n      operation: {op}\n')
    assert act.obs_operation == op


def test_scene_slot(tmp_path):
    act = yaml_action(tmp_path, '      type: obs\n      operation: scene_slot\n      slot: 3\n')
    assert act.obs_slot == 3


@pytest.mark.parametrize('tail', [
    'operation: exec', 'operation: scene_slot', 'operation: scene_slot\n      slot: 4',
    'operation: toggle_record\n      slot: 1', 'operation: toggle_record\n      input: Foo',
    'operation: toggle_record\n      injected: yes',
])
def test_load_obs_invalid(tmp_path, tail):
    with pytest.raises(ProfileValidationError):
        yaml_action(tmp_path, '      type: obs\n      ' + tail + '\n')


def test_auth_correct_formula():
    passwd, salt, challenge = 'senha forte', 'abcd', 'xyz'
    secret = base64.b64encode(hashlib.sha256((passwd + salt).encode()).digest())
    expected = base64.b64encode(hashlib.sha256(secret + challenge.encode()).digest()).decode()
    assert make_auth(passwd, salt, challenge) == expected


def test_obs_config_local_permissions(tmp_path):
    path = tmp_path / 'obs.json'
    path.write_text(json.dumps({'password': 'secret'}))
    os.chmod(path, 0o600)
    assert read_config(path)['host'] == '127.0.0.1'
    assert read_config(path)['password'] == 'secret'
    path.chmod(0o644)
    with pytest.raises(OBSError, match='0600'):
        read_config(path)


def test_obs_config_reject_remote(tmp_path):
    path = tmp_path / 'obs.json'
    path.write_text(json.dumps({'password': '', 'host': '192.168.0.2'}))
    path.chmod(0o600)
    with pytest.raises(OBSError, match='localhost'):
        read_config(path)


def test_obs_config_symlink_rejected(tmp_path):
    file = tmp_path / 'real.json'
    file.write_text('{}')
    file.chmod(0o600)
    link = tmp_path / 'obs.json'
    link.symlink_to(file)
    with pytest.raises(OBSError, match='simbólico'):
        read_config(link)


class FakeOBS:
    def __init__(self):
        self.calls = []
        self.responses = {
            'GetRecordStatus': {'outputActive': True, 'outputPaused': False},
            'GetStreamStatus': {'outputActive': True},
            'GetVirtualCamStatus': {'outputActive': False},
            'GetReplayBufferStatus': {'outputActive': True},
            'GetSceneList': {'scenes': [{'sceneName': 'Mesa'}, {'sceneName': 'Camera'}, {'sceneName': 'Jogo'}], 'currentProgramSceneName': 'Mesa'},
            'GetSpecialInputs': {'mic1': 'Mic/Aux', 'desktop1': 'Desktop'},
            'GetInputMute': {'inputMuted': True},
        }

    def call(self, name, data=None):
        self.calls.append((name, data))
        return self.responses.get(name, {})


def test_collect_snapshot():
    snapshot = collect_snapshot(FakeOBS(), {})
    assert snapshot.recording is True
    assert snapshot.streaming is True
    assert snapshot.mic_muted is True
    assert snapshot.scenes == ('Mesa', 'Camera', 'Jogo')


@pytest.mark.parametrize('op,expected_request', [
    ('toggle_record','ToggleRecord'), ('toggle_stream','ToggleStream'),
    ('toggle_virtualcam','ToggleVirtualCam'), ('save_replay','SaveReplayBuffer'),
    ('toggle_mic','ToggleInputMute'), ('toggle_desktop','ToggleInputMute'),
    ('toggle_pause','PauseRecord'), ('next_scene','SetCurrentProgramScene'),
    ('previous_scene','SetCurrentProgramScene'), ('scene_slot','SetCurrentProgramScene'),
])
def test_execute_request_type(op, expected_request):
    client = FakeOBS()
    perform_action(client, action(op, slot=2 if op == 'scene_slot' else None), OBSSnapshot(connected=True), {})
    assert client.calls[-1][0] == expected_request
    if op == 'scene_slot':
        assert client.calls[-1][1] == {'sceneName': 'Camera'}


def test_pause_not_recording():
    client = FakeOBS()
    client.responses['GetRecordStatus']['outputActive'] = False
    with pytest.raises(OBSError, match='gravação'):
        perform_action(client, action('toggle_pause'), OBSSnapshot(), {})
    assert len(client.calls) == 1


def test_resume_paused():
    client = FakeOBS()
    client.responses['GetRecordStatus']['outputPaused'] = True
    perform_action(client, action('toggle_pause'), OBSSnapshot(), {})
    assert client.calls[-1][0] == 'ResumeRecord'


def test_input_override():
    client = FakeOBS()
    perform_action(client, action('toggle_mic', source='MIC_USB'), OBSSnapshot(), {})
    assert client.calls[-1][1] == {'inputName': 'MIC_USB'}


def test_missing_input_is_safe():
    client = FakeOBS()
    client.responses['GetSpecialInputs'] = {}
    with pytest.raises(OBSError, match='configure'):
        perform_action(client, action('toggle_mic'), OBSSnapshot(), {})
    assert not any(k == 'ToggleInputMute' for k, _ in client.calls)


def test_worker_rejects_offline():
    worker = OBSWorker(reader=lambda: {'port': 4455})
    with pytest.raises(OBSError, match='desconectado'):
        worker.submit(action('toggle_record'))


def test_worker_submits_connected_and_bounded():
    worker = OBSWorker()
    worker._update(OBSSnapshot(connected=True))
    worker.submit(action('refresh'))
    assert worker._queue.get_nowait().obs_operation == 'refresh'


def test_images_are_rgb_100():
    for op in ('refresh','toggle_record','toggle_mic','scene_slot','next_scene'):
        img = obs_image(action(op, slot=1 if op == 'scene_slot' else None), OBSSnapshot(connected=True, scenes=('Mesa',), scene='Mesa'))
        assert img.mode == 'RGB' and img.size == (100, 100)
        assert obs_image(action(op, slot=1 if op == 'scene_slot' else None), OBSSnapshot()).size == (100, 100)


def test_obs_profile_mapping_and_dashboard(tmp_path):
    from vision02.profiles.models import Profile, KeyConfig
    profile = Profile('OBS Studio', keys={1: KeyConfig(1,'Gravar',action('toggle_record')),
                                         2: KeyConfig(2,'Status',action('refresh'))})
    assert set(obs_mapping(profile)) == {1, 2}
    worker = OBSWorker()
    worker._update(OBSSnapshot(connected=True, recording=True))
    display = Mock()
    class Empty:
        def latest(self):
            return (0, None)
    dash = Dashboard(Empty(), obs_worker=worker, minimum_gap=0.2)
    assert dash.tick(profile, display, now=1) is True
    assert dash.tick(profile, display, now=1.1) is False
    assert dash.tick(profile, display, now=1.3) is True
    assert display.set_image.call_count == 2
    assert dash.tick(Profile('Desenvolvimento'), display, now=1.6) is False


def test_status_updates_without_hid_access():
    from vision02.obs_control import OBSWorker
    worker = OBSWorker()
    revision, snapshot = worker.latest()
    assert not snapshot.connected
    worker._update(OBSSnapshot(connected=True))
    assert worker.latest()[0] == revision + 1
    worker._update(OBSSnapshot(connected=True))
    assert worker.latest()[0] == revision + 1


def test_request_response_success_and_failure():
    class FakeConnection(OBSConnection):
        def __init__(self, responses):
            self.responses = iter(responses)
            self.sent = []
            self._id = 0
        def send_json(self, obj):
            self.sent.append(obj)
        def recv_json(self):
            return next(self.responses)
    valid = {'op': 7, 'd': {'requestId': '1', 'requestStatus': {'result': True}, 'responseData': {'x': 1}}}
    connection = FakeConnection([valid])
    assert connection.call('GetVersion') == {'x': 1}
    assert connection.sent[0]['d']['requestType'] == 'GetVersion'
    invalid = {'op': 7, 'd': {'requestId': '1', 'requestStatus': {'result': False, 'code': 500}}}
    with pytest.raises(OBSError):
        FakeConnection([invalid]).call('ToggleRecord')


def test_websocket_frame_masking(monkeypatch):
    class Sock:
        def __init__(self): self.sent = b''
        def sendall(self, content): self.sent += content
    sock = Sock()
    obs = OBSConnection(sock)
    monkeypatch.setattr('vision02.obs_websocket.secrets.token_bytes', lambda n: b'ABCD' if n == 4 else b'X'*n)
    obs.send_json({'op': 1})
    assert sock.sent[0] == 0x81
    assert sock.sent[1] & 0x80
    length = sock.sent[1] & 0x7f
    decoded = bytes(b ^ b'ABCD'[i % 4] for i,b in enumerate(sock.sent[6:6+length]))
    assert json.loads(decoded) == {'op': 1}
