"""Seleção visual geométrica e integração GTK isolada sem display/HID."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from vision02.studio_visual_selection import hit_visual_element
from vision02.studio_composition_v2 import state_from_fields
CHOICES = {'horizontal': ('left', 'center', 'right'),
           'vertical': ('top', 'center', 'bottom')}

SOURCE = (Path(__file__).resolve().parents[1] / 'apps' / 'vision02_studio.py').read_text()
TREE = ast.parse(SOURCE)
WINDOW = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == 'StudioWindow')


def snippet(name):
    node = next(n for n in WINDOW.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SOURCE, node)


def callback(name):
    node = next(n for n in WINDOW.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = {'hit_visual_element': hit_visual_element, 'CHOICES': CHOICES,
             'state_from_fields': state_from_fields}
    exec(compile(ast.fix_missing_locations(ast.Module([node], [])), '<selection>', 'exec'), scope)
    return scope[name]


def geometry(**options):
    values = dict(x=60., y=60., width=240, height=240, zoom=1.0,
                  image_present=True, image_x=0, image_y=0, image_scale=100,
                  text='Hello', show_text=True, offset_x=0, offset_y=0,
                  font_size=16, horizontal='center', vertical='center')
    values.update(options)
    return hit_visual_element(**values)


def test_text_in_front_of_image():
    assert geometry(x=120,y=120) == 'text'
    assert geometry(x=60,y=60) == 'image'


@pytest.mark.parametrize('zoom,point', [(1.0, (120,120)),(1.5,(120,120)),(2.0,(120,120))])
def test_zoom_preserves_hit_target(zoom,point):
    assert geometry(x=point[0],y=point[1],zoom=zoom) == 'text'


def test_empty_text_or_hidden_text_is_not_selectable():
    assert geometry(x=120,y=120,show_text=False) == 'image'
    assert geometry(x=120,y=120,text='  ') == 'image'


def test_image_absent_and_text_hidden():
    assert geometry(x=120,y=120,image_present=False,show_text=False) is None


def test_outside_image_and_text_is_not_selectable():
    assert geometry(x=1,y=1,image_scale=25) is None
    assert geometry(x=-1,y=120) is None
    assert geometry(x=260,y=120) is None


def test_moved_image_hit_area():
    assert geometry(x=192,y=120,image_scale=25,image_x=30,show_text=False) == 'image'
    assert geometry(x=120,y=120,image_scale=25,image_x=30,show_text=False) is None


def test_text_alignment_offsets():
    assert geometry(x=31,y=29,image_present=False,horizontal='left',vertical='top',
                    offset_x=0,offset_y=0) == 'text'
    assert geometry(x=211,y=211,image_present=False,horizontal='right',vertical='bottom') == 'text'


def test_text_offset():
    assert geometry(x=144,y=96,image_present=False,offset_x=10,offset_y=-10) == 'text'
    assert geometry(x=60,y=60,image_present=False,offset_x=30,offset_y=30) is None


@pytest.mark.parametrize('x,y', [(float('nan'), 5), (float('inf'), 2), (2,float('-inf'))])
def test_invalid_point_returns_none(x,y):
    assert geometry(x=x,y=y) is None


def test_zero_surface_returns_none():
    assert geometry(width=0) is None
    assert geometry(height=0) is None


def test_invalid_text_style_rejected():
    with pytest.raises(ValueError, match='Alinhamento'):
        geometry(horizontal='diagonal')


def test_click_handlers_are_wired_to_surface():
    src=snippet('_build_composition_canvas')
    for expected in ('Gtk.GestureClick.new()', "click.set_button(1)",
                     "click.connect('pressed', self._composition_click_pressed)",
                     "click.connect('released', self._composition_click_released)",
                     'self.composition_surface.add_controller(click)'):
        assert expected in src


def test_click_selects_and_opens_correct_tab_without_saving():
    obj=SimpleNamespace(_composition_drag_did_move=False,
        _composition_pick_target=lambda x,y:'text',
        quick_tabs=SimpleNamespace(set_current_page=lambda page:setattr(obj,'page',page)),
        composition_status=SimpleNamespace(set_text=lambda v:setattr(obj,'status',v)))
    callback('_composition_click_released')(obj,None,1,150,100)
    assert obj.page == 2
    assert 'Texto' in obj.status
    obj._composition_pick_target=lambda x,y:'image'
    callback('_composition_click_released')(obj,None,1,20,80)
    assert obj.page == 1


def test_click_ignores_drag_and_background():
    obj=SimpleNamespace(_composition_drag_did_move=True,
        _composition_pick_target=lambda x,y:'text',
        quick_tabs=SimpleNamespace(set_current_page=lambda _:pytest.fail('no tab switch')),
        composition_status=SimpleNamespace(set_text=lambda _:pytest.fail('no status')))
    callback('_composition_click_released')(obj,None,1,120,120)
    assert obj._composition_drag_did_move is False
    obj._composition_pick_target=lambda x,y: None
    callback('_composition_click_released')(obj,None,1,0,0)
    callback('_composition_click_released')(obj,None,2,0,0)


def test_pressed_resets_previous_drag():
    obj=SimpleNamespace(_composition_drag_did_move=True)
    callback('_composition_click_pressed')(obj)
    assert not obj._composition_drag_did_move


def test_hit_picker_syncs_dropdown_without_mutating_saved_profile():
    class Spin:
        def __init__(self,value):self.value=value
        def get_value(self):return self.value
    class Select:
        def __init__(self,value=0):self.value=value
        def get_selected(self):return self.value
        def set_selected(self,value):self.value=value
    obj=SimpleNamespace(_quick_loaded={'profile':'sample'},_busy=set(),
        composition_canvas=SimpleNamespace(get_width=lambda:240,get_height=lambda:240),
        _composition_zoom=1.0,
        quick_image=SimpleNamespace(get_text=lambda:'icon.png'),
        quick_visual_text=SimpleNamespace(get_text=lambda:'Texto'),
        quick_label=SimpleNamespace(get_text=lambda:'Rotulo'),
        style_show_text=SimpleNamespace(get_active=lambda:True),
        style_numbers={'image_x':Spin(0),'image_y':Spin(0),'image_scale':Spin(100),
                       'font_size':Spin(16),'offset_x':Spin(0),'offset_y':Spin(0)},
        style_choices={'horizontal':Select(1),'vertical':Select(1)},
        composition_target=Select())
    fn=callback('_composition_pick_target')
    assert fn(obj,120,120)=='text'
    assert obj.composition_target.get_selected()==1
    assert fn(obj,35,35)=='image'
    assert obj.composition_target.get_selected()==0
    assert fn(obj,-1,-1) is None
    assert obj.composition_target.get_selected()==0
    obj._busy.add('quick_save')
    assert fn(obj,120,120) is None
    assert obj.composition_target.get_selected()==0


def test_drag_requires_hit_before_activation_and_uses_existing_handlers():
    src=snippet('_composition_drag_begin')
    assert 'self._composition_pick_target(x, y) is None' in src
    assert src.index('self._composition_pick_target(') < src.index('self.style_enabled.set_active(True)')
    assert 'self._composition_before_drag = state_from_fields(self.style_numbers)' in src
    assert 'self._composition_drag_kind' in src
    assert 'self._quick_save(' not in src
    assert 'self._call(' not in src


def test_drag_still_updates_history_and_does_not_apply_hardware():
    assert 'self._composition_history.record(' in snippet('_composition_drag_end')
    assert 'self._composition_drag_did_move = True' in snippet('_composition_drag_update')
    for method in ('_composition_click_released','_composition_pick_target',
                   '_composition_click_pressed'):
        s=snippet(method)
        assert "self._call(" not in s and 'self._quick_save(' not in s
