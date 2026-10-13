"""Invariantes de concorrência, sem abrir dispositivos reais."""
import errno
import threading
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from vision02.device import Vision02
from vision02.protocol import REPORT_SIZE, command


@contextmanager
def worker(action):
    errors = []
    def run():
        try:
            action()
        except BaseException as exc:
            errors.append(exc)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield errors
    finally:
        thread.join(3)
        assert not thread.is_alive(), "Thread não encerrou"


@pytest.fixture
def device():
    dev = Vision02(report_delay=0, display_delay=0)
    dev._fd = 100
    return dev


def wait_closing(device):
    with device._condition:
        assert device._condition.wait_for(lambda: device._closing, timeout=2)


@pytest.mark.parametrize('transition', ['close', 'reconnect'])
def test_transition_waits_for_tx_and_rejects_new_operations(device, transition):
    started, release = threading.Event(), threading.Event()
    calls = []
    def write(fd, data):
        calls.append((fd, data))
        started.set()
        assert release.wait(2)
        return REPORT_SIZE
    with (
        patch('vision02.device.encode_image', return_value=b'jpeg'),
        patch('vision02.device.image_reports', return_value=[bytes(REPORT_SIZE)]),
        patch('vision02.device.os.write', side_effect=write),
        patch('vision02.device.os.close') as close,
        patch('vision02.device.os.open', return_value=101),
        patch('vision02.device.find_device', return_value='/dev/mock'),
        patch.object(device, 'initialize'),
    ):
        with worker(lambda: device.set_image(11, None)) as tx_errors:
            assert started.wait(2)
            with worker(getattr(device, transition)) as close_errors:
                try:
                    wait_closing(device)
                    close.assert_not_called()
                    for action in (device.read_event, lambda: device.set_image(12, None)):
                        with pytest.raises(RuntimeError, match='encerramento'):
                            action()
                finally:
                    release.set()
        assert not tx_errors and not close_errors
        assert [fd for fd, _ in calls] == [100, 100]
        close.assert_called_once_with(100)
        if transition == 'reconnect':
            device._write(bytes(REPORT_SIZE))
            assert calls[-1][0] == 101


def test_rx_progresses_while_tx_blocked(device):
    started, release = threading.Event(), threading.Event()
    packet = (b'ACK\x00\x00OK\x00\x00' + bytes([3, 1])).ljust(REPORT_SIZE, b'\x00')
    def write(fd, data):
        started.set()
        assert release.wait(2)
        return REPORT_SIZE
    with (
        patch('vision02.device.encode_image', return_value=b'jpeg'),
        patch('vision02.device.image_reports', return_value=[bytes(REPORT_SIZE)]),
        patch('vision02.device.os.write', side_effect=write),
        patch('vision02.device.select.select', return_value=([100], [], [])),
        patch('vision02.device.os.read', return_value=packet),
    ):
        with worker(lambda: device.set_image(11, None)) as errors:
            try:
                assert started.wait(2)
                assert device.read_event() == (3, True)
                assert not release.is_set()
            finally:
                release.set()
        assert not errors


def test_close_waits_for_rx_and_cancels_long_timeout(device):
    started, release = threading.Event(), threading.Event()
    results = []
    def select(*args):
        assert args[-1] <= 0.05
        started.set()
        assert release.wait(2)
        return [], [], []
    with patch('vision02.device.select.select', side_effect=select), patch('vision02.device.os.close') as close:
        with worker(lambda: results.append(device.read_event(3600))) as rx_errors:
            assert started.wait(2)
            with worker(device.close) as close_errors:
                try:
                    wait_closing(device)
                    close.assert_not_called()
                finally:
                    release.set()
        assert not rx_errors and not close_errors
        assert results == [None]
        close.assert_called_once_with(100)
        assert device._active == 0


