"""v8: hit-test real por canal alfa, sem acesso a GTK/HID/YAML."""
from __future__ import annotations

import ast
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from vision02.studio_alpha_hit_v8 import (
    DEFAULT_THRESHOLD, LCD_WIDTH, LCD_HEIGHT, MASK_LENGTH,
    extract_alpha, widget_pixel, mask_candidates, choose_mask_layer,
    next_mask_layer, mask_regions,
)

APP_PATH = Path(__file__).resolve().parents[1] / 'apps' / 'vision02_studio.py'
APP = APP_PATH.read_text()
CLASS = next(node for node in ast.parse(APP).body
             if isinstance(node, ast.ClassDef) and node.name == 'StudioWindow')


def source_of(name):
    return ast.get_source_segment(APP, next(node for node in CLASS.body
        if isinstance(node, ast.FunctionDef) and node.name == name))


def callback(name, globals_=None):
    node = next(n for n in CLASS.body if isinstance(n, ast.FunctionDef) and n.name == name)
    ns = dict(globals_ or {})
    exec(compile(ast.fix_missing_locations(ast.Module([node], [])), '<v8-callback>', 'exec'), ns)
    return ns[name]


def bitmask(*pixels):
    result = bytearray(MASK_LENGTH)
    for x, y, alpha in pixels:
        result[y * LCD_WIDTH + x] = alpha
    return bytes(result)


def point(x, y, zoom=1.0, width=240, height=240):
    unit = min(width, height) / 100 * zoom
    return width / 2 + (x - 49.5) * unit, height / 2 + (y - 49.5) * unit


def masks():
    return {'image': bitmask((20, 20, 255), (40, 40, 128), (60, 60, 10)),
            'text': bitmask((40, 40, 255), (50, 50, 255))}


@pytest.mark.parametrize('x,y', [(0, 0), (1, 1), (20, 21), (49, 49),
                                 (50, 50), (98, 98), (99, 99)])
@pytest.mark.parametrize('zoom', [1.0, 1.5, 2.0])
def test_logical_pixels_map_to_widget_at_all_zooms(x, y, zoom):
    wx, wy = point(x, y, zoom)
    if 0 <= wx < 240 and 0 <= wy < 240:
        assert widget_pixel(wx, wy, 240, 240, zoom) == (x, y)
    else:
        assert widget_pixel(wx, wy, 240, 240, zoom) is None


@pytest.mark.parametrize('width,height', [(300, 200), (200, 300), (240, 240)])
def test_non_square_widget_maps_center_to_pixel_50(width, height):
    assert widget_pixel(width / 2 + .01, height / 2 + .01,
                        width, height, 1.0) == (50, 50)


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf'), None, '3'])
def test_nonfinite_or_invalid_coordinate_is_ignored(bad):
    assert widget_pixel(bad, 120, 240, 240, 1) is None
    assert widget_pixel(120, bad, 240, 240, 1) is None


def test_only_rgba_opaque_pixels_are_selectable():
    x, y = point(40, 40)
    assert mask_candidates(masks(), x, y, 240, 240, 1) == ('image', 'text')
    x, y = point(20, 20)
    assert mask_candidates(masks(), x, y, 240, 240, 1) == ('image',)
    x, y = point(50, 50)
    assert mask_candidates(masks(), x, y, 240, 240, 1) == ('text',)
    x, y = point(30, 30)
    assert mask_candidates(masks(), x, y, 240, 240, 1) == ()


def test_antialiasing_threshold_ignores_nearly_transparent_fringe():
    x, y = point(60, 60)
    assert mask_candidates(masks(), x, y, 240, 240, 1) == ()
    assert mask_candidates(masks(), x, y, 240, 240, 1, threshold=10) == ('image',)


@pytest.mark.parametrize('threshold', [0, 256, -1, True, None, 1.1])
def test_invalid_alpha_cutoff_rejected(threshold):
    with pytest.raises(ValueError):
        mask_candidates(masks(), 120, 120, 240, 240, 1, threshold=threshold)
    with pytest.raises(ValueError):
        mask_regions(masks(), 240, 240, 1, threshold=threshold)


def test_visibility_disables_hit_even_when_channel_is_opaque():
    x, y = point(40, 40)
    assert mask_candidates(masks(), x, y, 240, 240, 1,
                           visible={'image': False, 'text': True}) == ('text',)
    assert mask_candidates(masks(), x, y, 240, 240, 1,
                           visible={'image': False, 'text': False}) == ()


@pytest.mark.parametrize('prefer, expected', [('text', 'text'), ('image', 'image')])
def test_overlap_preference_follows_manual_setting(prefer, expected):
    assert choose_mask_layer(('image', 'text'), prefer) == expected


def test_no_hit_does_not_select_geometry_behind_transparency():
    assert choose_mask_layer((), 'text') is None
    assert choose_mask_layer(('image',), 'text') == 'image'
    assert choose_mask_layer(('text',), 'image') == 'text'


@pytest.mark.parametrize('current, expected', [('image', 'text'), ('text', 'image')])
def test_overlap_cycles_without_changing_render_order(current, expected):
    assert next_mask_layer(('image', 'text'), current) == expected
    assert next_mask_layer(('image',), current) is None
    assert next_mask_layer(('text',), current) is None
    assert next_mask_layer((), current) is None


def test_mask_region_tracks_actual_opaque_content():
    region = mask_regions(masks(), 240, 240, 1)
    assert region['image'].contains(*point(20, 20))
    assert region['image'].contains(*point(40, 40))
    assert region['text'].contains(*point(40, 40))
    assert not region['text'].contains(*point(20, 20))
    assert region['image'].width < 240
    assert region['image'].height < 240


