"""Repressão da grade enorme e janela pequena (sem sessão GTK)."""
from __future__ import annotations

import ast
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0,str(ROOT/'src'))
from vision02.studio_deck_layout_v14 import (
    DECK_KEY_WIDTH,DECK_KEY_HEIGHT,DECK_COLUMN_SPACING,DECK_ROW_SPACING,
    deck_dimensions, deck_key_position,
)

SRC=(ROOT/'apps/vision02_studio.py').read_text(encoding='utf-8')

def source_method(name):
    tree=ast.parse(SRC)
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='StudioWindow')
    node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
    return ast.get_source_segment(SRC,node)

@pytest.mark.parametrize('ident, expected', [
    (1,(0,0)),(2,(117,0)),(3,(234,0)),(4,(351,0)),(5,(468,0)),
    (6,(0,127)),(10,(468,127)),(11,(0,254)),(15,(468,254)),
])
def test_key_fixed_position(ident,expected):
    assert deck_key_position(ident)==expected

@pytest.mark.parametrize('ident', [0,16,-1,True,'1',1.2,None])
def test_reject_invalid_key_index(ident):
    with pytest.raises(ValueError):deck_key_position(ident)

def test_all_keys_fit_and_never_overlap():
    width,height=deck_dimensions()
    seen=set()
    for ident in range(1,16):
        x,y=deck_key_position(ident)
        assert x>=0 and y>=0
        assert x+DECK_KEY_WIDTH <= width
        assert y+DECK_KEY_HEIGHT <= height
        assert (x,y) not in seen
        seen.add((x,y))
    assert len(seen)==15
    assert (DECK_COLUMN_SPACING,DECK_ROW_SPACING)==(11,11)

def test_fixed_gtk_surface_does_not_expand_columns():
    source=source_method('_build_keys')
    assert 'self.key_grid = Gtk.Fixed()' in source
    assert 'self.key_grid.put(button, col_x, row_y)' in source
    assert 'col_x, row_y = deck_key_position(ident)' in source
    assert 'self.key_grid.set_hexpand(False)' in source
    assert 'self.key_grid.set_vexpand(False)' in source
    assert 'button.set_halign(Gtk.Align.START)' in source
    assert 'button.set_valign(Gtk.Align.START)' in source
    assert 'self.key_grid.attach(' not in source
    assert 'Gtk.Grid(column_spacing=' not in source

def test_panel_width_migrates_small_saved_value():
    source=source_method('_build_keys')
    assert 'editor_split.set_position(max(load_panel_width(), 660))' in source
    assert 'key_scroll.set_min_content_width(634)' in source
    assert 'deck_frame.set_halign(Gtk.Align.CENTER)' in source
    assert 'deck_center.set_center_widget(deck_frame)' in source

def test_window_starts_maximized_with_restore_controls():
    source=source_method('__init__')
    assert 'self.maximize()' in source
    assert 'self.set_default_size(width, height)' in source
    assert 'self.set_resizable(True)' in source
    assert 'self.fullscreen()' not in source

def test_selection_state_no_longer_expands_fixed_button_width():
    source=source_method('_update_key_highlight')
    assert "number_label.set_text(f'{ident:02d}')" in source
    assert "' • SELECIONADA'" not in source
    assert "button.add_css_class('vision02-key-selected')" in source

def test_preview_still_shows_all_15_buttons_with_live_images():
    source=source_method('_render_keys')
    assert 'for key_id, button in self.key_buttons.items():' in source
    assert 'self._update_key_highlight()' in source
    assert 'self._live_images' in source