def test_image_transactions_do_not_interleave(device):
    started, release, second_admitted = (threading.Event() for _ in range(3))
    calls = []
    def encode(source, **kwargs):
        if source == b'b':
            second_admitted.set()
        return source
    def write(fd, data):
        calls.append(data)
        if len(calls) == 1:
            started.set()
            assert release.wait(2)
        return REPORT_SIZE
    with (
        patch('vision02.device.encode_image', side_effect=encode),
        patch('vision02.device.image_reports', side_effect=lambda _, jpeg: [jpeg * REPORT_SIZE] * 2),
        patch('vision02.device.os.write', side_effect=write),
    ):
        with worker(lambda: device.set_image(11, b'a')) as first:
            assert started.wait(2)
            with worker(lambda: device.set_image(12, b'b')) as second:
                try:
                    assert second_admitted.wait(2)
                    assert calls == [b'a' * REPORT_SIZE]
                finally:
                    release.set()
        assert not first and not second
        assert calls == [b'a' * REPORT_SIZE] * 2 + [command(b'STP')] + [b'b' * REPORT_SIZE] * 2 + [command(b'STP')]


@pytest.mark.parametrize('error_number', [errno.EPROTO, errno.EPIPE])
def test_partial_tx_failure_never_retries_or_sends_stop(device, error_number):
    error = OSError(error_number, 'transport')
    with (
        patch('vision02.device.encode_image', return_value=b'jpeg'),
        patch('vision02.device.image_reports', return_value=[bytes(REPORT_SIZE)] * 3),
        patch('vision02.device.os.write', side_effect=[REPORT_SIZE, error]) as write,
    ):
        with pytest.raises(OSError) as caught:
            device.set_image(11, None)
        assert caught.value is error
        assert write.call_count == 2
        assert device.last_error is error and device.faulted
        with pytest.raises(RuntimeError, match='falha'):
            device.set_image(12, None)
        with pytest.raises(RuntimeError, match='falha'):
            device.read_event()
        assert write.call_count == 2
        assert device._active == 0


@pytest.mark.parametrize('exception', [OSError(errno.ENODEV, 'gone'), ValueError('mock'), KeyboardInterrupt()])
def test_read_exceptions_release_operation(device, exception):
    with (
        patch('vision02.device.select.select', return_value=([100], [], [])),
        patch('vision02.device.os.read', side_effect=exception),
        patch('vision02.device.os.close') as close,
    ):
        with pytest.raises(type(exception)):
            device.read_event()
        assert device._active == 0
        if isinstance(exception, OSError):
            assert device.faulted and device.last_error is exception
        device.close()
        close.assert_called_once_with(100)


@pytest.mark.parametrize('exception', [OSError(errno.EPROTO, 'init'), KeyboardInterrupt()])
def test_failed_initialization_releases_fd(exception):
    device = Vision02('/dev/mock')
    with (
        patch('vision02.device.os.open', return_value=101),
        patch('vision02.device.os.write', side_effect=exception),
        patch('vision02.device.os.close') as close,
    ):
        with pytest.raises(type(exception)):
            device.open()
        close.assert_called_once_with(101)
        assert device._fd is None
        assert device._active == 0 and not device._closing


def test_open_and_close_are_serialized():
    device = Vision02('/dev/mock')
    started, release, close_called = (threading.Event() for _ in range(3))
    def initialize():
        started.set()
        assert release.wait(2)
    def closing():
        close_called.set()
        device.close()
    with (
        patch('vision02.device.os.open', return_value=101),
        patch('vision02.device.os.close') as close,
        patch.object(device, 'initialize', side_effect=initialize),
    ):
        with worker(device.open) as opening:
            assert started.wait(2)
            with worker(closing) as shutting:
                try:
                    assert close_called.wait(2)
                    close.assert_not_called()
                    with pytest.raises(RuntimeError, match='encerramento'):
                        device.read_event()
                finally:
                    release.set()
        assert not opening and not shutting
        close.assert_called_once_with(101)
        assert device._fd is None


def test_interrupted_image_invalidates_session(device):
    with (
        patch('vision02.device.encode_image', return_value=b'jpeg'),
        patch('vision02.device.image_reports', return_value=[bytes(REPORT_SIZE)] * 2),
        patch('vision02.device.os.write', side_effect=[REPORT_SIZE, KeyboardInterrupt()]) as write,
        patch('vision02.device.os.close') as close,
    ):
        with pytest.raises(KeyboardInterrupt):
            device.set_image(11, None)
        assert device.faulted and device.last_error is not None
        assert write.call_count == 2 and device._active == 0
        device.close()
        close.assert_called_once_with(100)


def test_lifecycle_inside_operation_rejected_without_deadlock(device):
    with device._operation():
        with pytest.raises(RuntimeError, match='durante operação'):
            device.close()
    assert device._active == 0 and device._fd == 100
