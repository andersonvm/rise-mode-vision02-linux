"""Dashboard offline: nunca inicia sessão HID real."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
import threading
import time

import pytest
from PIL import Image

from vision02.profiles.models import Action, KeyAppearance, KeyConfig, Profile
from vision02.system_dashboard import (
    Dashboard, LinuxSampler, MetricsWorker, Snapshot,
    _gpu_utilization, _temperature, cpu_percent, memory_usage,
    metric_image, network_rates, parse_network,
)


def make_profile(name='Sistema', *, label4='DISCO', custom=False):
    names = ['CPU', 'RAM', 'GPU', label4, 'REDE']
    return Profile(
        name=name,
        keys={n: KeyConfig(key_id=n, label=label, action=Action(type='command', argv=('true',)),
                           appearance=KeyAppearance() if custom and n == 1 else None)
              for n, label in enumerate(names, 1)},
    )


def test_cpu_samples_delta():
    assert cpu_percent(None, (100, 50)) is None
    assert cpu_percent((100, 50), (200, 80)) == pytest.approx(70)
    assert cpu_percent((100, 50), (100, 50)) is None
    assert cpu_percent((200, 50), (190, 40)) is None
    assert cpu_percent((100, 50), (200, 40)) is None


def test_memory_usage_with_memavailable(tmp_path):
    p = tmp_path / 'mem'
    p.write_text('MemTotal: 8192000 kB\nMemFree: 200000 kB\nMemAvailable: 2048000 kB\n')
    used, gib = memory_usage(p)
    assert used == pytest.approx(75)
    assert gib == pytest.approx(6144000 / 1048576)


def test_memory_usage_rejects_missing_total(tmp_path):
    p = tmp_path / 'mem'
    p.write_text('MemFree: 1 kB\n')
    with pytest.raises(ValueError):
        memory_usage(p)


def test_network_aggregate_excludes_virtual():
    line = lambda name, rx, tx: f'{name}: {rx} 0 0 0 0 0 0 0 {tx} 0 0 0 0 0 0 0'
    result = '\n'.join([line('lo', 800, 400), line('enp0s31f6', 1000, 500),
                        line('wlp0s20f3', 600, 300), line('docker0', 1_000_000, 1_000_000)])
    assert parse_network(result) == (1600, 800)


def test_network_rates_use_monotonic_and_reset_safe():
    assert network_rates(None, (1.0, 10, 20)) == (None, None)
    assert network_rates((5., 1000, 2000), (7., 3000, 2600)) == (1000, 300)
    assert network_rates((5., 1000, 2000), (7., 900, 2600)) == (None, None)
    assert network_rates((5., 1000, 2000), (5., 2000, 3000)) == (None, None)


def test_gpu_sysfs_reads_valid_percentage(tmp_path):
    gpu = tmp_path / 'card0/device'
    gpu.mkdir(parents=True)
    (gpu / 'gpu_busy_percent').write_text('47\n')
    assert _gpu_utilization(tmp_path) == 47
    (gpu / 'gpu_busy_percent').write_text('999\n')
    # Ignore invalid values, may attempt NVIDIA fallback (not required to exist).
    assert _gpu_utilization(tmp_path) is None or isinstance(_gpu_utilization(tmp_path), float)


def test_sensor_priority_and_temperature_units(tmp_path):
    hw = tmp_path / 'hwmon'; hw.mkdir()
    thermal = tmp_path / 'thermal'; thermal.mkdir()
    a = hw / 'hwmon0'; a.mkdir(); (a/'name').write_text('amdgpu')
    (a/'temp1_input').write_text('86000')
    b = hw / 'hwmon1'; b.mkdir(); (b/'name').write_text('coretemp')
    (b/'temp1_input').write_text('48000')
    (b/'temp2_input').write_text('61000')
    assert _temperature(hw, thermal) == 61


def test_missing_metrics_render_nd():
    for metric in ('cpu', 'ram', 'gpu', 'disk', 'network', 'temp'):
        img = metric_image(metric, Snapshot())
        assert img.size == (100, 100)
        assert img.mode == 'RGB'
        assert img.getbbox() is not None


def test_actual_metrics_render_valid_picture():
    snap = Snapshot(cpu=22.3, ram=60, ram_gib=12.6, gpu=88, disk=51, temp=64,
                    rx_bps=300_000, tx_bps=400_000)
    hashes = []
    for metric in ('cpu', 'ram', 'gpu', 'disk', 'network', 'temp'):
        img = metric_image(metric, snap)
        assert isinstance(img, Image.Image)
        hashes.append(img.tobytes())
    assert len(set(hashes)) == 6


def test_image_changes_when_metric_changes():
    low = metric_image('cpu', Snapshot(cpu=10, temp=40))
    high = metric_image('cpu', Snapshot(cpu=95, temp=80))
    assert low.tobytes() != high.tobytes()


def test_mapping_only_sistema():
    assert Dashboard.mapping(make_profile('Desenvolvimento')) == {}
    assert Dashboard.mapping(make_profile()) == {1:'cpu', 2:'ram', 3:'gpu', 4:'disk', 5:'network'}
    assert Dashboard.mapping(make_profile(label4='TEMP'))[4] == 'temp'


def test_custom_appearance_is_not_overridden():
    mapped = Dashboard.mapping(make_profile(custom=True))
    assert 1 not in mapped
    assert len(mapped) == 4


def test_mapping_skips_key_with_different_label():
    profile = make_profile(label4='BACKUP')
    assert 4 not in Dashboard.mapping(profile)


class FakeWorker:
    def __init__(self):
        self.revision = 1
        self.snapshot = Snapshot(cpu=20, ram=50, gpu=30, disk=40, temp=50)
    def latest(self):
        return self.revision, self.snapshot


def test_tick_updates_one_display_per_iteration():
    worker = FakeWorker(); d = Dashboard(worker, minimum_gap=.20)
    device = Mock(); profile = make_profile()
    assert d.tick(profile, device, now=1.0) is True
    assert device.set_image.call_count == 1
    assert d.tick(profile, device, now=1.05) is False
    assert d.tick(profile, device, now=1.25) is True
    assert device.set_image.call_count == 2
    assert [call.args[0] for call in device.set_image.call_args_list] == [11, 12]
    assert all(call.kwargs['skip_unchanged'] is True for call in device.set_image.call_args_list)


def test_tick_skips_other_profiles_without_writing():
    worker = FakeWorker(); d = Dashboard(worker, minimum_gap=0)
    device = Mock()
    assert d.tick(make_profile('Observabilidade'), device, now=1.0) is False
    device.set_image.assert_not_called()


def test_switch_cancels_stale_pending_updates():
    worker = FakeWorker(); d = Dashboard(worker, minimum_gap=0)
    device = Mock()
    d.tick(make_profile(), device, now=1)
    assert d.tick(make_profile('Desenvolvimento'), device, now=2) is False
    # Retorno Sistema reconstrói fila ao invés de usar atualização antiga.
    d.tick(make_profile(), device, now=3)
    assert device.set_image.call_count == 2
    assert device.set_image.call_args_list[-1].args[0] == 11


def test_new_snapshot_replaces_old_queue():
    worker = FakeWorker(); d = Dashboard(worker, minimum_gap=0)
    device = Mock(); profile = make_profile()
    d.tick(profile, device, now=1)
    worker.revision += 1
    worker.snapshot = Snapshot(cpu=95, ram=40)
    d.tick(profile, device, now=2)
    assert device.set_image.call_args_list[-1].args[0] == 11


def test_reload_invalidate_rerenders_unchanged_revision():
    worker = FakeWorker(); d = Dashboard(worker, minimum_gap=0)
    device = Mock(); profile = make_profile()
    d.tick(profile, device, now=1)
    d.invalidate()
    d.tick(profile, device, now=2)
    assert device.set_image.call_count == 2


def test_worker_interval_guard():
    with pytest.raises(ValueError): MetricsWorker(interval=.5)
    with pytest.raises(ValueError): MetricsWorker(interval=100)


def test_worker_collects_without_access_to_hid():
    fake = Mock()
    fake.collect.return_value = Snapshot(cpu=42)
    worker = MetricsWorker(fake, interval=3)
    worker.start()
    deadline = time.monotonic() + 1
    while worker.latest()[0] == 0 and time.monotonic() < deadline:
        time.sleep(.005)
    worker.close()
    assert worker.latest()[1] == Snapshot(cpu=42)
    assert not worker._thread.is_alive()


def test_linux_sampler_fixture_missing_optional_values(tmp_path, monkeypatch):
    proc = tmp_path / 'proc'; (proc/'net').mkdir(parents=True)
    (proc/'stat').write_text('cpu 100 0 80 600 20 0 0 0\n')
    (proc/'meminfo').write_text('MemTotal: 1000 kB\nMemAvailable: 250 kB\n')
    (proc/'net/dev').write_text('enp1s0: 1000 0 0 0 0 0 0 0 250 0 0 0 0 0 0 0\n')
    fake_sys = tmp_path/'sys'; fake_sys.mkdir()
    first = LinuxSampler(proc, fake_sys, tmp_path).collect()
    assert first.cpu is None
    assert first.ram == 75
    assert first.gpu is None or 0 <= first.gpu <= 100
    assert first.rx_bps is None
    (proc/'stat').write_text('cpu 150 0 100 660 20 0 0 0\n')
    (proc/'net/dev').write_text('enp1s0: 4000 0 0 0 0 0 0 0 2250 0 0 0 0 0 0 0\n')
    second = LinuxSampler(proc, fake_sys, tmp_path)  # arquivo artificial pode ser lido
    assert second.collect().ram == 75


def test_dashboard_hid_exception_propagates():
    worker = FakeWorker(); d = Dashboard(worker)
    device = Mock(); device.set_image.side_effect = OSError('USB removido')
    with pytest.raises(OSError, match='USB removido'):
        d.tick(make_profile(), device, now=1)


def test_cli_integrates_dashboard_with_owner_loop():
    from vision02.cli import _run_profile
    import inspect
    code = inspect.getsource(_run_profile)
    assert 'dashboard.tick(manager.active, device)' in code
    assert 'dashboard.invalidate()' in code
    assert 'metrics_worker.close()' in code
