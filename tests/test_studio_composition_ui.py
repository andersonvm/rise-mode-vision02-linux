"""Regression checks for the LCD composition GTK integration.

Tests isolate the GTK callback bodies, with fake widgets. GTK event dispatch and
rendering must be validated on the user's Ubuntu desktop (no gi in CI).
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from vision02.studio_composition import clamp_drag, grid_coordinate
from vision02.studio_composition_v2 import (state_from_fields, anchors_for_target,
    smart_snap, hit_image_handle, resize_image_scale)
from vision02.studio_visual_style import INT_RANGES, IMAGE_RANGES

SOURCE = (Path(__file__).resolve().parents[1] / 'apps' / 'vision02_studio.py').read_text()
TREE = ast.parse(SOURCE)
WINDOW = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == 'StudioWindow')


def method(name):
    node = next(node for node in WINDOW.body if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {'clamp_drag': clamp_drag, 'grid_coordinate': grid_coordinate,
                 'INT_RANGES': INT_RANGES, 'IMAGE_RANGES': IMAGE_RANGES,
                 'state_from_fields': state_from_fields,
                 'anchors_for_target': anchors_for_target, 'smart_snap': smart_snap,
                 'hit_image_handle': hit_image_handle, 'resize_image_scale': resize_image_scale}
    module = ast.Module(body=[node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), '<composition-gtk-callback>', 'exec'), namespace)
    return namespace[name]


class FakeSpin:
    def __init__(self, value=0):
        self.value = value

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value


class FakeCheck:
    def __init__(self, active=False):
        self.active = active

    def get_active(self):
        return self.active

    def set_active(self, active):
        self.active = active


class FakeText:
    def __init__(self):
        self.text = ''

    def set_text(self, value):
        self.text = value


class FakeArea:
    def __init__(self, size=240):
        self.size = size

    def get_width(self):
        return self.size

    def get_height(self):
        return self.size

    def queue_draw(self):
        pass


class FakeSelection:
    def __init__(self, idx):
        self.idx = idx

    def get_selected(self):
        return self.idx


def studio(target=0, style=False, loaded=True, size=240, snap=False):
    result = SimpleNamespace(
        _quick_loaded=object() if loaded else None,
        _busy=set(),
        style_enabled=FakeCheck(style),
        composition_target=FakeSelection(target),
        composition_grid=FakeCheck(snap),
        composition_canvas=FakeArea(size),
        composition_status=FakeText(),
        style_numbers={name:FakeSpin() for name in {**INT_RANGES, **IMAGE_RANGES}},
        _composition_drag_start=(0,0),
        _composition_before_drag=None,
        _composition_drag_kind='move',
        _composition_guide=(None,None),
        _composition_zoom=1.0,
    )
    result.style_numbers['image_scale'].set_value(100)
    return result


def test_picture_is_not_cairo_pixbuf_painting():
    draw = ast.get_source_segment(SOURCE, next(n for n in WINDOW.body if isinstance(n, ast.FunctionDef) and n.name == '_composition_draw'))
    assert 'Gdk.cairo_set_source_pixbuf' not in draw
    assert 'cr.paint()' not in draw
    assert 'cr.stroke()' in draw


def test_canvas_uses_picture_inside_overlay_with_visible_frame():
    for text in ('self.composition_picture = Gtk.Picture()', 'self.composition_surface = Gtk.Overlay()',
                 'self.composition_surface.set_child(self.composition_picture)',
                 'self.composition_surface.add_overlay(self.composition_canvas)',
                 "frame.add_css_class('vision02-composition-surface')"):
        assert text in SOURCE


def test_drag_controller_is_on_surface_not_guides():
    assert 'self.composition_surface.add_controller(gesture)' in SOURCE
    assert 'self.composition_canvas.set_can_target(False)' in SOURCE


def test_selection_automatically_requests_local_preview():
    node = next(n for n in WINDOW.body if isinstance(n, ast.FunctionDef) and n.name == '_quick_received')
    snippet = ast.get_source_segment(SOURCE, node)
    inspect = snippet.split("if command == 'quick_inspect':",1)[1].split("elif command == 'quick_preview':",1)[0]
    assert 'self._quick_preview()' in inspect


def test_preview_is_loaded_into_both_pictures():
    node = next(n for n in WINDOW.body if isinstance(n, ast.FunctionDef) and n.name == '_quick_received')
    snippet = ast.get_source_segment(SOURCE, node)
    preview = snippet.split("elif command == 'quick_preview':",1)[1].split("elif command == 'quick_save':",1)[0]
    assert 'self.quick_picture.set_file(picture_file)' in preview
    assert 'self.composition_picture.set_file(picture_file)' in preview


def test_switching_keys_clears_old_picture_and_dirty_guard():
    node = next(n for n in WINDOW.body if isinstance(n, ast.FunctionDef) and n.name == '_quick_load')
    snippet = ast.get_source_segment(SOURCE, node)
    assert 'if self._quick_dirty:' in snippet
    assert 'self.composition_picture.set_paintable(None)' in snippet


def test_drag_auto_enables_appearance():
    s=studio(style=False)
    method('_composition_drag_begin')(s)
    assert s.style_enabled.get_active() is True
    assert s.composition_status.text.startswith('Arrastando imagem')


@pytest.mark.parametrize('target,fields', [(0,('image_x','image_y')), (1,('offset_x','offset_y'))])
def test_begin_records_correct_fields(target,fields):
    s=studio(target=target)
    s.style_numbers[fields[0]].set_value(7)
    s.style_numbers[fields[1]].set_value(-3)
    method('_composition_drag_begin')(s)
    assert s._composition_drag_start==(7,-3)


@pytest.mark.parametrize('target,size,move,expected', [
    (0,240,(24,-24),(10,-10)),
    (1,240,(24,-24),(10,-10)),
    (0,240,(2400,-2400),(100,-100)),
    (1,240,(2400,-2400),(40,-40)),
    (0,200,(24,-24),(12,-12)),
])
def test_drag_updates_offset(target,size,move,expected):
    s=studio(target=target,style=True,size=size)
    method('_composition_drag_begin')(s)
    method('_composition_drag_update')(s,None,*move)
    names=('image_x','image_y') if target == 0 else ('offset_x','offset_y')
    assert (s.style_numbers[names[0]].get_value(),s.style_numbers[names[1]].get_value())==expected
    assert 'X=' in s.composition_status.text


def test_snap_to_5_pixel_grid():
    s=studio(style=True,snap=True)
    method('_composition_drag_begin')(s)
    method('_composition_drag_update')(s,None,32,13)
    assert s.style_numbers['image_x'].get_value()==15
    assert s.style_numbers['image_y'].get_value()==5


def test_locked_during_save_does_not_move():
    s=studio(style=True)
    s._busy.add('quick_save')
    method('_composition_drag_begin')(s)
    method('_composition_drag_update')(s,None,200,200)
    assert s.style_numbers['image_x'].get_value()==0


def test_missing_key_does_not_enable_appearance():
    s=studio(loaded=False)
    method('_composition_drag_begin')(s)
    assert not s.style_enabled.get_active()
    assert 'Selecione' in s.composition_status.text


def test_zero_canvas_size_reports_problem():
    s=studio(style=True,size=0)
    method('_composition_drag_begin')(s)
    method('_composition_drag_update')(s,None,50,50)
    assert 'indisponível' in s.composition_status.text


def test_css_has_clear_background_and_border():
    assert 'frame.vision02-composition-surface' in SOURCE
    assert 'background-color: #101723' in SOURCE
    assert 'border: 2px solid #3584e4' in SOURCE
