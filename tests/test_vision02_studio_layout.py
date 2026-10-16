"""Regressão do menu lateral, sem exigir GTK ou hardware no CI."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('studio_layout', ROOT / 'apps/vision02_studio_layout.py')
assert SPEC and SPEC.loader
LAYOUT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAYOUT)


def test_default_width_without_settings(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    assert LAYOUT.load_sidebar_width() == 265


def test_width_persisted_across_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    path = LAYOUT.save_sidebar_width(340)
    assert path == tmp_path / 'vision02/studio-ui.json'
    assert LAYOUT.load_sidebar_width() == 340
    assert json.loads(path.read_text()) == {'sidebar_width': 340}
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('source,expected', [(0, 230), (190, 230), (250, 250),
                                             (480, 480), (9999, 480), (-5, 230)])
def test_clamp(source, expected):
    assert LAYOUT.normalize_sidebar_width(source) == expected


@pytest.mark.parametrize('source', [True, False, None, '400', 3.5])
def test_invalid_width_uses_default(source):
    assert LAYOUT.normalize_sidebar_width(source) == 265


def test_invalid_json_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    path = LAYOUT.ui_settings_path()
    path.parent.mkdir()
    path.write_text('{não é JSON', encoding='utf-8')
    assert LAYOUT.load_sidebar_width() == 265


def test_symlink_is_not_followed(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    original = tmp_path / 'important.txt'
    original.write_text('não alterar', encoding='utf-8')
    path = LAYOUT.ui_settings_path()
    path.parent.mkdir(parents=True)
    path.symlink_to(original)
    assert LAYOUT.load_sidebar_width() == 265
    with pytest.raises(ValueError, match='link simbólico'):
        LAYOUT.save_sidebar_width(300)
    assert original.read_text(encoding='utf-8') == 'não alterar'


def test_gtk_layout_has_resizable_divider_and_full_height_sidebar():
    text = (ROOT / 'apps/vision02_studio.py').read_text(encoding='utf-8')
    assert 'Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)' in text
    assert 'self.navigation.set_wide_handle(True)' in text
    assert 'sidebar.set_vexpand(True)' in text
    assert 'sidebar.set_valign(Gtk.Align.FILL)' in text
    assert "self.navigation.connect('notify::position'" in text
    assert 'Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)' not in text


def test_layout_does_not_reference_hid_or_obs_credentials():
    code = (ROOT / 'apps/vision02_studio_layout.py').read_text(encoding='utf-8')
    assert 'hidraw' not in code
    assert 'obs.json' not in code
    assert 'profiles/' not in code
