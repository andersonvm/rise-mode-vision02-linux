"""v7 previews: channel visibility is local; LCD renderer remains unchanged."""
from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from vision02.profiles.models import KeyAppearance
from vision02.rendering import render_appearance
from vision02.studio_preview_layers_v7 import (
    visibility_mode, render_preview_views, render_rgba_components,
)


@pytest.fixture
def icon(tmp_path):
    path = tmp_path / 'semi-alpha.png'
    bitmap = Image.new('RGBA', (37, 59), (100, 180, 35, 160))
    bitmap.putpixel((0, 0), (0, 0, 0, 0))
    bitmap.save(path)
    return path


@pytest.mark.parametrize('image_on,text_on,result', [
    (True, True, 'both'), (True, False, 'image'),
    (False, True, 'text'), (False, False, 'none'),
])
def test_visibility_combinations(image_on, text_on, result):
    assert visibility_mode(image_on, text_on) == result


@pytest.mark.parametrize('bad', [(1, True), (None, False), (True, 'yes')])
def test_visibility_rejects_non_boolean(bad):
    with pytest.raises(ValueError):
        visibility_mode(*bad)


@pytest.mark.parametrize('fit', ['contain', 'cover', 'stretch'])
@pytest.mark.parametrize('scale,offset', [(100, (0, 0)), (90, (-15, 11)), (150, (30, -25))])
def test_all_four_modes_match_existing_lcd_renderer(icon, fit, scale, offset):
    style = KeyAppearance(image_fit=fit, image_scale=scale,
                          image_x=offset[0], image_y=offset[1],
                          offset_x=7, offset_y=-11, text='Camadas',
                          background='#112233', text_color='#DDEEFF')
    before = style
    variants = render_preview_views('original', icon, style)
    assert list(variants) == ['both', 'image', 'text', 'none']
    assert style == before  # dataclass imutável, sem estado modificado
    expected = {
        'both': render_appearance('original', icon, style),
        'image': render_appearance('original', icon, replace(style, show_text=False)),
        'text': render_appearance('original', None, style),
        'none': render_appearance('original', None, replace(style, show_text=False)),
    }
    for mode, picture in variants.items():
        assert picture.mode == 'RGB' and picture.size == (100, 100)
        assert ImageChops.difference(picture, expected[mode]).getbbox() is None


@pytest.mark.parametrize('fit', ['contain', 'cover', 'stretch'])
@pytest.mark.parametrize('scale', [100, 135])
def test_rgba_channels_reproduce_complete_render(icon, fit, scale):
    style = KeyAppearance(image_fit=fit, image_scale=scale,
                          image_x=10, image_y=-13, offset_x=6, offset_y=-4,
                          text='Camadas', background='#132A41')
    parts = render_rgba_components('ignored', icon, style)
    assert set(parts) == {'background', 'image', 'text'}
    assert all(v.mode == 'RGBA' and v.size == (100, 100) for v in parts.values())
    assert parts['background'].getpixel((0, 0))[3] == 255
    assert parts['image'].getbbox() is not None
    assert parts['text'].getbbox() is not None
    composed = parts['background'].copy()
    composed.alpha_composite(parts['image'])
    composed.alpha_composite(parts['text'])
    assert ImageChops.difference(composed.convert('RGB'),
                                 render_appearance('ignored', icon, style)).getbbox() is None


def test_transparent_channels_when_no_content():
    parts = render_rgba_components('', None, KeyAppearance(show_text=False))
    assert parts['image'].getbbox() is None
    assert parts['text'].getbbox() is None


def test_hidden_text_keeps_image(icon):
    style = KeyAppearance(show_text=False, image_fit='contain')
    variants = render_preview_views('Never shown', icon, style)
    assert ImageChops.difference(variants['both'], variants['image']).getbbox() is None


def test_rgba_and_render_reject_invalid_arguments(icon):
    for fn in (render_preview_views, render_rgba_components):
        with pytest.raises(ValueError):
            fn(None, icon, KeyAppearance())
        with pytest.raises(ValueError):
            fn('X', icon, None)
        with pytest.raises(ValueError):
            fn('X', 'not-a-path', KeyAppearance())


def test_preview_files_do_not_change_profile(tmp_path, monkeypatch, icon):
    from apps import vision02_editor_backend as editor

    path = tmp_path / 'test.yaml'
    path.write_text('''version: 1
name: Camadas
keys:
  1:
    label: Original
    image: semi-alpha.png
    action:
      type: url
      url: https://example.org
    appearance:
      background: '#112233'
      text: 'Camadas'
      image_fit: contain
''', encoding='utf8')
    assert icon.parent == tmp_path
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    paths = [Path('test.yaml')]
    before = path.read_bytes()
    info = editor.inspect_profile(tmp_path, 'Camadas', paths)
    result = editor.preview_key(tmp_path, 'Camadas', 1, info['keys']['1'],
                                info['sha256'], paths)
    assert path.read_bytes() == before
    assert set(result['layers']) == {'both', 'image', 'text', 'none'}
    assert set(result['components']) == {'background', 'image', 'text'}
    for filename in [*result['layers'].values(), *result['components'].values()]:
        with Image.open(filename) as picture:
            picture.verify()
    with Image.open(result['previews']['1']['image']) as device_preview:
        with Image.open(result['layers']['both']) as layered_preview:
            assert ImageChops.difference(device_preview.convert('RGB'),
                                         layered_preview.convert('RGB')).getbbox() is None


def test_gtk_and_backend_hooks_have_no_save_or_ipc_side_effects():
    root = Path(__file__).resolve().parents[1]
    gtk = (root / 'apps/vision02_studio.py').read_text()
    backend = (root / 'apps/vision02_studio_backend.py').read_text()
    editor = (root / 'apps/vision02_editor_backend.py').read_text()
    tree = ast.parse(gtk)
    window = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'StudioWindow')
    update = next(n for n in window.body if isinstance(n, ast.FunctionDef)
                  and n.name == '_composition_v7_visibility_changed')
    hook = ast.get_source_segment(gtk, update)
    assert '_composition_v7_update_picture()' in hook
    assert '_quick_save' not in hook and '_quick_apply' not in hook and '_call(' not in hook
    assert "response.get('layers', {})" in gtk
    assert "result.get('layers', {})" in backend
    assert 'render_preview_views(' in editor
    assert 'render_rgba_components(' in editor
