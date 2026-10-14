import pytest

import vision02.device as device_module
from vision02.device import Vision02


@pytest.mark.parametrize("first_byte", [0x00, 0x43, 0xFF])
def test_hidraw_write_preserves_report_bytes(monkeypatch, first_byte):
    report = bytes([first_byte]) + bytes(511)
    writes = []

    def fake_write(fd, payload):
        writes.append((fd, payload))
        return len(payload)

    monkeypatch.setattr(device_module.os, "write", fake_write)

    device = Vision02(path="/dev/fake")
    device._fd = 123

    device._write(report)

    assert writes == [
        (123, b"\x00" + report)
    ]

    assert len(writes[0][1]) == 513
    assert writes[0][1][1:] == report


def test_hidraw_rejects_incomplete_write(monkeypatch):
    monkeypatch.setattr(
        device_module.os,
        "write",
        lambda fd, payload: 512,
    )

    device = Vision02(path="/dev/fake")
    device._fd = 123

    with pytest.raises(OSError, match="512/513"):
        device._write(bytes(512))

    assert device.faulted
