"""Regressão sem GTK: detector, presença do feedback e separação do HID."""
from pathlib import Path

import pytest

from vision02.studio_interaction import DoubleClickDetector

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / 'apps/vision02_studio.py').read_text(encoding='utf-8')


def test_single_click_never_opens_editor():
    now = [10.]
    detector = DoubleClickDetector(clock=lambda: now[0])
    assert detector.click(5) is False


def test_double_click_same_key_opens_once():
    now = [10.]
    detector = DoubleClickDetector(clock=lambda: now[0])
    assert detector.click(5) is False
    now[0] += .25
    assert detector.click(5) is True
    now[0] += .2
    assert detector.click(5) is False


def test_other_key_resets_click_sequence():
    now = [0.]
    detector = DoubleClickDetector(clock=lambda: now[0])
    assert detector.click(3) is False
    now[0] += .1
    assert detector.click(4) is False
    now[0] += .1
    assert detector.click(3) is False


def test_slow_repeated_clicks_remain_single():
    now = [0.]
    detector = DoubleClickDetector(clock=lambda: now[0])
    assert detector.click(2) is False
    now[0] += .61
    assert detector.click(2) is False


def test_backwards_clock_cannot_create_double_click():
    now = [50.]
    detector = DoubleClickDetector(clock=lambda: now[0])
    assert detector.click(8) is False
    now[0] -= 1.
    assert detector.click(8) is False


@pytest.mark.parametrize('bad', [0, 16, True, False, '5', None])
def test_bad_keys_rejected(bad):
    with pytest.raises(ValueError):
        DoubleClickDetector().click(bad)


def test_click_uses_one_clicked_handler_without_gesture():
    assert "button.connect('clicked', self._key_selected, ident)" in SRC
    assert 'Gtk.GestureClick()' not in SRC
    assert 'self._click_detector.click(key_id)' in SRC
    block = SRC.split('def _key_selected(', 1)[1].split('def _edit_selected_key(', 1)[0]
    assert 'self._render_keys()' not in block
    assert 'self._edit_selected_key()' in block


def test_status_explicitly_visible_with_highlight_css():
    assert "label.vision02-key-status-active" in SRC
    assert "button.vision02-key-pressed" in SRC
    assert "status_label.set_text('PRESSIONADA'" in SRC
    assert "self.key_activity_label.set_text" in SRC
    assert "self._call('key_activity')" in SRC


def test_new_file_does_not_use_usb():
    assert 'Vision02(' not in SRC
    assert 'device.read_event(' not in SRC
