"""Comp. V2: teste de unidade puro, sem gi e sem USB/HID."""
import ast
from pathlib import Path
from types import SimpleNamespace
import pytest
from vision02.studio_composition_v2 import (
    FIELDS, DEFAULT, ZOOMS, CompositionHistory, state_from_fields, apply_state,
    default_target, smart_snap, anchors_for_target, display_geometry,
    hit_image_handle, visible_handle_position, resize_image_scale,
)

S = Path(__file__).resolve().parents[1] / 'apps/vision02_studio.py'
SOURCE = S.read_text()
TREE = ast.parse(SOURCE)
WINDOW = next(x for x in TREE.body if isinstance(x, ast.ClassDef) and x.name == 'StudioWindow')

class Spin:
    def __init__(self, value): self.value=value
    def get_value(self): return self.value
    def set_value(self, value): self.value=value


def test_fields_match_required_appearance_names():
    assert FIELDS == ('image_x', 'image_y', 'image_scale', 'offset_x', 'offset_y')
    assert DEFAULT == (0,0,100,0,0)


def test_state_snapshot_and_application():
    spins={k:Spin(v) for k,v in zip(FIELDS,DEFAULT)}
    assert state_from_fields(spins)==DEFAULT
    apply_state(spins, (10,-5,75,3,-4))
    assert state_from_fields(spins)==(10,-5,75,3,-4)

@pytest.mark.parametrize('values', [(1,2), (True,0,100,0,0), ('1',2,100,0,0)])
def test_reject_malformed_state(values):
    with pytest.raises(ValueError):
        apply_state({k:Spin(0) for k in FIELDS}, values)


def test_history_round_trip():
    h=CompositionHistory()
    a=DEFAULT; b=(10,5,80,0,0); c=(10,5,80,20,0)
    assert h.record(a,b)
    assert h.record(b,c)
    assert h.undo(c)==b
    assert h.undo(b)==a
    assert h.undo(a) is None
    assert h.redo(a)==b
    assert h.redo(b)==c
    assert h.redo(c) is None


def test_history_diverging_clears_redo():
    h=CompositionHistory(); a=DEFAULT; b=(1,2,100,0,0); c=(3,4,100,0,0)
    h.record(a,b); assert h.undo(b)==a
    h.record(a,c)
    assert h.redo_stack == []
    assert h.undo(c)==a


def test_history_noop_does_not_drop_redo():
    h=CompositionHistory(); h.record(DEFAULT,(1,0,100,0,0))
    h.undo((1,0,100,0,0))
    assert not h.record(DEFAULT,DEFAULT)
    assert h.redo(DEFAULT)==(1,0,100,0,0)

@pytest.mark.parametrize('n', [0,-1,1001,'20'])
def test_history_invalid_limit(n):
    with pytest.raises(ValueError): CompositionHistory(limit=n)


def test_history_is_bounded():
    h=CompositionHistory(limit=3)
    for n in range(10):
        h.record((n,0,100,0,0),(n+1,0,100,0,0))
    assert len(h.undo_stack)==3
    assert h.undo_stack[0][0]==7
    h.clear(); assert not h.undo_stack and not h.redo_stack


@pytest.mark.parametrize('target,result', [
    ('image',(0,0,100,30,-20)),
    ('text',(12,-9,65,0,0))
])
def test_reset_target_preserves_other(target,result):
    assert default_target((12,-9,65,30,-20),target)==result


def test_invalid_reset_target():
    with pytest.raises(ValueError): default_target(DEFAULT,'unknown')

@pytest.mark.parametrize('position,expected,guide', [
    (-2,0,0),(2,0,0),(4,4,None),(47,50,50),(-48,-50,-50)
])
def test_smart_snap(position,expected,guide):
    assert smart_snap(position,-100,100,(-50,0,50))==(expected,guide)


def test_smart_snap_tie_prefers_center():
    assert smart_snap(2,-10,10,(0,4))==(0,0)

@pytest.mark.parametrize('target,scale,anchors',[
    ('text',100,(-40,0,40)),
    ('image',80,(-10,0,10)),
    ('image',100,(0,)),
    ('image',150,(-25,0,25)),
])
def test_anchor_geometry(target,scale,anchors):
    assert anchors_for_target(target,scale)==anchors


