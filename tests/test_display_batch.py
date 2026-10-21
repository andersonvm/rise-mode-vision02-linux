"""Regressões do lote de inicialização Windows, sem USB real."""
import errno
from unittest.mock import Mock, patch
import pytest
from PIL import Image
from vision02.device import Vision02
from vision02.display_preview import DisplayPreview, MirroredDevice
from vision02.protocol import REPORT_SIZE, command

def images():
    return {i: Image.new("RGB", (100, 100), (i, i, i)) for i in range(1, 16)}

@pytest.fixture
def device():
    instance = Vision02(report_delay=0, display_delay=0)
    instance._fd = 100
    return instance

def test_full_batch_command_order_and_cache(device):
    with patch("vision02.device.os.write", return_value=REPORT_SIZE + 1) as write:
        device.set_images_batch(images())
    packets = [c.args[1][1:] for c in write.call_args_list]
    assert packets[0] == command(b"CLE\x00\x00\x00\xff")
    assert packets[-1] == command(b"STP")
    assert packets.count(command(b"STP")) == 1
    headers = [p for p in packets if p.startswith(b"CRT\x00\x00BAT")]
    assert [p[12] for p in headers] == list(range(1, 16))
    assert len(device._display_cache) == 15
    assert not device.faulted

def test_cache_reuse_after_batch(device):
    batch = images()
    with patch("vision02.device.os.write", return_value=REPORT_SIZE + 1) as write:
        device.set_images_batch(batch)
        count = write.call_count
        device.set_image(11, batch[11], skip_unchanged=True)
        assert write.call_count == count
        device.set_image(11, Image.new("RGB", (100, 100), "red"), skip_unchanged=True)
        assert write.call_count > count

@pytest.mark.parametrize("ids", [range(1, 15), range(1, 17)])
def test_reject_incomplete_or_extra_batch(device, ids):
    with patch("vision02.device.os.write", return_value=REPORT_SIZE + 1) as write:
        with pytest.raises(ValueError, match="exatamente"):
            device.set_images_batch({i: None for i in ids})
    write.assert_not_called()

def test_encode_error_before_hid_clear(device):
    batch = images()
    batch[8] = "/file/does/not/exist.png"
    with patch("vision02.device.os.write", return_value=REPORT_SIZE + 1) as write:
        with pytest.raises((OSError, ValueError)):
            device.set_images_batch(batch)
    write.assert_not_called()
    assert not device.faulted

def test_hid_failure_invalidates_entire_cache(device):
    device._display_cache[1] = b"stale"
    error = OSError(errno.EPIPE, "USB disconnected")
    with patch("vision02.device.os.write", side_effect=[REPORT_SIZE + 1, error]):
        with pytest.raises(OSError) as found:
            device.set_images_batch(images())
    assert found.value is error
    assert device.faulted
    assert device._display_cache == {}

def test_stop_failure_does_not_publish_cache(device):
    def writer(_fd, packet):
        if packet[1:] == command(b"STP"):
            raise OSError(errno.EPIPE, "STP failed")
        return REPORT_SIZE + 1
    with patch("vision02.device.os.write", side_effect=writer):
        with pytest.raises(OSError, match="STP failed"):
            device.set_images_batch(images())
    assert device.faulted
    assert device._display_cache == {}

def test_mirrored_batch_only_publishes_after_hid(tmp_path):
    preview = DisplayPreview(tmp_path / "lcd")
    underlying = Mock()
    batch = images()
    MirroredDevice(underlying, preview).set_images_batch(batch)
    underlying.set_images_batch.assert_called_once_with(batch, quality=90, subsampling=0)
    assert preview.manifest("Sistema")["available"]
    assert preview.revision == 15

def test_mirrored_batch_failure_never_publishes(tmp_path):
    preview = DisplayPreview(tmp_path / "lcd")
    underlying = Mock()
    underlying.set_images_batch.side_effect = OSError("broken HID")
    with pytest.raises(OSError, match="broken HID"):
        MirroredDevice(underlying, preview).set_images_batch(images())
    assert preview.manifest("Sistema")["images"] == {}

def test_mirrored_batch_preview_failure_is_nonfatal(tmp_path):
    preview = DisplayPreview(tmp_path / "lcd")
    preview.record = Mock(side_effect=OSError("sem espaço"))
    underlying = Mock()
    MirroredDevice(underlying, preview).set_images_batch(images())
    underlying.set_images_batch.assert_called_once()
    assert preview.manifest("Sistema")["available"] is False
