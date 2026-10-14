"""Testes do transporte HID sem acesso ao hardware."""

import errno
from unittest.mock import patch

import pytest

from vision02.device import Vision02
from vision02.protocol import REPORT_SIZE


@pytest.fixture
def device():
    """Cria uma instância com um descritor HID simulado."""
    instance = Vision02()
    instance._fd = 100
    return instance


def test_successful_write(device):
    """Uma escrita completa não coloca a sessão em falha."""
    payload = bytes(REPORT_SIZE)

    with patch("vision02.device.os.write", return_value=REPORT_SIZE + 1) as write:
        device._write(payload)

    write.assert_called_once_with(100, b"\x00" + (payload))

    assert device.faulted is False
    assert device.last_error is None


def test_eproto_marks_session_as_faulted(device):
    """EPROTO deve invalidar a sessão."""
    payload = bytes(REPORT_SIZE)

    error = OSError(errno.EPROTO, "Protocol error")

    with patch("vision02.device.os.write", side_effect=error):
        with pytest.raises(OSError) as captured:
            device._write(payload)

    assert captured.value.errno == errno.EPROTO
    assert device.faulted is True
    assert device.last_error is error


def test_write_is_blocked_after_failure(device):
    """Uma sessão inválida não pode transmitir novos relatórios."""
    device._faulted = True

    with patch("vision02.device.os.write") as write:
        with pytest.raises(RuntimeError, match="Sessão HID em falha"):
            device._write(bytes(REPORT_SIZE))

    write.assert_not_called()


def test_short_write_marks_session_as_faulted(device):
    """Uma escrita incompleta deve invalidar a sessão."""
    with patch("vision02.device.os.write", return_value=100):
        with pytest.raises(OSError, match="Escrita HID incompleta"):
            device._write(bytes(REPORT_SIZE))

    assert device.faulted is True
    assert device.last_error is not None


def test_invalid_report_size(device):
    """Relatórios diferentes de 512 bytes devem ser rejeitados."""
    with patch("vision02.device.os.write") as write:
        with pytest.raises(ValueError, match="512 bytes"):
            device._write(b"INVALID")

    write.assert_not_called()
    assert device.faulted is False


def test_close_releases_descriptor(device):
    """O fechamento libera o descritor HID."""
    with patch("vision02.device.os.close") as close:
        device.close()

    close.assert_called_once_with(100)
    assert device._fd is None


def test_reconnect_reinitializes_session(device):
    """Uma reconexão explícita deve reinicializar a sessão."""
    device.path = "/dev/hidraw10"
    device._faulted = True
    device._last_error = OSError(errno.EPROTO, "Protocol error")

    with (
        patch("vision02.device.os.close") as close,
        patch("vision02.device.find_device", return_value="/dev/hidraw11"),
        patch("vision02.device.os.open", return_value=101) as open_mock,
        patch.object(device, "initialize") as initialize,
    ):
        device.reconnect()

    close.assert_called_once_with(100)
    open_mock.assert_called_once()
    initialize.assert_called_once()

    assert str(device.path) == "/dev/hidraw11"
    assert device._fd == 101
    assert device.faulted is False
    assert device.last_error is None


def test_read_error_marks_session_as_faulted(device):
    """Uma falha na leitura deve invalidar a sessão."""
    error = OSError(errno.ENODEV, "Device disconnected")

    with (
        patch("vision02.device.select.select", return_value=([100], [], [])),
        patch("vision02.device.os.read", side_effect=error),
    ):
        with pytest.raises(OSError) as captured:
            device.read_event()

    assert captured.value.errno == errno.ENODEV
    assert device.faulted is True
    assert device.last_error is error


def test_read_is_blocked_after_failure(device):
    """Uma sessão inválida não deve continuar recebendo eventos."""
    device._faulted = True

    with patch("vision02.device.os.read") as read:
        with pytest.raises(RuntimeError, match="Sessão HID em falha"):
            device.read_event()

    read.assert_not_called()
