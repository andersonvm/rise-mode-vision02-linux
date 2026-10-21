"""Controle global de brilho da Vision02 sem usar hardware físico."""
import errno
import json
from unittest.mock import patch

import pytest

from vision02.brightness import (
    DEFAULT_BRIGHTNESS, brightness_path, load_brightness,
    save_brightness, validate_brightness,
)
from vision02.control_ipc import _validate_request
from vision02.device import Vision02
from vision02.protocol import INIT_PAYLOADS, REPORT_SIZE, command


def test_brightness_defaults_to_original_25(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    assert load_brightness() == DEFAULT_BRIGHTNESS == 25


@pytest.mark.parametrize('value', [0, 1, 25, 50, 75, 100])
def test_brightness_roundtrip(monkeypatch, tmp_path, value):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    save_brightness(value)
    assert load_brightness() == value
    assert json.loads(brightness_path().read_text()) == {'brightness': value}
    assert brightness_path().stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('value', [-1, 101, 22.5, True, None, '50', b'50'])
def test_invalid_brightness_never_saved(monkeypatch, tmp_path, value):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    with pytest.raises(ValueError):
        save_brightness(value)
    assert not brightness_path().exists()


def test_config_invalid_falls_back_to_original(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    brightness_path().parent.mkdir(parents=True)
    brightness_path().write_text('{"brightness": true}')
    assert load_brightness() == DEFAULT_BRIGHTNESS


def test_reject_symlink_config_file(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    brightness_path().parent.mkdir(parents=True)
    brightness_path().symlink_to(tmp_path / 'outside')
    with pytest.raises(ValueError, match='simbólicos'):
        save_brightness(70)
    assert brightness_path().is_symlink()


def test_device_emits_single_lig_no_stp_or_cache_invalidation():
    device = Vision02(report_delay=0, display_delay=0)
    device._fd = 10
    device._display_cache[11] = b'existing'
    with patch('vision02.device.os.write', return_value=REPORT_SIZE + 1) as write:
        device.set_brightness(70)
    assert write.call_count == 1
    assert write.call_args.args == (10, b'\x00' + command(b'LIG\x00\x00\x46'))
    assert device.brightness == 70
    assert device._display_cache == {11: b'existing'}


def test_device_invalid_brightness_never_touches_hid():
    device = Vision02()
    device._fd = 10
    with patch('vision02.device.os.write') as write:
        with pytest.raises(ValueError):
            device.set_brightness(150)
    write.assert_not_called()


def test_device_failed_write_keeps_brightness_unchanged():
    device = Vision02()
    device._fd = 10
    with patch('vision02.device.os.write', side_effect=OSError(errno.EPIPE, 'io')):
        with pytest.raises(OSError):
            device.set_brightness(90)
    assert device.brightness == DEFAULT_BRIGHTNESS
    assert device.faulted


def test_init_restores_saved_value(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    save_brightness(60)
    device = Vision02()
    device._fd = 10
    with patch('vision02.device.os.write', return_value=REPORT_SIZE + 1) as write, patch('vision02.device.time.sleep'):
        device.initialize()
    assert write.call_count == len(INIT_PAYLOADS) + 1
    assert write.call_args.args[1] == b'\x00' + command(b'LIG\x00\x00\x3c')
    assert device.brightness == 60


def test_default_init_does_not_add_lig(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    device = Vision02()
    device._fd = 10
    with patch('vision02.device.os.write', return_value=REPORT_SIZE + 1) as write, patch('vision02.device.time.sleep'):
        device.initialize()
    assert write.call_count == len(INIT_PAYLOADS)


@pytest.mark.parametrize('target', [None, '0', '25', '100'])
def test_ipc_accepts_brightness(target):
    req = {'command': 'brightness'}
    if target is not None:
        req['target'] = target
    assert _validate_request(req) == ('brightness', target)


@pytest.mark.parametrize('target', ['101', '-1', '01', '25.0', True, 70, '', 'A'])
def test_ipc_rejects_invalid_brightness(target):
    with pytest.raises(ValueError):
        _validate_request({'command': 'brightness', 'target': target})


def test_cli_brightness_get_and_set_uses_service_not_hid(capsys):
    from vision02.cli import main
    from unittest.mock import Mock
    handler = Mock(return_value={'ok': True, 'brightness': 60})
    with patch('vision02.cli.ipc_request', handler), patch('vision02.cli.Vision02') as cls:
        main(['control', 'brightness', '60'])
        handler.assert_called_with('brightness', '60')
        main(['control', 'brightness'])
        handler.assert_called_with('brightness', None)
        cls.assert_not_called()
    assert '60' in capsys.readouterr().out


def test_cli_brightness_rejects_out_of_range_without_usb():
    from vision02.cli import main
    with patch('vision02.cli.ipc_request') as handler:
        with pytest.raises(SystemExit):
            main(['control', 'brightness', '101'])
        handler.assert_not_called()


def test_studio_backend_brightness_ipc_only():
    import importlib.util
    from pathlib import Path
    from unittest.mock import Mock
    path = Path(__file__).resolve().parents[1] / 'apps' / 'vision02_studio_backend.py'
    spec = importlib.util.spec_from_file_location('brightness_studio_backend', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    handler = Mock(return_value={'ok': True, 'brightness': 70})
    with patch.object(module, 'ipc_request', handler):
        assert module.run('brightness', {'value': 70}) == {'ok': True, 'brightness': 70}
        handler.assert_called_once_with('brightness', '70', timeout=7)
        for bad in ({'value': True}, {'value': -1}, {'value': 101}, {'value': '70'}, {}):
            with pytest.raises(ValueError):
                module.run('brightness', bad)
        assert handler.call_count == 1
