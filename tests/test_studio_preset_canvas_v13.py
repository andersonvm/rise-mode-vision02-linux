"""v13: canvas puro e regressão da integração GTK com rascunho v12."""
from pathlib import Path
import ast
import importlib.util
import math

import pytest

from vision02.studio_preset_canvas_v13 import (
    POSITION_LIMITS, canvas_regions, select_at, resize_hit, transform,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def style():
    return {
        'image_x': 0, 'image_y': 0, 'image_scale': 50,
        'offset_x': 35, 'offset_y': 35, 'text': 'Teste',
        'show_text': True, 'font_size': 14,
        'horizontal': 'center', 'vertical': 'center',
    }


@pytest.mark.parametrize('zoom', (1.0, 1.5, 2.0))
def test_hit_center_image_all_zooms(style, zoom):
    assert select_at(style, image_present=True, width=320, height=320,
                     zoom=zoom, x=160, y=160) == 'image'


@pytest.mark.parametrize('zoom', (1.0, 1.5, 2.0))
def test_hit_text_not_image(style, zoom):
    regions = canvas_regions(style, image_present=True, width=320, height=320, zoom=zoom)
    text = regions['text']
    x, y = text.x + text.width / 2, text.y + text.height / 2
    assert select_at(style, image_present=True, width=320, height=320,
                     zoom=zoom, x=x, y=y, preferred='text') == 'text'


def test_no_image_does_not_claim_image_region(style):
    regions = canvas_regions(style, image_present=False, width=320, height=320, zoom=1.0)
    assert 'image' not in regions
    assert select_at(style, image_present=False, width=320, height=320,
                     zoom=1.0, x=160, y=160) is None


def test_show_text_false_removes_text_hit(style):
    style['show_text'] = False
    assert 'text' not in canvas_regions(style, image_present=True, width=320, height=320, zoom=1.0)


def test_overlap_selection_uses_explicit_preference(style):
    style['offset_x'] = 0
    style['offset_y'] = 0
    for preferred in ('image', 'text'):
        assert select_at(style, image_present=True, width=320, height=320,
                         zoom=1.0, x=160, y=160, preferred=preferred) == preferred


@pytest.mark.parametrize('x,y', ((-5, 0), (320.5, 0), (0, -1), (0, 340)))
def test_outside_surface_is_not_a_selection(style, x, y):
    assert select_at(style, image_present=True, width=320, height=320,
                     zoom=1.0, x=x, y=y) is None


@pytest.mark.parametrize('x', (math.nan, math.inf, -math.inf))
def test_invalid_position_rejected(style, x):
    with pytest.raises(ValueError):
        select_at(style, image_present=True, width=320, height=320,
                  zoom=1.0, x=x, y=100)


def test_resize_handle_hits_correctly(style):
    # image_x=0, scale=50 -> (240,240) with 320px LCD plane.
    assert resize_hit(style, image_present=True, width=320, height=320,
                      zoom=1.0, x=240, y=240)
    assert not resize_hit(style, image_present=False, width=320, height=320,
                          zoom=1.0, x=240, y=240)
    assert not resize_hit(style, image_present=True, width=320, height=320,
                          zoom=1.0, x=100, y=100)


@pytest.mark.parametrize('zoom', (1.0, 1.5, 2.0))
def test_move_in_lcd_units_across_zooms(style, zoom):
    unit = 3.2 * zoom
    result, guides = transform(style, 'image', 'move', 10 * unit, -7 * unit,
                               320, 320, zoom, snap=False)
    assert (result['image_x'], result['image_y']) == (10, -7)
    assert guides == (None, None)
    assert style['image_x'] == 0


@pytest.mark.parametrize('target,x_key,y_key', (
    ('image', 'image_x', 'image_y'), ('text', 'offset_x', 'offset_y')))
def test_moving_is_local_and_does_not_mutate_style(style, target, x_key, y_key):
    original = dict(style)
    result, _ = transform(style, target, 'move', 32, -16, 320, 320, 1., snap=False)
    assert result[x_key] == (original[x_key] + 10 if target == 'image' else 40)
    assert result[y_key] == original[y_key] - 5
    assert style == original


@pytest.mark.parametrize('target', ('image', 'text'))
def test_move_clamps_to_bounds(style, target):
    x_key, y_key = ('image_x', 'image_y') if target == 'image' else ('offset_x', 'offset_y')
    lo, hi = POSITION_LIMITS[target]
    result, _ = transform(style, target, 'move', 10000, -10000, 320, 320, 1., snap=False)
    assert result[x_key] == hi and result[y_key] == lo


def test_resize_changes_only_image_scale(style):
    result, guide = transform(style, 'image', 'resize', 32, 32, 320, 320, 1.0)
    assert result['image_scale'] == 70
    assert guide == (None, None)
    for k in style:
        if k != 'image_scale':
            assert result[k] == style[k]


@pytest.mark.parametrize('dx,dy,expected', ((-10000,-10000,25), (10000,10000,200)))
def test_resize_bounded(style, dx, dy, expected):
    result, _ = transform(style, 'image', 'resize', dx, dy, 320, 320, 1.)
    assert result['image_scale'] == expected


def test_resize_text_is_invalid(style):
    with pytest.raises(ValueError):
        transform(style, 'text', 'resize', 1, 1, 320, 320, 1.)


def test_snap_to_center_guide(style):
    style['image_x'] = 7
    result, guides = transform(style, 'image', 'move', -5 * 3.2, 0, 320, 320, 1., snap=True)
    assert result['image_x'] == 0
    assert guides[0] == 0


def test_snap_can_be_disabled(style):
    style['image_x'] = 7
    result, guides = transform(style, 'image', 'move', -5 * 3.2, 0, 320, 320, 1., snap=False)
    assert result['image_x'] == 2
    assert guides == (None, None)


@pytest.mark.parametrize('operation,target', (("move", "wrong"), ("delete", "image"), ("resize", "text")))
def test_operations_rejected(style, operation, target):
    with pytest.raises(ValueError):
        transform(style, target, operation, 1, 2, 320, 320, 1.)


@pytest.mark.parametrize('zoom', (0, 1.2, 4.0))
def test_invalid_zoom_rejected(style, zoom):
    with pytest.raises(ValueError):
        transform(style, 'image', 'move', 1, 1, 320, 320, zoom)


@pytest.mark.parametrize('dx', (math.inf, math.nan))
def test_nonfinite_drag_rejected(style, dx):
    with pytest.raises(ValueError):
        transform(style, 'image', 'move', dx, 0, 320, 320, 1.)


def test_gtk_integration_preserves_existing_editor_contract():
    src = (ROOT / 'apps/vision02_studio.py').read_text()
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'StudioWindow')
    methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    for method in ('_build_preset_canvas_v13', '_preset_canvas_drag_begin',
                   '_preset_canvas_drag_update', '_preset_canvas_drag_end',
                   '_preset_canvas_draw', '_preset_canvas_zoom_changed',
                   '_preset_editor_changed', '_preset_editor_save', '_preset_editor_save_as'):
        assert method in methods
    assert "self._build_preset_canvas_v13(box)" in src
    assert "self._preset_canvas_drag_updating or not self._preset_editor_draft" in src
    assert "self._preset_editor_changed()  # uma só entrada de histórico por gesto" in src
    # Não introduzir interface nova que toque IPC, YAML ou backend de dispositivos.
    assert 'vision02_studio_backend.py' not in src.split('def _build_preset_canvas_v13', 1)[1].split('def _preset_editor_active', 1)[0]


def test_module_has_no_side_effect_imports():
    src = (ROOT / 'src/vision02/studio_preset_canvas_v13.py').read_text()
    tree = ast.parse(src)
    imports = [n for n in tree.body if isinstance(n, ast.Import)]
    assert {a.name for n in imports for a in n.names} == {'math'}
    assert 'os.' not in src and 'subprocess' not in src and 'open(' not in src
