"""Regression and functional tests for freely positioned LCD compositions.

No GUI, USB or systemd access is required; the same renderer is used by the
controller and the editor backend.
"""
from __future__ import annotations

from dataclasses import asdict
import importlib.util
from pathlib import Path

import pytest
import yaml
from PIL import Image, ImageChops

from vision02.profiles.loader import load_profile, parse_appearance, ProfileValidationError
from vision02.profiles.models import KeyAppearance
from vision02.rendering import render_appearance
from vision02.studio_composition import clamp_drag, grid_coordinate
from vision02.studio_visual_style import IMAGE_RANGES, ui_appearance, validated_appearance

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('studio_composition_backend', ROOT/'apps/vision02_studio_backend.py')
BACKEND = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACKEND)


def image(tmp_path, color='#E12748', size=(100,100)):
    path = tmp_path/'icon.png'
    Image.new('RGB', size, color).save(path)
    return path


def visual_form(*, image_path='', style=None):
    return {'label':'Tela de Teste', 'image':str(image_path), 'kind':'url',
            'fields':['https://example.org','','',''], 'visual_text':'',
            'appearance': asdict(style or KeyAppearance(show_text=False))}


def provision_profile(tmp_path, monkeypatch):
    config = tmp_path/'config'
    dest = config/'vision02'/'profiles'
    dest.mkdir(parents=True)
    path = dest/'demo.yaml'
    path.write_text('''version: 1
name: Composição
keys:
  1:
    label: Original
    action:
      type: url
      url: https://example.org
''', encoding='utf-8')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(config))
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path/'cache'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path/'state'))
    return path


def test_defaults_zero_and_full_size():
    style = KeyAppearance()
    assert (style.image_x, style.image_y, style.image_scale) == (0, 0, 100)
    assert IMAGE_RANGES == {'image_x':(-100,100), 'image_y':(-100,100), 'image_scale':(25,200)}


def test_absent_appearance_remains_legacy(tmp_path):
    pic = image(tmp_path)
    style = parse_appearance({})
    expected = Image.open(pic).convert('RGB')
    output = render_appearance('',pic,KeyAppearance(show_text=False))
    assert ImageChops.difference(expected,output).getbbox() is None
    assert style.image_scale == 100


@pytest.mark.parametrize('field,value', [
    ('image_x',-100),('image_x',100),('image_y',-100),('image_y',100),
    ('image_scale',25),('image_scale',200),('image_scale',100),
])
def test_extreme_values_are_allowed(field,value):
    style=parse_appearance({field:value})
    assert getattr(style,field)==value
    ui=asdict(style)
    ui.pop('text')
    assert validated_appearance(True,ui)[field]==value


@pytest.mark.parametrize('field,value', [
    ('image_x',-101),('image_x',101),('image_y',-101),('image_y',101),
    ('image_scale',24),('image_scale',201),('image_scale',0),('image_scale',-1),
    ('image_x',True),('image_y',False),('image_scale',True),
    ('image_x',2.5),('image_y','10'),('image_scale','100'),
])
def test_bad_values_are_rejected(field,value):
    with pytest.raises(ProfileValidationError,match=field):
        parse_appearance({field:value})


@pytest.mark.parametrize('scale', [25,50,75,100,125,150,200])
def test_scale_keeps_original_center_and_size(tmp_path,scale):
    pic=image(tmp_path)
    original=render_appearance('',pic,KeyAppearance(show_text=False))
    result=render_appearance('',pic,KeyAppearance(show_text=False,image_scale=scale))
    assert result.mode=='RGB' and result.size==(100,100)
    assert result.getpixel((50,50))==original.getpixel((50,50))
    if scale < 100:
        assert result.getpixel((0,0)) == (8,12,22)
    else:
        assert result.getpixel((0,0)) == (225,39,72)


@pytest.mark.parametrize('x,y', [(-30,0),(30,0),(0,-30),(0,30),(-100,0),(100,0),(0,-100),(0,100)])
def test_shifted_icon_is_cropped_safely(tmp_path,x,y):
    pic=image(tmp_path)
    result=render_appearance('',pic,KeyAppearance(show_text=False,image_x=x,image_y=y))
    assert result.size == (100,100)
    assert result.getpixel((50,50)) != (8,12,22) if abs(x)+abs(y)<50 else True
    if x>0:assert result.getpixel((0,50)) == (8,12,22)
    if x<0:assert result.getpixel((99,50)) == (8,12,22)
    if y>0:assert result.getpixel((50,0)) == (8,12,22)
    if y<0:assert result.getpixel((50,99)) == (8,12,22)


@pytest.mark.parametrize('fit',["cover","contain","stretch"])
def test_fit_mode_is_preserved_with_image_layout(tmp_path,fit):
    pic=image(tmp_path,size=(200,60))
    result=render_appearance('',pic,KeyAppearance(show_text=False,image_fit=fit,
                                                   image_scale=50,image_x=20,image_y=-15))
    assert result.size==(100,100)
    assert result.getpixel((0,0))==(8,12,22)


