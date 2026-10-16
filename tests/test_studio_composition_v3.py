"""Composição v3: geometria compartilhada, camadas e UI sem GTK/HID."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from vision02.studio_visual_selection import (
    VisualRegion, hit_visual_element, visual_element_regions,
)

APP = (Path(__file__).resolve().parents[1] / 'apps' / 'vision02_studio.py').read_text()
TREE = ast.parse(APP)
WINDOW = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == 'StudioWindow')


def method(name):
    return ast.get_source_segment(APP, next(
        node for node in WINDOW.body if isinstance(node, ast.FunctionDef) and node.name == name
    ))


def config(**kw):
    values = dict(width=240, height=240, zoom=1.0, image_present=True,
                  image_x=0, image_y=0, image_scale=100, text='Texto',
                  show_text=True, offset_x=0, offset_y=0, font_size=16,
                  horizontal='center', vertical='center')
    values.update(kw)
    return values


def test_visual_regions_and_hit_share_exact_boundaries():
    opts = config(image_scale=25, text='')
    box = visual_element_regions(**opts)['image']
    assert isinstance(box, VisualRegion)
    assert box.contains(box.x, box.y)
    assert hit_visual_element(box.x, box.y, **opts) == 'image'
    assert hit_visual_element(max(0,box.x-1), box.y, **opts) is None


@pytest.mark.parametrize('zoom', (1.0, 1.5, 2.0))
def test_zoom_and_clip(zoom):
    regions = visual_element_regions(**config(zoom=zoom, image_scale=200))
    assert regions['image'] == VisualRegion(0.0, 0.0, 240.0, 240.0)
    assert 0 <= regions['text'].x
    assert regions['text'].x + regions['text'].width <= 240


def test_non_square_canvas_and_outside_widget():
    opts = config(width=320, height=200, image_scale=25, text='')
    r = visual_element_regions(**opts)['image']
    assert r.x > 0 and r.y > 0
    assert hit_visual_element(321, 100, **opts) is None


def test_fully_outside_is_not_drawn():
    assert visual_element_regions(**config(image_x=1000, image_scale=25, text='')) == {}


def test_overlap_priority_has_explicit_user_control():
    opts = config()
    assert hit_visual_element(120, 120, **opts) == 'text'
    assert hit_visual_element(120, 120, prefer='image', **opts) == 'image'
    assert hit_visual_element(120, 120, prefer='text', **opts) == 'text'
    with pytest.raises(ValueError, match='Preferência'):
        hit_visual_element(120, 120, prefer='unknown', **opts)


def test_hidden_text_still_allows_image_selection():
    opts = config(show_text=False)
    assert 'text' not in visual_element_regions(**opts)
    assert hit_visual_element(120, 120, **opts) == 'image'


def test_selected_region_is_one_of_hit_regions():
    opts = config(image_x=15, image_y=-10, offset_x=8, offset_y=5)
    for target, box in visual_element_regions(**opts).items():
        assert box.width > 0 and box.height > 0
        cx = box.x + box.width / 2
        cy = box.y + box.height / 2
        assert hit_visual_element(cx, cy, prefer=target, **opts) == target


def test_cairo_selection_overlay_and_gtk_label():
    draw = method('_composition_draw')
    assert 'visual_element_regions(' in draw
    assert 'cr.rectangle(' in draw
    assert 'cr.stroke()' in draw
    assert 'self.composition_canvas.queue_draw()' in method('_composition_target_changed')
    assert 'self.composition_selected_label' in method('_build_composition_canvas')


def test_explicit_overlap_priority_and_unmodified_gestures():
    build = method('_build_composition_canvas')
    assert 'self.composition_prefer_image = Gtk.CheckButton(' in build
    assert "connect('toggled', self._composition_selection_priority_changed)" in build
    picker = method('_composition_pick_target')
    assert "and self.composition_prefer_image.get_active() else 'text'" in picker
    assert 'self.composition_target.set_selected(' in picker
    assert 'self._composition_pick_target(x, y) is None' in method('_composition_drag_begin')
    assert 'self._composition_history.record(' in method('_composition_drag_end')


def test_no_side_effects_in_new_visual_selection_methods():
    for func in ('_composition_draw', '_composition_selection_priority_changed',
                 '_composition_target_changed'):
        code = method(func)
        assert 'self._quick_save(' not in code
        assert 'self._call(' not in code
        assert 'vision02.service' not in code


def callback(name, namespace=None):
    node = next(n for n in WINDOW.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = dict(namespace or {})
    exec(compile(ast.fix_missing_locations(ast.Module([node], [])), '<v3-callback>', 'exec'), scope)
    return scope[name]


def test_target_change_updates_visible_label_and_redraws():
    from types import SimpleNamespace

    class FakeLabel:
        text = ''
        def set_text(self, text):
            self.text = text

    obj = SimpleNamespace(
        composition_target=SimpleNamespace(get_selected=lambda: 1),
        composition_selected_label=FakeLabel(),
        composition_canvas=SimpleNamespace(queue_draw=lambda: setattr(obj, 'redrawn', True)),
        _composition_update_buttons=lambda: setattr(obj, 'buttons_updated', True),
    )
    callback('_composition_target_changed')(obj)
    assert obj.composition_selected_label.text == 'Seleção atual: Texto'
    assert obj.redrawn and obj.buttons_updated


def test_priority_toggle_only_queues_local_redraw():
    from types import SimpleNamespace

    obj = SimpleNamespace(
        _quick_dirty=False, _quick_saved=True,
        composition_canvas=SimpleNamespace(queue_draw=lambda: setattr(obj, 'redrawn', True)),
    )
    callback('_composition_selection_priority_changed')(obj)
    assert obj.redrawn
    assert obj._quick_saved and not obj._quick_dirty


def test_cairo_outline_matches_visible_selection_geometry():
    from types import SimpleNamespace
    from vision02.studio_composition_v2 import display_geometry

    class Spin:
        def __init__(self, value):
            self.value = value
        def get_value(self):
            return self.value

    class CairoRecorder:
        def __init__(self):
            self.rectangles = []
        def set_line_width(self, *args): pass
        def set_source_rgba(self, *args): pass
        def move_to(self, *args): pass
        def line_to(self, *args): pass
        def stroke(self): pass
        def rectangle(self, *args):
            self.rectangles.append(args)

    obj = SimpleNamespace(
        _composition_zoom=1.0,
        _composition_guide=(None, None),
        _quick_loaded={'profile':'fake'},
        quick_image=SimpleNamespace(get_text=lambda:'icon.png'),
        quick_visual_text=SimpleNamespace(get_text=lambda:'Texto'),
        quick_label=SimpleNamespace(get_text=lambda:'Rótulo'),
        style_show_text=SimpleNamespace(get_active=lambda:True),
        composition_target=SimpleNamespace(get_selected=lambda:1),
        style_numbers={name:Spin(value) for name,value in dict(
            image_x=0, image_y=0, image_scale=100, offset_x=0, offset_y=0,
            font_size=16).items()},
        style_choices={name:SimpleNamespace(get_selected=lambda:1)
                       for name in ('horizontal', 'vertical')},
    )
    cr = CairoRecorder()
    callback('_composition_draw', {
        'display_geometry': display_geometry,
        'visual_element_regions': visual_element_regions,
        'CHOICES': {'horizontal': ('left','center','right'),
                    'vertical': ('top','center','bottom')},
    })(obj, None, cr, 240, 240)
    expected = visual_element_regions(**config())['text']
    assert cr.rectangles == [
        (expected.x, expected.y, expected.width, expected.height),
        (expected.x, expected.y, expected.width, expected.height),
    ]
