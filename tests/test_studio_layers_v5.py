"""Camadas v5: operações puras e callbacks isolados, sem GTK, IPC nem HID."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from vision02.studio_layers_v5 import (
    LAYER_ORDER, available_layers, hit_layer_candidates, next_overlapping_layer,
)
from vision02.studio_visual_selection import VisualRegion, visual_element_regions

APP = (Path(__file__).resolve().parents[1] / 'apps' / 'vision02_studio.py').read_text()
AST = ast.parse(APP)
WINDOW = next(n for n in AST.body if isinstance(n, ast.ClassDef) and n.name == 'StudioWindow')


def source_of(name):
    node = next(n for n in WINDOW.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(APP, node)


def callback(name, namespace=None):
    node = next(n for n in WINDOW.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = dict(namespace or {})
    exec(compile(ast.fix_missing_locations(ast.Module([node], [])), '<v5-callback>', 'exec'), scope)
    return scope[name]


@pytest.mark.parametrize('image,text,show,expected', [
    ('img.png', 'Texto', True, ('image', 'text')),
    ('img.png', 'Texto', False, ('image',)),
    ('', 'Texto', True, ('text',)),
    (' ', 'Texto', True, ('text',)),
    ('img.png', '', True, ('image',)),
    ('img.png', '   ', True, ('image',)),
    ('', 'Texto', False, ()),
    ('', '', False, ()),
    ('', '', True, ()),
    (' img.png ', '\nTexto\n', True, ('image', 'text')),
])
def test_available_layers(image, text, show, expected):
    assert available_layers(image_path=image, text=text, show_text=show) == expected


@pytest.mark.parametrize('bad', [None, [], {}, 23])
def test_reject_invalid_image_path(bad):
    with pytest.raises(ValueError):
        available_layers(image_path=bad, text='texto', show_text=True)


@pytest.mark.parametrize('bad', [None, [], 12, False])
def test_reject_invalid_text(bad):
    with pytest.raises(ValueError):
        available_layers(image_path='', text=bad, show_text=True)


def test_reject_non_boolean_show_text():
    with pytest.raises(ValueError):
        available_layers(image_path='a', text='b', show_text=1)


REGIONS = {'image': VisualRegion(10, 10, 100, 100),
           'text': VisualRegion(50, 50, 30, 30)}


@pytest.mark.parametrize('point, expected', [
    ((0, 0), ()), ((10, 10), ('image',)), ((60, 60), ('image', 'text')),
    ((80, 80), ('image', 'text')), ((110, 110), ('image',)),
    ((111, 110), ()), ((float('nan'), 70), ()),
    ((float('inf'), 40), ()), ((40, float('-inf')), ()),
])
def test_hit_candidates(point, expected):
    assert hit_layer_candidates(REGIONS, *point) == expected


def test_hit_candidates_ignore_unknown_keys_and_follow_fixed_order():
    shuffled = {'text': REGIONS['text'], 'other': VisualRegion(0,0,100,100),
                'image': REGIONS['image']}
    assert LAYER_ORDER == ('image', 'text')
    assert hit_layer_candidates(shuffled, 60, 60) == LAYER_ORDER


@pytest.mark.parametrize('current,expected', [('image', 'text'), ('text', 'image')])
def test_next_overlap_layer_switches_bidirectionally(current, expected):
    assert next_overlapping_layer(REGIONS, 60, 60, current) == expected


@pytest.mark.parametrize('regions,x,y', [(REGIONS, 20, 20), (REGIONS, 0, 0),
                                       ({'image': REGIONS['image']}, 60, 60), ({}, 0, 0)])
def test_next_overlap_needs_two_regions(regions, x, y):
    assert next_overlapping_layer(regions, x, y, 'image') is None


def test_invalid_selected_layer_is_rejected():
    with pytest.raises(ValueError):
        next_overlapping_layer(REGIONS, 60, 60, 'background')


class Button:
    def __init__(self):
        self.sensitive = False
        self.css = set()
    def set_sensitive(self, value):
        self.sensitive = value
    def add_css_class(self, value):
        self.css.add(value)
    def remove_css_class(self, value):
        self.css.discard(value)


class Selection:
    def __init__(self, index=0):
        self.index = index
    def get_selected(self):
        return self.index
    def set_selected(self, index):
        self.index = index


class Check:
    def __init__(self, active=False):
        self.active = active
    def get_active(self):
        return self.active
    def set_active(self, value):
        self.active = value


class Label:
    def __init__(self):
        self.text = ''
    def set_text(self, value):
        self.text = value


def mock_window(*, loaded=True, layers=('image', 'text'), selected=0, busy=False):
    obj = SimpleNamespace(
        _quick_loaded=object() if loaded else None,
        _busy={'quick_save'} if busy else set(),
        _composition_last_overlap=None,
        _quick_dirty=False,
        _quick_saved=True,
        _composition_history=SimpleNamespace(undo_stack=[], redo_stack=[]),
        composition_target=Selection(selected),
        composition_prefer_image=Check(),
        composition_status=Label(),
        composition_layers_status=Label(),
        composition_layer_buttons={k: Button() for k in ('image', 'text')},
        composition_cycle_overlap=Button(),
        composition_canvas=SimpleNamespace(queue_draw=lambda: None),
    )
    obj._composition_available_layers = lambda: layers if obj._quick_loaded is not None else ()
    obj._composition_layer_regions = lambda: REGIONS
    obj._composition_update_layer_panel = lambda: callback('_composition_update_layer_panel', {
        'hit_layer_candidates': hit_layer_candidates,
    })(obj)
    obj._composition_select_layer = lambda layer: callback('_composition_select_layer')(obj, layer)
    return obj


def test_layer_panel_shows_available_and_selected():
    obj = mock_window(layers=('image', 'text'), selected=1)
    obj._composition_update_layer_panel()
    assert obj.composition_layer_buttons['image'].sensitive
    assert obj.composition_layer_buttons['text'].sensitive
    assert 'suggested-action' in obj.composition_layer_buttons['text'].css
    assert 'suggested-action' not in obj.composition_layer_buttons['image'].css
    assert obj.composition_layers_status.text.endswith('Imagem, Texto')


@pytest.mark.parametrize('loaded,busy,expected', [
    (True, False, True), (False, False, False), (True, True, False),
])
def test_layer_panel_respects_ready_state(loaded, busy, expected):
    obj = mock_window(loaded=loaded, busy=busy)
    obj._composition_update_layer_panel()
    assert obj.composition_layer_buttons['image'].sensitive is expected
    assert obj.composition_layer_buttons['text'].sensitive is expected


def test_absent_layer_disabled_in_panel():
    obj = mock_window(layers=('image',), selected=1)
    obj._composition_update_layer_panel()
    assert obj.composition_layer_buttons['image'].sensitive
    assert not obj.composition_layer_buttons['text'].sensitive
    assert 'suggested-action' not in obj.composition_layer_buttons['text'].css
    assert obj.composition_layers_status.text.endswith('Imagem')


@pytest.mark.parametrize('selected,prefer,expected', [
    ('image', True, 0), ('text', False, 1),
])
def test_manual_layer_selection_is_local_and_sets_hit_priority(selected, prefer, expected):
    obj = mock_window()
    assert obj._composition_select_layer(selected) is True
    assert obj.composition_target.get_selected() == expected
    assert obj.composition_prefer_image.get_active() is prefer
    assert obj._quick_dirty is False and obj._quick_saved is True
    assert obj._composition_history.undo_stack == []


@pytest.mark.parametrize('layers,target', [
    (('image',), 'text'), (('text',), 'image'), ((), 'text'),
])
def test_missing_layer_cannot_be_selected(layers, target):
    obj = mock_window(layers=layers)
    assert obj._composition_select_layer(target) is False
    assert obj.composition_target.get_selected() == 0


@pytest.mark.parametrize('loaded,busy', [(False, False), (True, True)])
def test_layer_selection_is_blocked_while_unavailable(loaded, busy):
    obj = mock_window(loaded=loaded, busy=busy)
    assert obj._composition_select_layer('text') is False
    assert obj.composition_target.get_selected() == 0


def test_capture_and_cycle_overlap_in_both_directions_without_dirty():
    obj = mock_window(selected=1)
    capture = callback('_composition_capture_overlap', {'hit_layer_candidates': hit_layer_candidates})
    cycle = callback('_composition_cycle_overlap_action', {'next_overlapping_layer': next_overlapping_layer})
    capture(obj, 60, 60)
    assert obj._composition_last_overlap == (60, 60)
    assert obj.composition_cycle_overlap.sensitive
    assert cycle(obj)
    assert obj.composition_target.get_selected() == 0
    assert cycle(obj)
    assert obj.composition_target.get_selected() == 1
    assert not obj._quick_dirty and obj._quick_saved


def test_nonoverlap_click_clears_cycle_button():
    obj = mock_window()
    obj._composition_last_overlap = (60, 60)
    capture = callback('_composition_capture_overlap', {'hit_layer_candidates': hit_layer_candidates})
    capture(obj, 20, 20)
    assert obj._composition_last_overlap is None
    assert not obj.composition_cycle_overlap.sensitive


def test_capture_during_save_does_not_expose_stale_overlap():
    obj = mock_window(busy=True)
    obj._composition_last_overlap = (60, 60)
    callback('_composition_capture_overlap', {'hit_layer_candidates': hit_layer_candidates})(obj, 60, 60)
    assert obj._composition_last_overlap is None
    assert not obj.composition_cycle_overlap.sensitive


def test_overlapping_region_moved_since_click_prevents_cycle():
    obj = mock_window()
    obj._composition_last_overlap = (60, 60)
    obj._composition_layer_regions = lambda: {'image': REGIONS['image']}
    cycle = callback('_composition_cycle_overlap_action', {'next_overlapping_layer': next_overlapping_layer})
    assert cycle(obj) is False
    assert obj._composition_last_overlap is None
    assert obj.composition_target.get_selected() == 0


def test_gtk_layer_regions_uses_existing_preview_geometry():
    obj = SimpleNamespace(
        composition_canvas=SimpleNamespace(get_width=lambda: 240, get_height=lambda: 240),
        _composition_zoom=1.0,
        quick_image=SimpleNamespace(get_text=lambda: 'icon.png'),
        quick_visual_text=SimpleNamespace(get_text=lambda: 'Texto'),
        quick_label=SimpleNamespace(get_text=lambda: 'Rótulo'),
        style_show_text=Check(True),
        style_numbers={key:SimpleNamespace(get_value=lambda value=v: value) for key,v in {
            'image_x':0, 'image_y':0, 'image_scale':100, 'offset_x':0,
            'offset_y':0, 'font_size':16}.items()},
        style_choices={'horizontal':Selection(1), 'vertical':Selection(1)},
    )
    func = callback('_composition_layer_regions', {
        'visual_element_regions': visual_element_regions,
        'CHOICES': {'horizontal': ('left','center','right'),
                    'vertical': ('top','center','bottom')},
    })
    regions = func(obj)
    assert hit_layer_candidates(regions, 120, 120) == ('image', 'text')


def test_wiring_and_regression_protection():
    code = source_of('_build_composition_canvas')
    assert "Gtk.Expander(label='Camadas — seleção local')" in code
    assert 'self.composition_layer_buttons[layer] = button' in code
    assert 'self._composition_cycle_overlap_action' in code
    assert 'self._composition_update_layer_panel()' in code
    assert 'self.composition_prefer_image' in code
    assert '_composition_last_overlap = None' in source_of('_quick_load')
    assert 'self._composition_capture_overlap(x, y)' in source_of('_composition_click_released')
    assert "self.quick_tabs.set_current_page(1 if selected == 'image' else 2)" in source_of('_composition_click_released')
    assert 'self._composition_update_layer_panel()' in source_of('_composition_update_buttons')
    draw = source_of('_composition_draw')
    assert 'for other, other_region in regions.items()' in draw
    assert 'visual_element_regions(' in draw


def test_new_callbacks_do_not_save_apply_or_operate_device():
    for method_name in ('_composition_available_layers', '_composition_layer_regions',
                        '_composition_update_layer_panel', '_composition_select_layer',
                        '_composition_capture_overlap', '_composition_cycle_overlap_action'):
        body = source_of(method_name)
        for forbidden in ('.save(', '_quick_save(', '_quick_apply(', 'subprocess.', 'self._call(', 'usb', 'hid.'):
            assert forbidden not in body