@pytest.mark.parametrize('zoom,unit', [(1.0,2.4),(1.5,3.6),(2.0,4.8)])
def test_zoom_units(zoom,unit):
    cx,cy,v=display_geometry(240,240,zoom)
    assert cx==cy==120
    assert v==pytest.approx(unit)

@pytest.mark.parametrize('zoom', [0,0.5,2.5,-1])
def test_invalid_zoom(zoom):
    with pytest.raises(ValueError): display_geometry(240,240,zoom)


def test_visible_handle_usable_even_for_large_image():
    assert visible_handle_position(240,240,0,0,200,1.0)==(228,228)
    assert hit_image_handle(228,228,240,240,0,0,200,1.0)
    assert not hit_image_handle(120,120,240,240,0,0,200,1.0)


@pytest.mark.parametrize('dx,dy,zoom,expected',[
    (24,24,1.0,120),(-24,-24,1.0,80),
    (24,24,2.0,110),(0,0,1.0,100),
    (400,400,1.0,200),(-400,-400,1.0,25)
])
def test_resize_direction_and_bounds(dx,dy,zoom,expected):
    assert resize_image_scale(100,dx,dy,2.4*zoom)==expected


def test_invalid_resize():
    with pytest.raises(ValueError): resize_image_scale(100,20,20,0)


def method(name):
    return next(x for x in WINDOW.body if isinstance(x,ast.FunctionDef) and x.name == name)

@pytest.mark.parametrize('name', [
    '_composition_drag_end', '_composition_undo_action', '_composition_redo_action',
    '_composition_reset_action', '_composition_key_pressed', '_composition_zoom_changed',
    '_composition_update_zoom', '_composition_update_buttons',
])
def test_gtk_callbacks_exist(name):
    assert method(name)


def test_ui_has_resize_handle_and_drag_end():
    # A alça precisa ser um widget GTK próprio: a camada Cairo de guias não
    # apareceu em uma sessão GTK/Wayland, deixando a alça antiga invisível.
    draw=ast.get_source_segment(SOURCE,method('_composition_draw'))
    assert 'cr.rectangle(hx-7, hy-7, 14, 14)' not in draw
    assert 'self.composition_resize_handle = Gtk.Frame()' in SOURCE
    assert "resize_drag.connect('drag-end', self._composition_drag_end)" in SOURCE
    assert "gesture.connect('drag-end', self._composition_drag_end)" in SOURCE


def test_zoom_does_not_mutate_form():
    snippet=ast.get_source_segment(SOURCE,method('_composition_zoom_changed'))
    assert '_composition_update_zoom()' in snippet
    assert '_quick_changed' not in snippet
    assert '_quick_save' not in snippet


def test_zoom_updates_picture_without_touching_hid():
    snippet=ast.get_source_segment(SOURCE,method('_composition_update_zoom'))
    assert 'Gdk.Texture.new_for_pixbuf' in snippet
    assert 'crop' in snippet
    assert '_call(' not in snippet


def test_history_clears_on_key_change():
    snippet=ast.get_source_segment(SOURCE,method('_quick_load'))
    assert '_composition_history.clear()' in snippet


def test_legacy_drag_still_available():
    snippet=ast.get_source_segment(SOURCE,method('_composition_drag_update'))
    assert 'clamp_drag(' in snippet
    assert 'grid_coordinate(' in snippet


def test_keyboard_preserves_entry_undo():
    snippet=ast.get_source_segment(SOURCE,method('_composition_key_pressed'))
    assert 'Gtk.Entry' in snippet and 'Gtk.TextView' in snippet
    assert 'Gdk.ModifierType.CONTROL_MASK' in snippet
    assert 'Gdk.ModifierType.SHIFT_MASK' in snippet


def test_undo_never_saves_directly():
    for name in ('_composition_undo_action','_composition_redo_action','_composition_reset_action'):
        snippet=ast.get_source_segment(SOURCE,method(name))
        assert '_quick_save' not in snippet.replace("'quick_save'",'')
        assert "self._call('reload')" not in snippet


def test_preview_remains_original_for_quick_display():
    snippet=ast.get_source_segment(SOURCE,method('_quick_received'))
    assert 'self.quick_picture.set_file(picture_file)' in snippet
    assert 'self.composition_picture.set_file(picture_file)' in snippet
    assert 'self._composition_update_zoom()' in snippet