@pytest.mark.parametrize('zoom', [1.0, 1.5, 2.0])
def test_regions_are_clipped_at_visible_canvas(zoom):
    result = mask_regions({'image': bitmask((0, 0, 255), (99, 99, 255))},
                          240, 240, zoom)
    value = result['image']
    assert 0 <= value.x <= 240 and 0 <= value.y <= 240
    assert value.x + value.width <= 240
    assert value.y + value.height <= 240


def test_empty_alpha_creates_no_region():
    assert mask_regions({'image': bytes(MASK_LENGTH)}, 240, 240, 1) == {}


def test_invalid_or_missing_mask_is_not_treated_as_opaque():
    assert mask_candidates({'image': bytes(3)}, 120, 120, 240, 240, 1) == ()
    assert mask_regions({'image': bytes(3)}, 240, 240, 1) == {}


def test_stride_decoder_handles_row_padding():
    stride = 404
    rgba = bytearray(stride * 100)
    rgba[40 * stride + 30 * 4 + 3] = 199
    rgba[99 * stride + 99 * 4 + 3] = 17
    mask = extract_alpha(bytes(rgba), 100, 100, stride, 4)
    assert len(mask) == 10000
    assert mask[40 * 100 + 30] == 199
    assert mask[9999] == 17
    assert mask[0] == 0


@pytest.mark.parametrize('width,height,stride,channels,alpha', [
    (99, 100, 396, 4, True), (100, 99, 400, 4, True),
    (100, 100, 399, 4, True), (100, 100, 400, 3, True),
    (100, 100, 400, 4, False),
])
def test_decoder_rejects_wrong_pixbuf_metadata(width, height, stride, channels, alpha):
    with pytest.raises(ValueError):
        extract_alpha(bytes(404 * 100), width, height, stride, channels, has_alpha=alpha)


def test_decoder_rejects_truncated_pixel_buffer():
    with pytest.raises(ValueError):
        extract_alpha(b'\0' * 100, 100, 100, 400, 4)


def test_alpha_masks_agree_with_v7_real_components(tmp_path):
    from vision02.studio_preview_layers_v7 import render_rgba_components
    from vision02.profiles.models import KeyAppearance
    icon = tmp_path / 'icon.png'
    bitmap = Image.new('RGBA', (100, 100), (0, 0, 0, 0))
    bitmap.putpixel((5, 5), (255, 0, 0, 255))
    bitmap.save(icon)
    parts = render_rgba_components('Texto', icon, KeyAppearance(image_fit='stretch'))
    result = {}
    for key in ('image', 'text'):
        picture = parts[key].convert('RGBA')
        result[key] = extract_alpha(picture.tobytes(), 100, 100, 400, 4)
    assert result['image'][5 * 100 + 5] == 255
    assert result['image'][6 * 100 + 6] == 0
    px, py = point(5, 5)
    assert mask_candidates(result, px, py, 240, 240, 1) == ('image',)


def test_gtk_source_never_calls_ipc_or_yaml_from_pixel_hit_testing():
    for fn in ('_composition_v8_set_components', '_composition_v8_candidates',
               '_composition_pick_target', '_composition_capture_overlap'):
        code = source_of(fn)
        assert '_quick_save(' not in code and 'ipc_request(' not in code
        assert 'vision02.service' not in code and 'usb' not in code.lower()
    assert 'response.get(\'components\', {})' in source_of('_quick_received')
    assert 'self._composition_v8_masks = {}' in source_of('_quick_changed')
    assert 'self._composition_v8_masks = {}' in source_of('_quick_load')


def test_v8_picker_rejects_blank_pixel_and_selects_opaque():
    class Select:
        def __init__(self):self.value=0
        def set_selected(self,x):self.value=x
        def get_selected(self):return self.value
    obj = SimpleNamespace(_quick_loaded={'key':1}, _busy=set(),
        _composition_v8_masks=masks(),
        _composition_v7_visible={'image':True,'text':True},
        composition_canvas=SimpleNamespace(get_width=lambda:240,get_height=lambda:240),
        _composition_zoom=1.0,
        composition_prefer_image=SimpleNamespace(get_active=lambda:False),
        composition_target=Select())
    obj._composition_v8_candidates=callback('_composition_v8_candidates',
                                           {'mask_candidates':mask_candidates}).__get__(obj)
    pick=callback('_composition_pick_target', {'choose_mask_layer':choose_mask_layer})
    wx,wy=point(20,20)
    assert pick(obj,wx,wy)=='image'
    assert obj.composition_target.value==0
    wx,wy=point(50,50)
    assert pick(obj,wx,wy)=='text'
    assert obj.composition_target.value==1
    wx,wy=point(30,30)
    assert pick(obj,wx,wy) is None
    assert obj.composition_target.value==1
    obj._busy.add('quick_save')
    assert pick(obj,*point(40,40)) is None


def test_gui_protects_stale_mask_when_form_changes():
    src=source_of('_quick_changed')
    assert src.index('self._composition_v8_masks = {}') < src.index('self._quick_dirty = True')
    assert '_composition_v8_set_components' in source_of('_quick_received')
    assert 'request_matches and response_matches' in source_of('_quick_received')


def test_backend_already_emits_components_without_changes():
    backend = (APP_PATH.parent/'vision02_studio_backend.py').read_text()
    editor = (APP_PATH.parent/'vision02_editor_backend.py').read_text()
    assert "'components': result.get('components', {})" in backend
    assert 'render_rgba_components(' in editor
