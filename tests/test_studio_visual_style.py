"""Aparência embutida sem GTK, HID, OBS ou alteração de perfis pessoais."""
from __future__ import annotations

from dataclasses import asdict
import importlib.util
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import pytest
import yaml

from vision02.profiles.loader import parse_appearance
from vision02.profiles.models import KeyAppearance
from vision02.studio_inline_edit import form_to_key
from vision02.studio_visual_style import CHOICES, INT_RANGES, COLORS, ui_appearance, validated_appearance, hex_from_rgb

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('style_studio_backend', ROOT / 'apps/vision02_studio_backend.py')
assert spec and spec.loader
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


def controls(**changed):
    style = asdict(KeyAppearance())
    style.pop('text')
    style.update(changed)
    return style


def form(style, *, text='', image='', label='Teste LCD'):
    return dict(label=label, image=image, kind='url', fields=['https://example.com', '', '', ''],
                visual_text=text, appearance=style)


def profile(tmp_path, monkeypatch):
    directory = tmp_path / 'xdg' / 'vision02' / 'profiles'
    directory.mkdir(parents=True)
    p = directory / 'local.yaml'
    p.write_text('''version: 1
name: Teste Visual
keys:
  1:
    label: Original
    action:
      type: url
      url: https://example.com
''', encoding='utf-8')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    return p


def test_defaults_remain_legacy_when_disabled():
    assert ui_appearance(None) == asdict(KeyAppearance())
    assert validated_appearance(False, controls()) is None


def test_enable_creates_complete_style():
    appearance = validated_appearance(True, controls())
    assert appearance == asdict(KeyAppearance())
    assert parse_appearance(appearance)


@pytest.mark.parametrize('changed', [
    {'font_family':'serif'}, {'font_family':'mono'}, {'font_weight':'regular'},
    {'horizontal':'left'}, {'horizontal':'right'}, {'vertical':'top'},
    {'vertical':'bottom'}, {'image_fit':'contain'}, {'image_fit':'stretch'},
    {'show_text':False}, {'offset_x':-40}, {'offset_y':40},
    {'font_size':8}, {'font_size':36}, {'background':'#AABBCC'},
    {'text_color':'#112233'},
])
def test_all_supported_controls_roundtrip(changed):
    expected = controls(**changed)
    assert {k: v for k, v in validated_appearance(True, expected).items() if k != 'text'} == expected
    assert {k: v for k, v in ui_appearance(validated_appearance(True, expected)).items() if k != 'text'} == expected


@pytest.mark.parametrize('change', [
    {'font_family':'comic'}, {'font_size':37}, {'font_size':True},
    {'offset_x':41}, {'offset_y':-41}, {'background':'#000'},
    {'text_color':'bad'}, {'horizontal':'middle'}, {'image_fit':'invalid'},
    {'show_text':1},
])
def test_reject_invalid_style(change):
    with pytest.raises((ValueError, TypeError)):
        validated_appearance(True, controls(**change))


def test_reject_unknown_or_missing_fields():
    for fields in ({**controls(), 'command':'rm -rf /'}, {k:v for k,v in controls().items() if k != 'font_size'}):
        with pytest.raises(ValueError):
            validated_appearance(True, fields)


def test_invalid_enabled_and_raw():
    with pytest.raises(ValueError): validated_appearance(1, controls())
    with pytest.raises(ValueError): ui_appearance('bad')


def test_custom_text_keeps_show_text_false():
    result = form_to_key(form(validated_appearance(True, controls(show_text=False)), text='Oculto'))
    assert result['appearance']['text'] == 'Oculto'
    assert result['appearance']['show_text'] is False


def test_legacy_visual_text_preserved():
    result = form_to_key(form(None, text='Mostrado'))
    assert result['appearance']['show_text'] is True
    assert result['appearance']['text'] == 'Mostrado'


def test_disable_custom_style_preserves_legacy():
    result = form_to_key(form(validated_appearance(False, controls()), text=''))
    assert result['appearance'] is None


