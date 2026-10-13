"""Testes de sincronização da sessão HID."""

import threading
from unittest.mock import patch

from vision02.device import Vision02
from vision02.protocol import REPORT_SIZE


def test_close_waits_for_image_transmission():
    device = Vision02(report_delay=0, display_delay=0)
    device._fd = 100

    write_started = threading.Event()
    allow_write = threading.Event()
    close_finished = threading.Event()
    failures = []

    def fake_write(data):
        assert len(data) == REPORT_SIZE
        write_started.set()

        if not allow_write.wait(timeout=5):
            raise TimeoutError("Teste excedeu o tempo de espera")

    def transmit():
        try:
            device.set_image(11, "imagem-simulada")
        except Exception as exc:
            failures.append(exc)

    def close_device():
        try:
            device.close()
            close_finished.set()
        except Exception as exc:
            failures.append(exc)

    with (
        patch("vision02.device.encode_image", return_value=b"jpeg"),
        patch(
            "vision02.device.image_reports",
            return_value=[bytes(REPORT_SIZE)],
        ),
        patch.object(device, "_write", side_effect=fake_write),
        patch("vision02.device.os.close") as os_close,
    ):
        transmitter = threading.Thread(target=transmit)
        closer = threading.Thread(target=close_device)

        try:
            transmitter.start()

            assert write_started.wait(timeout=5), (
                "A transmissão não começou"
            )

            closer.start()

            # A transmissão continua bloqueada neste momento.
            assert not close_finished.wait(timeout=0.2), (
                "close() encerrou a sessão durante a transmissão"
            )

        finally:
            allow_write.set()
            transmitter.join(timeout=5)

            if closer.ident is not None:
                closer.join(timeout=5)

        assert not transmitter.is_alive()
        assert not closer.is_alive()
        assert not failures

        assert close_finished.is_set()
        os_close.assert_called_once_with(100)
        assert device._fd is None
