"""Espelho dos LCDs e IPC: testes offline sem USB/HID ou GTK."""
from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import stat
from unittest.mock import Mock

import pytest
from PIL import Image, ImageDraw

from vision02.control_ipc import _validate_request
from vision02.display import encode_image
from vision02.display_preview import DisplayPreview, MirroredDevice, DISPLAY_TO_KEY, preview_root
from vision02.protocol import physical_key_to_display_id


def fixture_image(color=(10, 120, 180)):
    image = Image.new('RGB', (100, 100), color)
    ImageDraw.Draw(image).rectangle((3, 5, 43, 28), fill='white')
    return image


def test_physical_order_1_through_15():
    assert set(DISPLAY_TO_KEY) == set(range(1, 16))
    assert [DISPLAY_TO_KEY[physical_key_to_display_id(k)] for k in range(1, 16)] == list(range(1, 16))
    assert physical_key_to_display_id(1) == 11
    assert physical_key_to_display_id(15) == 5


def test_private_directory_and_files(tmp_path):
    root = tmp_path / 'lcds'
    p = DisplayPreview(root)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    p.record(physical_key_to_display_id(1), fixture_image())
    file = root / 'key-01.png'
    assert file.exists()
    assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert not (root / 'key-11.png').exists()


def test_preview_uses_actual_jpeg_colors_with_reverse_rotation(tmp_path):
    p = DisplayPreview(tmp_path / 'lcds')
    source = fixture_image()
    p.record(physical_key_to_display_id(1), source)
    wire = encode_image(source)
    with Image.open(BytesIO(wire)) as encoded:
        expected = encoded.convert('RGB').transpose(Image.Transpose.ROTATE_180)
    with Image.open(p.root / 'key-01.png') as preview:
        assert preview.size == (100, 100)
        assert preview.mode == 'RGB'
        assert preview.format == 'PNG'
        assert preview.tobytes() == expected.tobytes()


def test_revision_changes_only_for_new_visual_content(tmp_path):
    p = DisplayPreview(tmp_path / 'lcds')
    display_id = physical_key_to_display_id(2)
    p.record(display_id, fixture_image())
    assert p.revision == 1
    p.record(display_id, fixture_image())
    assert p.revision == 1
    p.record(display_id, fixture_image((250, 20, 5)))
    assert p.revision == 2


def test_per_key_manifest_after_all_fifteen_frames(tmp_path):
    p = DisplayPreview(tmp_path / 'lcds')
    for physical in range(1, 16):
        p.record(physical_key_to_display_id(physical), fixture_image((physical, 100, 150)))
    out = p.manifest('Sistema')
    assert out['active'] == 'Sistema'
    assert out['available'] is True
    assert out['revision'] == 15
    assert list(out['images']) == [str(i) for i in range(1, 16)]
    for physical, filename in out['images'].items():
        assert Path(filename).name == f'key-{int(physical):02d}.png'


def test_partial_frames_remain_marked_unavailable(tmp_path):
    p = DisplayPreview(tmp_path / 'lcds')
    p.record(physical_key_to_display_id(1), fixture_image())
    assert p.manifest('OBS — Controle')['available'] is False


def test_old_preview_files_are_cleared_on_new_session(tmp_path):
    root = tmp_path / 'lcds'
    old = DisplayPreview(root)
    old.record(physical_key_to_display_id(1), fixture_image())
    assert (root / 'key-01.png').exists()
    fresh = DisplayPreview(root)
    assert not (root / 'key-01.png').exists()
    assert fresh.manifest('Desenvolvimento')['images'] == {}


def test_directory_symlink_rejected(tmp_path):
    target = tmp_path / 'target'
    target.mkdir()
    link = tmp_path / 'alias'
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(PermissionError):
        DisplayPreview(link)


def test_stale_frame_symlink_rejected(tmp_path):
    root = tmp_path / 'lcds'
    root.mkdir()
    (root / 'key-01.png').symlink_to(tmp_path / 'important')
    with pytest.raises(PermissionError):
        DisplayPreview(root)


def test_runtime_root_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path))
    assert preview_root() == tmp_path / 'vision02' / 'display-preview'


def test_runtime_root_required(monkeypatch):
    monkeypatch.delenv('XDG_RUNTIME_DIR', raising=False)
    with pytest.raises(RuntimeError, match='XDG_RUNTIME_DIR'):
        preview_root()


def test_capture_only_after_successful_device_call(tmp_path):
    preview = DisplayPreview(tmp_path / 'lcds')
    original = Mock()
    mir = MirroredDevice(original, preview)
    img = fixture_image()
    mir.set_image(physical_key_to_display_id(1), img, skip_unchanged=True)
    original.set_image.assert_called_once_with(
        physical_key_to_display_id(1), img, quality=90, subsampling=0,
        skip_unchanged=True,
    )
    assert preview.revision == 1


def test_hid_failure_is_propagated_and_not_published(tmp_path):
    preview = DisplayPreview(tmp_path / 'lcds')
    original = Mock()
    original.set_image.side_effect = OSError('USB desconectado')
    with pytest.raises(OSError, match='USB desconectado'):
        MirroredDevice(original, preview).set_image(
            physical_key_to_display_id(1), fixture_image()
        )
    assert preview.revision == 0


def test_preview_failure_does_not_interrupt_hid(tmp_path):
    preview = DisplayPreview(tmp_path / 'lcds')
    preview.record = Mock(side_effect=OSError('sem espaço'))
    original = Mock()
    MirroredDevice(original, preview).set_image(physical_key_to_display_id(1), fixture_image())
    original.set_image.assert_called_once()
    assert preview.manifest('Sistema')['available'] is False


def test_preview_failure_hides_previous_frames(tmp_path):
    preview = DisplayPreview(tmp_path / 'lcds')
    preview.record(physical_key_to_display_id(1), fixture_image())
    preview.unavailable()
    assert preview.manifest('Sistema')['images'] == {}


def test_proxy_delegates_hid_event_read(tmp_path):
    original = Mock()
    original.read_event.return_value = (15, True)
    wrapper = MirroredDevice(original, DisplayPreview(tmp_path / 'lcds'))
    assert wrapper.read_event(timeout=0.2) == (15, True)
    original.read_event.assert_called_once_with(timeout=0.2)


def test_ipc_accepts_only_no_argument_display_preview():
    assert _validate_request({'command': 'display_preview'}) == ('display_preview', None)
    for bad in ({'command': 'display_preview', 'target': 'Sistema'},
                {'command': 'display_preview', 'path': '/etc/passwd'}):
        with pytest.raises(ValueError):
            _validate_request(bad)


def test_cli_exposes_preview_parser():
    from vision02.cli import build_parser
    args = build_parser().parse_args(['control', 'display_preview'])
    assert args.control_action == 'display_preview'


def test_no_second_usb_connection_in_preview_source():
    from vision02 import display_preview
    source = Path(display_preview.__file__).read_text(encoding='utf-8')
    assert 'Vision02(' not in source
    assert '/dev/hidraw' not in source
