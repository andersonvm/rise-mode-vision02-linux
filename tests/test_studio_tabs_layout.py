"""Aba de propriedades, histórico pendente e preferência do divisor."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

from vision02 import studio_tabs_layout as tabs

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'apps' / 'vision02_studio.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
WINDOW = next(x for x in TREE.body if isinstance(x, ast.ClassDef) and x.name == 'StudioWindow')


def body(name):
    node = next(x for x in WINDOW.body if isinstance(x, ast.FunctionDef) and x.name == name)
    return ast.get_source_segment(SOURCE, node)


@pytest.mark.parametrize(('given', 'expected'), [
    (None, 535), (True, 535), (False, 535), ('340', 535), (1.5, 535),
    (0, 220), (40, 220), (220, 220), (500, 500), (950, 950), (10000, 950),
    (-100, 220),
])
def test_normalize_panel_width(given, expected):
    assert tabs.normalize_panel_width(given) == expected


def test_defaults_without_file(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    assert tabs.load_panel_width() == tabs.DEFAULT_PANEL_WIDTH
    assert tabs.panel_settings_path().parent == tmp_path / 'vision02'


def test_save_and_restore_private_file(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    destination = tabs.save_panel_width(630)
    assert tabs.load_panel_width() == 630
    assert json.loads(destination.read_text()) == {'grid_width': 630}
    assert destination.stat().st_mode & 0o777 == 0o600
    assert destination.parent.stat().st_mode & 0o777 == 0o700
    assert len(list(destination.parent.iterdir())) == 1
    tabs.save_panel_width(940)
    assert tabs.load_panel_width() == 940


def test_reject_symlink_without_altering_target(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'cfg'))
    other = tmp_path / 'external.json'
    other.write_text('{"grid_width": 605}')
    path = tabs.panel_settings_path()
    path.parent.mkdir(parents=True)
    path.symlink_to(other)
    assert tabs.load_panel_width() == tabs.DEFAULT_PANEL_WIDTH
    with pytest.raises(ValueError, match='simbólico'):
        tabs.save_panel_width(700)
    assert other.read_text() == '{"grid_width": 605}'


@pytest.mark.parametrize('text', ['not json', '{}', '{"grid_width": "800"}', '[]',
                                   '{"grid_width": true}', ''])
def test_bad_preference_does_not_crash(tmp_path, monkeypatch, text):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    p = tabs.panel_settings_path()
    p.parent.mkdir(parents=True)
    p.write_text(text)
    assert tabs.load_panel_width() == tabs.DEFAULT_PANEL_WIDTH


def test_fallback_for_relative_xdg_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', 'relative-invalid')
    assert tabs.panel_settings_path() == Path.home() / '.config/vision02/studio-editor-layout.json'


def test_four_tab_labels_and_scrolled_pages():
    src = body('_build_quick_properties')
    expected = ('Ação', 'Imagem', 'Texto', 'Composição')
    for label in expected:
        assert f"make_tab('{label}')" in src
    assert src.count('= make_tab(') == 4
    assert 'Gtk.Notebook()' in src
    assert 'self.quick_tabs.set_scrollable(True)' in src
    assert 'self.quick_tabs.set_vexpand(True)' in src
    assert 'scroller = Gtk.ScrolledWindow()' in src
    assert 'self.quick_tabs.append_page(scroller, Gtk.Label(label=title))' in src


def test_buttons_remain_fixed_outside_tab_scroll():
    src = body('_build_quick_properties')
    assert 'props_scroll.set_size_request(300, -1)' in src
    assert 'editor_split.set_end_child(props_scroll)' in src
    assert "props_scroll.append(self.quick_tabs)" in src
    assert src.index('props_scroll.append(self.quick_tabs)') < src.index("footer = _box(False, 6)")
    assert 'footer.append(self.quick_state)' in src
    for name in ('self.quick_preview_btn', 'self.quick_save_btn', 'self.quick_apply_btn'):
        assert f'{name} = _button(footer,' in src
    assert 'props_scroll.append(footer)' in src


def test_stable_property_wiring_across_pages():
    src = body('_build_quick_properties')
    for anchor in ('action_box.append(self.quick_kind)',
                   'image_box.append(self.quick_image)',
                   'image_box.append(self.quick_picture)',
                   'text_box.append(self.quick_label)',
                   'text_box.append(self.quick_visual_text)',
                   'self._build_visual_style(text_box, composition_box)',
                   'self._build_composition_canvas(composition_box)'):
        assert anchor in src
    assert '_quick_load(' not in src
    assert '_quick_save(' not in src
    assert '_quick_discard(' not in src
    assert 'self.quick_tabs.connect(' not in src


def test_global_appearance_toggle_reaches_both_pages():
    src = body('_build_visual_style')
    assert "self.style_enabled.connect('toggled', self._visual_style_changed)" in src
    assert "self.style_image_options if name == 'image_fit' else self.style_options" in src
    assert 'if name in IMAGE_RANGES' in src
    assert 'self.style_choices[name] = widget' in src
    assert 'self.style_numbers[name] = spin' in src
    assert 'self.style_image_options.set_sensitive(active)' in body('_update_style_sensitivity')
    assert 'style_enabled' in body('_read_visual_style')


def test_editor_divider_restores_and_saves_preference():
    assert 'editor_split.set_position(max(load_panel_width(), 660))' in body('_build_keys')
    assert "editor_split.connect('notify::position', self._panel_position_changed)" in body('_build_keys')
    assert 'save_panel_width(self.editor_split.get_position())' in body('_persist_panel_width')
    assert 'self._persist_panel_width()' in body('_on_close')
    assert 'self._sidebar_save_timer = 0\n        self._panel_save_timer = 0' not in body('_persist_sidebar_width')


def test_tab_navigation_never_sends_hid_or_writes_yaml():
    src = body('_build_quick_properties')
    assert 'Vision02(' not in SOURCE
    assert 'hidraw' not in src
    assert 'execute_action(' not in src
    assert 'save_key(' not in src
    assert "_button(footer, 'Salvar YAML com backup', self._quick_save)" in src
    assert "_button(footer, 'Aplicar ao dispositivo (IPC)', self._quick_apply)" in src


def test_window_checks_dirty_edits_before_close_or_switch():
    assert 'if self._quick_dirty:' in body('_on_close')
    assert 'if self._quick_dirty:' in body('_quick_load')
    assert 'self._quick_dirty = False' not in body('_build_quick_properties')
