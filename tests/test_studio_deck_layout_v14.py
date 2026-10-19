"""Regressão de dimensões, centralização e preferências da v14 (sem GTK)."""
from pathlib import Path
import json
import sys
import os

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from vision02.studio_deck_layout_v14 import (
    DECK_ICON_SIZE,DECK_KEY_WIDTH,DECK_KEY_HEIGHT,DECK_COLUMN_SPACING,
    DECK_ROW_SPACING,deck_dimensions,recommended_window_size,
    load_window_size,save_window_size,window_size_path,
)

SRC=(ROOT/'apps/vision02_studio.py').read_text()


def test_deck_is_compact():
    assert DECK_ICON_SIZE <= DECK_KEY_WIDTH <= 110
    assert DECK_KEY_HEIGHT <= 130
    assert 5*DECK_KEY_WIDTH+4*DECK_COLUMN_SPACING < 630
    assert 3*DECK_KEY_HEIGHT+2*DECK_ROW_SPACING < 440


def test_deck_calculates_dimensions():
    assert deck_dimensions()==(574,370)


def test_window_respects_monitor_size():
    assert recommended_window_size(2004,1089)==(1740,914)
    assert recommended_window_size(1366,768)==(1229,645)
    assert recommended_window_size(2560,1440)==(1740,960)
    assert recommended_window_size(None,None)==(1440,840)


def test_window_fallback_rejects_bad_dimensions():
    assert recommended_window_size('fail',False)==(1440,840)
    assert recommended_window_size(100,100)==(1440,840)
    for w,h in [(1280,720),(1920,1080),(3840,2160)]:
        x,y=recommended_window_size(w,h)
        assert x<=w and y<=h


def test_gtk_grid_keeps_fixed_keys_and_center():
    block=SRC.split('    def _build_keys(self):',1)[1].split('    def _build_quick_properties',1)[0]
    for snippet in ('self.key_grid = Gtk.Fixed()',
                    'self.key_grid.set_hexpand(False)',
                    'self.key_grid.set_vexpand(False)',
                    'deck_center.set_center_widget(deck_frame)',
                    'button.set_size_request(DECK_KEY_WIDTH, DECK_KEY_HEIGHT)',
                    'button.set_halign(Gtk.Align.START)',
                    'self.key_grid.put(button,',
                    'key_scroll.set_child(grid_box)'):
        assert snippet in block


def test_3d_css_and_status_survive():
    for snippet in ('button.vision02-deck-key', 'frame.vision02-deck-body',
                    'button.vision02-deck-key.vision02-key-pressed',
                    'button.vision02-deck-key.vision02-key-selected',
                    'self._key_status_labels[key_id] = status'):
        assert snippet in SRC


def test_window_uses_monitors_and_persists():
    for snippet in ('monitors.get_item(0)', 'recommended_window_size(',
                    'load_window_size(width, height)','self.set_default_size(width, height)',
                    'save_window_size(self.get_width(), self.get_height())'):
        assert snippet in SRC


def test_window_save_and_load(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    assert load_window_size(1600,920)==(1600,920)
    path=save_window_size(1400,800)
    assert path==tmp_path/'vision02'/'studio-window.json'
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_window_size(1600,920)==(1400,800)
    assert load_window_size(1280,720)==(1280,720)
    assert json.loads(path.read_text())=={'width':1400,'height':800}


def test_window_rejects_malformed_preferences(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    path=window_size_path(); path.parent.mkdir()
    for data in ('broken', '[1,2]', '{"width":true,"height":700}',
                 '{"width":120,"height":600}'):
        path.write_text(data)
        assert load_window_size(1400,850)==(1400,850)
    assert save_window_size(-1,100) is None


def test_window_symlink_protection(tmp_path,monkeypatch):
    import pytest
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    target=tmp_path/'target'; target.write_text('private')
    path=window_size_path();path.parent.mkdir();path.symlink_to(target)
    assert load_window_size(1400,850)==(1400,850)
    with pytest.raises(ValueError):save_window_size(1400,850)
    assert target.read_text()=='private'
