"""Testes de atualização seletiva dos displays, sem hardware."""

import errno
import threading
from unittest.mock import patch

import pytest

from vision02.device import Vision02
from vision02.protocol import REPORT_SIZE


@pytest.fixture
def device():
    dev = Vision02(report_delay=0, display_delay=0)
    dev._fd = 100
    return dev


@pytest.fixture
def transport():
    with (
        patch(
            "vision02.device.encode_image",
            side_effect=lambda source, **kwargs: source,
        ),
        patch(
            "vision02.device.image_reports",
            return_value=[bytes(REPORT_SIZE)],
        ),
        patch(
            "vision02.device.os.write",
            return_value=REPORT_SIZE + 1,
        ) as write,
    ):
        yield write


def test_first_image_is_transmitted(device, transport):
    device.set_image(11, b"imagem-a", skip_unchanged=True)

    # Um relatório de imagem e um STP.
    assert transport.call_count == 2
    assert 11 in device._display_cache


def test_identical_image_is_skipped(device, transport):
    device.set_image(11, b"imagem-a", skip_unchanged=True)
    device.set_image(11, b"imagem-a", skip_unchanged=True)

    assert transport.call_count == 2


def test_different_image_is_transmitted(device, transport):
    device.set_image(11, b"imagem-a", skip_unchanged=True)
    device.set_image(11, b"imagem-b", skip_unchanged=True)

    assert transport.call_count == 4


def test_cache_is_independent_per_display(device, transport):
    device.set_image(11, b"imagem-a", skip_unchanged=True)
    device.set_image(12, b"imagem-a", skip_unchanged=True)

    assert transport.call_count == 4
    assert len(device._display_cache) == 2


def test_default_behavior_preserves_retransmission(device, transport):
    device.set_image(11, b"imagem-a")
    device.set_image(11, b"imagem-a")

    assert transport.call_count == 4


def test_cache_is_invalidated_on_transport_error(device):
    error = OSError(errno.EPROTO, "Protocol error")

    with (
        patch(
            "vision02.device.encode_image",
            return_value=b"imagem-a",
        ),
        patch(
            "vision02.device.image_reports",
            return_value=[bytes(REPORT_SIZE)],
        ),
        patch(
            "vision02.device.os.write",
            side_effect=[REPORT_SIZE + 1, error],
        ),
    ):
        with pytest.raises(OSError) as caught:
            device.set_image(11, None, skip_unchanged=True)

    assert caught.value is error
    assert device.faulted
    assert device._display_cache == {}


def test_close_invalidates_cache(device, transport):
    device.set_image(11, b"imagem-a", skip_unchanged=True)

    assert device._display_cache

    with patch("vision02.device.os.close"):
        device.close()

    assert device._display_cache == {}


def test_reconnect_invalidates_cache(device, transport):
    device.set_image(11, b"imagem-a", skip_unchanged=True)

    with (
        patch("vision02.device.os.close"),
        patch("vision02.device.os.open", return_value=101),
        patch(
            "vision02.device.find_device",
            return_value="/dev/hidraw-mock",
        ),
        patch.object(device, "initialize"),
    ):
        device.reconnect()

    assert device._display_cache == {}
    assert device._fd == 101


def test_concurrent_identical_updates_are_not_duplicated(
    device, transport
):
    barrier = threading.Barrier(3)
    errors = []

    def update():
        try:
            barrier.wait(timeout=3)
            device.set_image(
                11,
                b"imagem-a",
                skip_unchanged=True,
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=update)
        for _ in range(2)
    ]

    for thread in threads:
        thread.start()

    try:
        barrier.wait(timeout=3)
    finally:
        for thread in threads:
            thread.join(timeout=3)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []

    # Apenas uma transmissão: imagem + STP.
    assert transport.call_count == 2