def test_overlay_has_transparency_around_shrunk_icon(tmp_path):
    path=tmp_path/'alpha.png'
    src=Image.new('RGBA',(100,100),(255,0,0,0))
    for x in range(20,80):
        for y in range(20,80):src.putpixel((x,y),(255,0,0,255))
    src.save(path)
    result=render_appearance('',path,KeyAppearance(show_text=False,
                             background='#132435',image_scale=50))
    assert result.getpixel((0,0))==(19,36,53)
    assert result.getpixel((50,50))==(255,0,0)


def test_text_offset_and_icon_offset_are_independent(tmp_path):
    pic=image(tmp_path)
    baseline=render_appearance('Oi',pic,KeyAppearance())
    image_shift=render_appearance('Oi',pic,KeyAppearance(image_x=20))
    text_shift=render_appearance('Oi',pic,KeyAppearance(offset_y=20))
    assert ImageChops.difference(baseline,image_shift).getbbox()
    assert ImageChops.difference(baseline,text_shift).getbbox()


def test_round_trip_yaml_and_preview_and_save(tmp_path,monkeypatch):
    path=provision_profile(tmp_path,monkeypatch)
    pic=image(tmp_path)
    before=path.read_bytes()
    initial=BACKEND.run('quick_inspect',{'profile':'Composição','key_id':1},project=tmp_path)
    style=KeyAppearance(show_text=False,image_x=-17,image_y=12,image_scale=62,
                        image_fit='contain',background='#294056')
    request={'profile':'Composição','key_id':1,'sha256':initial['sha256'],
             'form':visual_form(image_path=pic,style=style)}
    preview=BACKEND.run('quick_preview',request,project=tmp_path)
    with Image.open(preview['image']) as fp:
        original_preview=fp.copy()
    assert path.read_bytes()==before
    saved=BACKEND.run('quick_save',request,project=tmp_path)
    assert Path(saved['backup']).read_bytes()==before
    loaded=load_profile(path)
    actual=loaded.keys[1]
    assert actual.action.type=='url' and actual.action.url=='https://example.org'
    assert actual.appearance.image_scale==62 and actual.appearance.image_x==-17
    live=render_appearance(actual.label, actual.image, actual.appearance)
    assert ImageChops.difference(live,original_preview.convert('RGB')).getbbox() is None
    again=BACKEND.run('quick_inspect',{'profile':'Composição','key_id':1},project=tmp_path)
    assert again['edited']['appearance']['image_scale']==62


def test_concurrent_changes_prevent_save(tmp_path,monkeypatch):
    path=provision_profile(tmp_path,monkeypatch)
    initial=BACKEND.run('quick_inspect',{'profile':'Composição','key_id':1},project=tmp_path)
    path.write_text(path.read_text().replace('Original','Modificado'))
    before=path.read_bytes()
    with pytest.raises(RuntimeError,match='mudou'):
        BACKEND.run('quick_save',{'profile':'Composição','key_id':1,
           'sha256':initial['sha256'],'form':visual_form()},project=tmp_path)
    assert path.read_bytes()==before


@pytest.mark.parametrize('start,distance,zoom,low,high,expected', [
    (0,25,2.5,-100,100,10),
    (0,-25,2.5,-100,100,-10),
    (3,5,2.5,-40,40,5),
    (-39,-25,2.5,-40,40,-40),
    (100,15,2.5,-100,100,100),
    (0,0,1,-100,100,0),
    (0,100,5,-100,100,20),
])
def test_drag_coordinates(start,distance,zoom,low,high,expected):
    assert clamp_drag(start,distance,zoom,low,high)==expected


@pytest.mark.parametrize('input_,expected',[(-42,-40),(-38,-40),(-26,-25),
     (-7,-5),(-2,0),(1,0),(3,5),(7,5),(9,10),(39,40),(41,40)])
def test_grid_snaps_clamps(input_,expected):
    assert grid_coordinate(input_,-40,40)==expected


def test_bad_drag_input_rejected():
    for args in ((0,2,0,-40,40),(True,1,2,-40,40),(0,2,2,40,-40)):
        with pytest.raises(ValueError): clamp_drag(*args)
    with pytest.raises(ValueError):grid_coordinate(0,-40,40,0)


def test_editor_contains_drag_interface_but_does_not_write_directly():
    source=(ROOT/'apps/vision02_studio.py').read_text()
    assert '_composition_drag_update' in source
    assert "Gtk.GestureDrag.new()" in source
    assert "self.composition_picture = Gtk.Picture()" in source
    assert "self.composition_surface = Gtk.Overlay()" in source
    assert "quick_save" in source and "quick_preview" in source
    assert "set_draw_func(self._composition_draw)" in source