@pytest.mark.parametrize('red,green,blue,value', [
    (0,0,0,'#000000'), (1,1,1,'#FFFFFF'), (1,0,0,'#FF0000'), (0,0.5,1,'#0080FF'),
])
def test_hex_from_rgb(red,green,blue,value):
    assert hex_from_rgb(red,green,blue)==value


def test_hex_reject_out_of_range():
    with pytest.raises(ValueError): hex_from_rgb(2,0,0)


def test_choices_match_loader_and_known_controls():
    assert set(CHOICES) == {'font_family','font_weight','horizontal','vertical','image_fit'}
    assert set(INT_RANGES) == {'font_size','offset_x','offset_y'}
    assert set(COLORS) == {'background','text_color'}
    assert {k for k in controls()} == set(CHOICES) | set(INT_RANGES) | set(COLORS) | {'show_text'}


def test_backend_preview_reflects_custom_background(tmp_path, monkeypatch):
    p = profile(tmp_path,monkeypatch)
    inspected=backend.run('quick_inspect',{'profile':'Teste Visual','key_id':1},project=tmp_path)
    style=validated_appearance(True, controls(background='#13579B',show_text=False))
    original=p.read_bytes()
    preview=backend.run('quick_preview',{
        'profile':'Teste Visual','key_id':1,'sha256':inspected['sha256'],
        'form':form(style)},project=tmp_path)
    with Image.open(preview['image']) as image:
        assert image.getpixel((50,50)) == (0x13,0x57,0x9b)
    assert p.read_bytes()==original


def test_backend_saves_valid_yaml_with_backup(tmp_path, monkeypatch):
    p=profile(tmp_path,monkeypatch)
    original=p.read_bytes()
    inspected=backend.run('quick_inspect',{'profile':'Teste Visual','key_id':1},project=tmp_path)
    style=validated_appearance(True,controls(background='#123456',font_family='mono',
                                             image_fit='contain',offset_y=-9))
    saved=backend.run('quick_save',{'profile':'Teste Visual','key_id':1,'sha256':inspected['sha256'],
                                    'form':form(style,text='LCD atual')},project=tmp_path)
    assert saved['ok']
    assert Path(saved['backup']).read_bytes()==original
    cfg=yaml.safe_load(p.read_text())['keys'][1]['appearance']
    assert cfg['font_family']=='mono' and cfg['offset_y']==-9
    assert cfg['background']=='#123456' and cfg['text']=='LCD atual'
    assert cfg['image_fit']=='contain'


def test_backend_invalid_color_preserves_file(tmp_path,monkeypatch):
    p=profile(tmp_path,monkeypatch)
    original=p.read_bytes()
    inspected=backend.run('quick_inspect',{'profile':'Teste Visual','key_id':1},project=tmp_path)
    edited=form({**controls(),'background':'wrong'})
    with pytest.raises(ValueError):
        backend.run('quick_save',{'profile':'Teste Visual','key_id':1,'sha256':inspected['sha256'],
                                  'form':edited},project=tmp_path)
    assert p.read_bytes()==original


def test_stale_revision_rejected(tmp_path,monkeypatch):
    p=profile(tmp_path,monkeypatch)
    inspected=backend.run('quick_inspect',{'profile':'Teste Visual','key_id':1},project=tmp_path)
    p.write_text(p.read_text()+'\n# modificado fora do Studio\n')
    changed=p.read_bytes()
    with pytest.raises(RuntimeError,match='mudou'):
        backend.run('quick_save',{'profile':'Teste Visual','key_id':1,'sha256':inspected['sha256'],
                                  'form':form(validated_appearance(True,controls()))},project=tmp_path)
    assert p.read_bytes()==changed


def test_gui_wiring_never_executes_hid():
    source=(ROOT/'apps/vision02_studio.py').read_text()
    for anchor in ('_build_visual_style', '_read_visual_style', '_set_visual_style',
                   'Gtk.ColorDialogButton', '_style_preview_delayed',
                   'validated_appearance', 'self._quick_changed()'):
        assert anchor in source
    assert 'Vision02(' not in source
    assert 'execute_action(' not in source
