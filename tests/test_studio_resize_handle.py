"""Regressão da alça Gtk.Overlay: testes sem GTK instalado e sem USB/HID.

A posição visível e o despacho real do GTK/Wayland devem ser confirmados
pela validação de desktop. Estes testes verificam ligações dos callbacks e
comportamento isolado de estado, sem prometer cobertura gráfica.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from vision02.studio_composition_v2 import (
    resize_image_scale, state_from_fields, CompositionHistory,
)

SOURCE = (Path(__file__).resolve().parents[1] / 'apps/vision02_studio.py').read_text()
TREE = ast.parse(SOURCE)
WINDOW = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == 'StudioWindow')


def snippet(name):
    return ast.get_source_segment(SOURCE, next(
        x for x in WINDOW.body if isinstance(x, ast.FunctionDef) and x.name == name
    ))


def callback(name, namespace=None):
    node = next(x for x in WINDOW.body if isinstance(x, ast.FunctionDef) and x.name == name)
    scope = dict(namespace or {})
    exec(compile(ast.fix_missing_locations(ast.Module([node], [])), '<gtk-callback>', 'exec'), scope)
    return scope[name]


@pytest.mark.parametrize('required', [
    'self.composition_resize_handle = Gtk.Frame()',
    "self.composition_resize_handle.add_css_class('vision02-resize-handle')",
    'self.composition_resize_handle.set_size_request(40, 40)',
    'self.composition_resize_handle.set_halign(Gtk.Align.END)',
    'self.composition_resize_handle.set_valign(Gtk.Align.END)',
    'self.composition_surface.add_overlay(self.composition_resize_handle)',
    "resize_label = Gtk.Label(label='↘')",
    "resize_drag.connect('drag-begin', self._composition_resize_drag_begin)",
    "resize_drag.connect('drag-update', self._composition_drag_update)",
    "resize_drag.connect('drag-end', self._composition_drag_end)",
    'self.composition_resize_handle.add_controller(resize_drag)',
    'self.composition_target.connect(\'notify::selected\', self._composition_target_changed)',
])
def test_independent_visible_gtk_handle(required):
    assert required in snippet('_build_composition_canvas')


def test_handle_is_last_overlay_above_picture_and_guides():
    source = snippet('_build_composition_canvas')
    assert source.index('self.composition_surface.set_child(self.composition_picture)') < source.index(
        'self.composition_surface.add_overlay(self.composition_canvas)'
    ) < source.index('self.composition_surface.add_overlay(self.composition_resize_handle)')
    assert 'self.composition_surface.add_controller(gesture)' in source  # existing move gesture


def test_handle_high_contrast_css_and_help():
    assert 'frame.vision02-resize-handle' in SOURCE
    assert 'background-color: #1566bc' in SOURCE
    assert 'border: 3px solid #ffffff' in SOURCE
    assert 'self.composition_resize_handle.set_tooltip_text' in SOURCE
    assert 'Arraste esta alça' in SOURCE


def test_cairo_no_longer_renders_click_handle():
    draw=snippet('_composition_draw')
    assert 'cr.rectangle(hx-7' not in draw
    assert 'cr.stroke()' in draw  # guides intact


def test_resize_callback_forces_resize_and_claims_event():
    class Gesture:
        state=None
        def set_state(self,state): self.state=state

    gtk = SimpleNamespace(EventSequenceState=SimpleNamespace(CLAIMED='claimed'))
    fn=callback('_composition_resize_drag_begin', {'Gtk':gtk})
    s=SimpleNamespace(_composition_before_drag=None,
                      _composition_drag_kind='move',
                      composition_status=SimpleNamespace(set_text=lambda msg: setattr(s,'message',msg)))
    def begin():
        s._composition_before_drag=(0,0,100,0,0)
    s._composition_drag_begin=begin
    g=Gesture()
    fn(s,g,4,5)
    assert s._composition_drag_kind=='resize'
    assert 'Redimensionando' in s.message
    assert g.state=='claimed'


def test_resize_callback_does_not_claim_when_no_key():
    gtk = SimpleNamespace(EventSequenceState=SimpleNamespace(CLAIMED='claimed'))
    fn=callback('_composition_resize_drag_begin', {'Gtk':gtk})
    s=SimpleNamespace(_composition_before_drag=None,
                      _composition_drag_kind='move',
                      _composition_drag_begin=lambda:None)
    g=SimpleNamespace(set_state=lambda value: pytest.fail('should not claim'))
    fn(s,g,5,6)
    assert s._composition_drag_kind=='move'


@pytest.mark.parametrize('ready,target,visible', [
    (False,0,False), (True,0,True), (True,1,False),
])
def test_visibility_depends_on_loaded_key_and_image_target(ready,target,visible):
    fn=callback('_composition_update_buttons')
    class Widget:
        def set_sensitive(self,value): self.sensitive=value
        def set_visible(self,value): self.visible=value
    handle=Widget()
    s=SimpleNamespace(_quick_loaded={} if ready else None,_busy=set(),
         composition_target=SimpleNamespace(get_selected=lambda:target),
         _composition_history=CompositionHistory(),
         composition_undo=Widget(), composition_redo=Widget(),
         composition_reset=Widget(), composition_resize_handle=handle)
    fn(s)
    assert handle.visible is visible
    assert s.composition_reset.sensitive is ready


def test_changing_target_redraws_guides_and_toggles_handle():
    fn=callback('_composition_target_changed')
    calls=[]
    s=SimpleNamespace(_composition_update_buttons=lambda:calls.append('buttons'),
                      composition_canvas=SimpleNamespace(queue_draw=lambda:calls.append('draw')))
    fn(s)
    assert calls==['buttons','draw']


def test_resize_still_uses_existing_bounds_and_does_not_touch_hid():
    drag=snippet('_composition_drag_update')
    assert "if self._composition_drag_kind == 'resize':" in drag
    assert 'resize_image_scale(previous, offset_x, offset_y, unit)' in drag
    assert resize_image_scale(100,40,40,2.4)==133
    assert 'HID' not in drag and 'vision02 control' not in drag


def test_selected_profile_and_yamls_unchanged_by_handle():
    assert 'self._quick_save' not in snippet('_composition_resize_drag_begin')
    assert '_call(' not in snippet('_composition_resize_drag_begin')
    assert 'yaml' not in snippet('_composition_resize_drag_begin').lower()
