"""Testes offline de edição embutida, sem gi, OBS, HID ou systemd."""
import importlib.util
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest
import yaml

from vision02.studio_inline_edit import KINDS, HINTS, form_to_key, key_to_form

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('studio_inline_backend', ROOT/'apps/vision02_studio_backend.py')
assert SPEC and SPEC.loader
BACKEND = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACKEND)


def form(kind, *fields, label='Painel', image='', appearance=None):
    return {'kind':kind,'fields': list(fields)+['']*(4-len(fields)),
            'label':label,'image':image,'appearance':appearance}


@pytest.mark.parametrize('action', [
    {'type':'none'},
    {'type':'command','argv':['gnome-terminal','--wait']},
    {'type':'url','url':'https://example.org/a'},
    {'type':'profile','target':'OBS — Controle'},
    {'type':'hotkey','keys':['Ctrl','Shift','T']},
    {'type':'script','path':'/tmp/test.sh','interpreter':'bash','args':['one','two words']},
    {'type':'obs','operation':'scene_name','scene':'Teste'},
    {'type':'obs','operation':'scene_slot','slot':2},
    {'type':'obs','operation':'toggle_mic','input':'Mic/Aux'},
])
def test_action_roundtrip(action):
    loaded = {'label':'ABC','image':'','action':action,'appearance':None}
    assert form_to_key(key_to_form(loaded))['action'] == action


def test_appearance_preserved_on_edit():
    style = {'background':'#aabbcc','show_text': True}
    output=form_to_key(form('url','https://example.org', appearance=style))
    assert output['appearance'] is style


@pytest.mark.parametrize('invalid', [
    {'kind':'invalid','fields':['','','',''],'label':'a','image':''},
    {'kind':'url','fields':['a'], 'label':'a', 'image':''},
    form('obs','scene_slot','','','abc'),
    form('script','/tmp/a.sh','bash','"broken quote'),
    form('command','"unterminated'),
])
def test_reject_malformed_form(invalid):
    with pytest.raises(ValueError):
        form_to_key(invalid)


def test_fields_ignore_extra_when_unselected():
    output=form_to_key(form('url','https://example.org','ignore','ignore','ignore'))
    assert output['action']=={'type':'url','url':'https://example.org'}


def test_all_action_kinds_have_help():
    assert set(KINDS)==set(HINTS)


@pytest.fixture
def sample_profile(tmp_path,monkeypatch):
    user_dir = tmp_path/'usercfg'/'vision02'/'profiles'
    user_dir.mkdir(parents=True)
    path=user_dir/'test.yaml'
    path.write_text('''version: 1
name: Teste
keys:
  1:
    label: Original
    action:
      type: url
      url: https://example.org/one
  15:
    label: Voltar
    action:
      type: profile
      target: Teste
''',encoding='utf8')
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'usercfg'))
    monkeypatch.setenv('XDG_STATE_HOME',str(tmp_path/'state'))
    return path


def test_backend_inspect_and_save_and_backup(sample_profile,tmp_path):
    original=sample_profile.read_bytes()
    original_mode = sample_profile.stat().st_mode & 0o777
    inspected=BACKEND.run('quick_inspect',{'profile':'Teste','key_id':1},project=tmp_path)
    assert inspected['edited']['label']=='Original'
    change=form('url','https://example.org/two',label='Atualizado')
    saved=BACKEND.run('quick_save',{'profile':'Teste','key_id':1,'sha256':inspected['sha256'],
                                   'form':change},project=tmp_path)
    assert saved['ok'] and Path(saved['backup']).read_bytes()==original
    assert yaml.safe_load(sample_profile.read_text())['keys'][1]['label']=='Atualizado'
    assert yaml.safe_load(sample_profile.read_text())['keys'][15]['label']=='Voltar'
    assert sample_profile.stat().st_mode & 0o777 == original_mode  # preserva o umask do usuário


def test_stale_sha_does_not_override_yaml(sample_profile,tmp_path):
    inspected=BACKEND.run('quick_inspect',{'profile':'Teste','key_id':1},project=tmp_path)
    sample_profile.write_text(sample_profile.read_text()+'\n# edicao concorrente\n')
    content=sample_profile.read_bytes()
    with pytest.raises(RuntimeError,match='mudou'):
        BACKEND.run('quick_save',{'profile':'Teste','key_id':1,'sha256':inspected['sha256'],
                                  'form':form('url','https://example.org/2')},project=tmp_path)
    assert sample_profile.read_bytes()==content


