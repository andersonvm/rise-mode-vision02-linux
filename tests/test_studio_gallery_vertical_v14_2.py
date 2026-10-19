"""Regressão estrutural da galeria vertical no Studio GTK4 (sem display)."""
from __future__ import annotations
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'apps/vision02_studio.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
STUDIO = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == 'StudioWindow')


def method(name):
    return ast.get_source_segment(SOURCE, next(node for node in STUDIO.body if isinstance(node, ast.FunctionDef) and node.name == name))


def test_gallery_scroll_has_real_height_and_independent_scroll():
    src = method('_build_quick_properties')
    assert 'gallery_scroll.set_size_request(-1, 300)' in src
    assert 'gallery_scroll.set_min_content_height(270)' in src
    assert 'gallery_scroll.set_vexpand(True)' in src
    assert 'gallery_scroll.set_propagate_natural_height(False)' in src
    assert 'gallery_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)' in src


def test_image_gallery_remains_inside_image_tab():
    src = method('_build_quick_properties')
    assert "image_box = make_tab('Imagem')" in src
    assert "Gtk.Expander(label='Galeria visual de ícones')" in src
    assert 'gallery.set_child(gallery_box)' in src
    assert "self._open_quick_icon_gallery" in src


def test_compact_footer_keeps_all_five_buttons_accessible():
    src = method('_build_quick_properties')
    assert 'footer_buttons = Gtk.Grid(column_spacing=6, row_spacing=6)' in src
    assert 'footer_buttons.attach(control, index % 2, index // 2, 1, 1)' in src
    assert 'footer.insert_child_after(footer_buttons, self.quick_state)' in src
    for name in ('self.quick_preview_btn', 'self.quick_save_btn', 'self.quick_apply_btn', 'discard_btn', 'advanced_btn'):
        assert name in src
    assert 'footer.remove(control)' in src


def test_popup_window_is_bigger_and_scrollable():
    src = method('_open_quick_icon_gallery')
    assert 'window.set_default_size(820, 680)' in src
    assert 'window.set_resizable(True)' in src
    assert 'scroll.set_vexpand(True)' in src
    assert 'flow.set_max_children_per_line(6)' in src
    assert 'picture.set_size_request(90, 90)' in src


def test_popup_filters_same_catalog_and_updates_only_local_preview():
    src = method('_open_quick_icon_gallery')
    assert 'filtered_icons(self._icons, search.get_text())' in src
    assert 'self._quick_pick_icon(_button, chosen)' in src
    assert 'quick_save(' not in src
    assert 'quick_apply(' not in src
    assert 'save_key(' not in src
    assert 'self._call(' not in src


def test_popup_refuses_selection_without_loaded_key_or_during_save():
    src = method('_open_quick_icon_gallery')
    assert "self._quick_loaded is not None and 'quick_save' not in self._busy" in src


def test_popup_highlights_current_icon_and_syncs_main_search():
    src = method('_open_quick_icon_gallery')
    assert "selected = self.quick_image.get_text()" in src
    assert "button.add_css_class('vision02-icon-selected')" in src
    assert 'search.set_text(self.quick_icon_search.get_text())' in src


def test_popup_keeps_one_instance_and_cleans_up_reference():
    src = method('_open_quick_icon_gallery')
    assert 'existing.present()' in src
    assert 'self._quick_icon_gallery_window = None' in src
    assert "window.connect('close-request', on_close)" in src


def test_deck_remains_fixed_5_by_3():
    src = method('_build_keys')
    assert 'self.key_grid = Gtk.Fixed()' in src
    assert 'self.key_grid.put(button, col_x, row_y)' in src
    assert 'deck_center.set_center_widget(deck_frame)' in src


def test_does_not_change_backend_or_export_geometry():
    src = method('_open_quick_icon_gallery')
    assert 'vision02.service' not in src
    assert 'usb' not in src.casefold()
    assert 'subprocess' not in src
