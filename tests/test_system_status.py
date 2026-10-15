"""Estados Linux offline: não altera rádios, microfone, perfis nem USB."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
import threading
import time

import pytest
from PIL import Image

from vision02.profiles.models import Action, KeyAppearance, KeyConfig, Profile
from vision02.system_dashboard import Dashboard, Snapshot
from vision02.system_status import (
    LinuxStatusSampler, StatusSnapshot, StatusWorker, bluetooth_state,
    parse_mute, parse_wifi, status_image, status_mapping,
)


def profile(name='Sistema', *, custom=False):
    labels = {1: 'CPU', 2: 'RAM', 3: 'GPU', 4: 'DISCO', 5: 'REDE',
              8: 'MUDO', 9: 'MIC MUDO', 10: 'WIFI', 12: 'BLUETOOTH',
              15: 'VOLTAR'}
    return Profile(name=name, keys={index: KeyConfig(
        key_id=index, label=label,
        action=Action(type='profile', target='Desenvolvimento') if index == 15
        else Action(type='command', argv=('true',)),
        appearance=KeyAppearance() if custom and index == 9 else None,
    ) for index, label in labels.items()})


@pytest.mark.parametrize(('value', 'expected'), [
    ('Volume: 0.50 [MUTED]', True), ('Volume: 1.00', False),
    ('Volume: 0.00', False), ('Mute: yes', True), ('Mute: no', False),
    ('Mute: 1', True), ('Mute: 0', False), ('random', None), ('', None),
])
def test_parse_mute(value, expected):
    assert parse_mute(value) is expected


@pytest.mark.parametrize(('radio', 'devices', 'expected'), [
    ('disabled', '', 'disabled'),
    ('enabled', 'wifi:connected\nethernet:disconnected', 'connected'),
    ('enabled', 'wifi:disconnected\nethernet:connected', 'disconnected'),
    ('enabled', 'ethernet:connected', 'disconnected'),
    ('enabled', 'wifi:connecting', 'connected'),
    ('nonsense', '', None),
    ('', '', None),
])
def test_parse_wifi(radio, devices, expected):
    assert parse_wifi(radio, devices) == expected


def test_rfkill_state_for_bluetooth(tmp_path):
    p = tmp_path / 'rfkill0'; p.mkdir()
    (p / 'type').write_text('wlan'); (p / 'soft').write_text('0'); (p / 'hard').write_text('0')
    assert bluetooth_state(tmp_path) is None
    q = tmp_path / 'rfkill1'; q.mkdir()
    (q / 'type').write_text('bluetooth'); (q / 'soft').write_text('1'); (q / 'hard').write_text('0')
    assert bluetooth_state(tmp_path) is False
    (q / 'soft').write_text('0')
    assert bluetooth_state(tmp_path) is True
    (q / 'hard').write_text('1')
    assert bluetooth_state(tmp_path) is False


def test_rfkill_absent_or_malformed(tmp_path):
    assert bluetooth_state(tmp_path) is None
    p = tmp_path / 'rfkill0'; p.mkdir()
    (p / 'type').write_text('bluetooth'); (p / 'soft').write_text('bad'); (p / 'hard').write_text('0')
    assert bluetooth_state(tmp_path) is None


def test_sampler_gets_all_states_without_side_effects(tmp_path, monkeypatch):
    radio = tmp_path / 'rfkill0'; radio.mkdir()
    (radio / 'type').write_text('bluetooth'); (radio / 'soft').write_text('0'); (radio / 'hard').write_text('0')
    sampler = LinuxStatusSampler(rfkill=tmp_path)
    calls = []
    values = {
        ('wpctl', 'get-volume', '@DEFAULT_AUDIO_SINK@'): 'Volume: 0.55 [MUTED]',
        ('wpctl', 'get-volume', '@DEFAULT_AUDIO_SOURCE@'): 'Volume: 0.45',
        ('nmcli', 'radio', 'wifi'): 'enabled',
        ('nmcli', '-t', '-f', 'TYPE,STATE', 'device', 'status'): 'wifi:connected',
    }
    def fake(argv):
        calls.append(tuple(argv))
        return values.get(tuple(argv))
    monkeypatch.setattr(sampler, '_command', fake)
    sample = sampler.collect()
    assert sample == StatusSnapshot(True, False, 'connected', True)
    assert all(x[0] in {'wpctl', 'nmcli'} for x in calls)


def test_sampler_falls_back_to_pactl(tmp_path, monkeypatch):
    sampler = LinuxStatusSampler(rfkill=tmp_path)
    values = {('pactl', 'get-sink-mute', '@DEFAULT_SINK@'): 'Mute: yes',
              ('pactl', 'get-source-mute', '@DEFAULT_SOURCE@'): 'Mute: no',
              ('nmcli', 'radio', 'wifi'): 'disabled'}
    monkeypatch.setattr(sampler, '_command', lambda args: values.get(tuple(args)))
    result = sampler.collect()
    assert result.audio_muted is True
    assert result.microphone_muted is False
    assert result.wifi == 'disabled'


def test_missing_deps_never_assumed_turned_off(tmp_path, monkeypatch):
    sampler = LinuxStatusSampler(rfkill=tmp_path)
    monkeypatch.setattr(sampler, '_command', lambda args: None)
    assert sampler.collect() == StatusSnapshot()


def test_subprocess_command_is_read_only_and_times_out(monkeypatch):
    def which(binary): return '/usr/bin/' + binary
    monkeypatch.setattr('vision02.system_status.shutil.which', which)
    result = Mock(returncode=0, stdout='Volume: 0.6 [MUTED]\n')
    run = Mock(return_value=result)
    monkeypatch.setattr('vision02.system_status.subprocess.run', run)
    assert LinuxStatusSampler._command(['wpctl', 'get-volume', '@DEFAULT_AUDIO_SINK@']) == 'Volume: 0.6 [MUTED]'
    assert run.call_args.kwargs['timeout'] == 1.0
    assert run.call_args.kwargs['env']['LC_ALL'] == 'C'
    assert run.call_args.args[0] == ['wpctl', 'get-volume', '@DEFAULT_AUDIO_SINK@']


def test_worker_interval_guard():
    with pytest.raises(ValueError): StatusWorker(interval=.5)
    with pytest.raises(ValueError): StatusWorker(interval=90)


def test_worker_snapshot_is_read_only_and_revision_tracks_changes():
    class Sampler:
        def __init__(self): self.status = StatusSnapshot(audio_muted=True)
        def collect(self): return self.status
    sampler = Sampler(); worker = StatusWorker(sampler, interval=1)
    worker.start()
    try:
        for _ in range(100):
            rev, value = worker.latest()
            if rev:
                break
            time.sleep(.005)
        assert (rev, value) == (1, StatusSnapshot(audio_muted=True))
        # O snapshot lido é imutável e nenhuma ação foi executada.
    finally:
        worker.close()


def test_snapshot_immutable():
    with pytest.raises(Exception):
        StatusSnapshot().audio_muted = False


@pytest.mark.parametrize('category', ['audio', 'microphone', 'wifi', 'bluetooth'])
def test_status_image_is_rgb100_and_changes(category):
    before = status_image(category, StatusSnapshot())
    sample = StatusSnapshot(False, True, 'connected', True)
    after = status_image(category, sample)
    assert isinstance(before, Image.Image)
    assert before.size == after.size == (100, 100)
    assert before.mode == after.mode == 'RGB'
    assert before.tobytes() != after.tobytes()


def test_status_image_rejects_unsupported_type():
    with pytest.raises(ValueError): status_image('vpn', StatusSnapshot())


def test_mapping_respects_profile_and_appearance():
    assert status_mapping(profile('Observabilidade')) == {}
    assert status_mapping(profile()) == {8: 'audio', 9: 'microphone', 10: 'wifi', 12: 'bluetooth'}
    assert status_mapping(profile(custom=True)) == {8: 'audio', 10: 'wifi', 12: 'bluetooth'}
    assert 15 not in status_mapping(profile())


def test_mapping_accepts_variations_but_not_unrelated_keys():
    p = profile()
    labels = {8:'ÁUDIO MUDO',9:'MICROFONE MUDO',10:'WI-FI',12:'BT'}
    other = replace(p, keys={k: replace(v, label=labels.get(k, v.label)) for k,v in p.keys.items()})
    assert status_mapping(other) == {8: 'audio', 9: 'microphone', 10: 'wifi', 12: 'bluetooth'}


class Metric:
    def __init__(self): self.revision=1; self.snapshot=Snapshot(cpu=20, ram=40, gpu=10, disk=30)
    def latest(self): return self.revision, self.snapshot


class States:
    def __init__(self): self.revision=1; self.snapshot=StatusSnapshot(True, False, 'connected', False)
    def latest(self): return self.revision, self.snapshot


def test_dashboard_interleaves_metrics_and_status_with_global_rate_limit():
    metrics=Metric(); states=States(); dashboard=Dashboard(metrics, status_worker=states, minimum_gap=.20)
    dev=Mock()
    active=profile()
    assert dashboard.tick(active, dev, now=1) is True
    assert dashboard.tick(active, dev, now=1.05) is False
    assert dashboard.tick(active, dev, now=1.21) is True
    # primeira atualização métrica CPU(11), segunda estado áudio(8 -> BAT 8).
    assert [v.args[0] for v in dev.set_image.call_args_list] == [11,8]
    assert all(v.kwargs['skip_unchanged'] for v in dev.set_image.call_args_list)
    assert dashboard.tick(active, dev, now=1.25) is False


def test_status_change_only_updates_status_queue():
    metric=Metric(); state=States()
    d=Dashboard(metric, status_worker=state, minimum_gap=0)
    dev=Mock(); p=profile()
    assert d.tick(p, dev, now=1) is True
    state.revision += 1
    state.snapshot = replace(state.snapshot, audio_muted=False)
    for n in range(16): d.tick(p, dev, now=2+n)
    # Métricas continuam a ser transmitidas sem ser substituídas pelas mudanças de estado.
    ids=[v.args[0] for v in dev.set_image.call_args_list]
    assert all(k in ids for k in (11,12,13,14,15,8,9,10,2))


def test_switch_clears_pending_status_and_reload_rebuilds():
    metric=Metric(); state=States()
    d=Dashboard(metric, status_worker=state, minimum_gap=0)
    dev=Mock(); p=profile()
    d.tick(p, dev, now=1)
    assert d.tick(profile('Desenvolvimento'), dev, now=2) is False
    count = dev.set_image.call_count
    d.tick(p, dev, now=3)
    assert dev.set_image.call_count == count + 1
    d.invalidate()
    d.tick(p, dev, now=4)
    assert dev.set_image.call_count == count + 2


def test_hid_failure_propagates_to_supervisor():
    d=Dashboard(Metric(), status_worker=States(), minimum_gap=0)
    dev=Mock(); dev.set_image.side_effect=OSError('usb detached')
    with pytest.raises(OSError, match='usb detached'):
        d.tick(profile(), dev, now=1)


def test_profile_without_metrics_can_have_only_statuses():
    p=replace(profile(), keys={8: profile().keys[8]})
    d=Dashboard(Metric(), status_worker=States(), minimum_gap=0)
    dev=Mock()
    assert d.tick(p, dev, now=1)
    assert dev.set_image.call_args.args[0] == 8


def test_non_sistema_no_updates():
    d=Dashboard(Metric(), status_worker=States(), minimum_gap=0)
    dev=Mock()
    assert d.tick(profile('Desenvolvimento'), dev, now=1) is False
    dev.set_image.assert_not_called()