def test_invalid_url_rejected_without_backup(sample_profile,tmp_path):
    inspected=BACKEND.run('quick_inspect',{'profile':'Teste','key_id':1},project=tmp_path)
    content=sample_profile.read_bytes()
    with pytest.raises(ValueError):
        BACKEND.run('quick_save',{'profile':'Teste','key_id':1,'sha256':inspected['sha256'],
                                  'form':form('url','file:///etc/passwd')},project=tmp_path)
    assert sample_profile.read_bytes()==content
    assert not (tmp_path/'state'/'vision02'/'editor-backups').exists()


def test_preview_does_not_change_profile(sample_profile,tmp_path):
    inspected=BACKEND.run('quick_inspect',{'profile':'Teste','key_id':1},project=tmp_path)
    original=sample_profile.read_bytes()
    response=BACKEND.run('quick_preview', {'profile':'Teste','key_id':1,'sha256':inspected['sha256'],
                                            'form':form('url','https://example.org/other')}, project=tmp_path)
    assert Path(response['image']).is_file()
    assert sample_profile.read_bytes()==original


@pytest.mark.parametrize('payload', [
    {'profile':'Teste','key_id':0},
    {'profile':'Teste','key_id':True},
    {'profile':'Teste','key_id':'5'},
    {'profile':'Teste','key_id':16},
    {'profile':'Teste','key_id':5,'bad':True},
    {'profile':4,'key_id':5},
])
def test_inspect_rejects_bad_payload(payload,tmp_path):
    with pytest.raises(ValueError):
        BACKEND.run('quick_inspect',payload,project=tmp_path)


def test_write_requires_revision_and_explicit_form(sample_profile,tmp_path):
    with pytest.raises(ValueError):
        BACKEND.run('quick_save',{'profile':'Teste','key_id':1},project=tmp_path)
    with pytest.raises(ValueError):
        BACKEND.run('quick_save', {'profile':'Teste','key_id':1,'sha256':'0'*64,'form':{}},project=tmp_path)


def test_no_hid_or_action_execution_by_quick_panel():
    gtk=(ROOT/'apps/vision02_studio.py').read_text(encoding='utf-8')
    backend=(ROOT/'apps/vision02_studio_backend.py').read_text(encoding='utf-8')
    assert 'Vision02(' not in gtk
    assert "if command in ('quick_inspect', 'quick_preview', 'quick_save')" in backend
    assert 'save_key(' in backend
    assert 'preview_key(' in backend
    assert 'execute_action(' not in backend
    assert "self._call('reload')" in gtk


def test_studio_backend_rejects_unknown_form_keys(sample_profile,tmp_path):
    inspected=BACKEND.run('quick_inspect',{'profile':'Teste','key_id':1},project=tmp_path)
    with pytest.raises(ValueError):
        BACKEND.run('quick_save',{'profile':'Teste','key_id':1,
                                 'sha256':inspected['sha256'],'form':form('url','https://example.org'),
                                 'danger':'true'},project=tmp_path)


def test_visual_text_can_be_set_without_discarding_other_style():
    style = {'background': '#001122', 'font_size': 23, 'text': 'Antigo', 'show_text': True}
    edited = form_to_key({**form('url', 'https://example.org', appearance=style),
                          'visual_text': 'Novo título'})
    assert edited['appearance']['text'] == 'Novo título'
    assert edited['appearance']['background'] == '#001122'
    assert edited['appearance']['font_size'] == 23
    assert style['text'] == 'Antigo'


def test_custom_visual_text_creates_style_but_empty_does_not():
    assert form_to_key(form('url','https://example.org'))['appearance'] is None
    changed=form_to_key({**form('url','https://example.org'), 'visual_text':'Novo'})
    assert changed['appearance']['text']=='Novo'
    assert changed['appearance']['show_text'] is True
    cleared=form_to_key({**form('url','https://example.org',appearance=changed['appearance']),
                         'visual_text':''})
    assert cleared['appearance']['text'] is None


def test_visual_text_limit():
    with pytest.raises(ValueError,match='até 120'):
        form_to_key({**form('url','https://example.org'), 'visual_text':'x'*121})
