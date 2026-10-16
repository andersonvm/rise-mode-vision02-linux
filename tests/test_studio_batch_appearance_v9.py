"""Cópia de aparência v9: testes offline, sem GTK, IPC ou HID."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
import pytest
import yaml

from vision02.studio_batch_appearance_v9 import batch_targets, copy_saved_appearance

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('vision02_batch_backend', ROOT/'apps/vision02_studio_backend.py')
assert spec and spec.loader
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


def test_normalize_destinations():
    assert batch_targets(1, [15, 2, 4]) == (2, 4, 15)


@pytest.mark.parametrize('source', [None, 0, -1, 16, True, 1.5, '1', {}, []])
def test_invalid_source(source):
    with pytest.raises(ValueError):
        batch_targets(source, [2])


@pytest.mark.parametrize('targets', [None, (), {}, '2', [], [1], [2, 2], [0], [16],
                                     [False], ['2'], [2.0], [2, True], [2]*15,
                                     list(range(1,16)), [2, '3']])
def test_invalid_targets(targets):
    with pytest.raises(ValueError):
        batch_targets(1, targets)


@pytest.fixture
def profile(tmp_path, monkeypatch):
    folder = tmp_path/'config'/'vision02'/'profiles'
    folder.mkdir(parents=True)
    picture=folder/'foto.png'
    Image.new('RGB', (32, 32), '#336699').save(picture)
    raw = {
        'version': 1, 'name': 'Em Lote', 'keys': {
            1: {'label': 'Origem', 'action': {'type':'url', 'url':'https://example.org/one'},
                'image':'foto.png', 'appearance': {'text': 'Visível', 'background': '#123456',
                                                  'show_text': True, 'font_size': 25}},
            2: {'label': 'Destino OBS', 'action': {'type':'obs','operation':'scene_name','scene':'Ao Vivo'},
                'appearance': {'text':'Antigo', 'background':'#000000'}},
            3: {'label': 'Destino URL', 'action': {'type':'url','url':'https://example.org/three'},
                'image':'foto.png'},
            15: {'label': 'Retorno', 'action': {'type':'profile','target':'Em Lote'}}
        }}
    p=folder/'lote.yaml'
    p.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),encoding='utf-8')
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'config'))
    monkeypatch.setenv('XDG_STATE_HOME',str(tmp_path/'state'))
    monkeypatch.setenv('XDG_CACHE_HOME',str(tmp_path/'cache'))
    return p


def request(profile, source=1, targets=(2, 3, 15), sha=None):
    inspected=backend.run('quick_inspect',{'profile':'Em Lote','key_id':source},project=profile)
    return {'profile':'Em Lote','source_key':source,'targets':list(targets),
            'sha256':sha or inspected['sha256']}


def test_batch_pure_copies_only_image_and_style(profile):
    original=profile.read_bytes()
    data_before=yaml.safe_load(original)
    result=yaml.safe_load(copy_saved_appearance(original,1,[2,3,15]))
    for dest in (2,3,15):
        old=data_before['keys'][dest]
        new=result['keys'][dest]
        assert new['action']==old['action']
        assert new['label']==old['label']
        assert new['image']==data_before['keys'][1]['image']
        assert new['appearance']==data_before['keys'][1]['appearance']
    assert result['keys'][1]==data_before['keys'][1]
    assert profile.read_bytes()==original


def test_batch_clears_absent_appearance_and_image(profile):
    original=profile.read_bytes()
    result=yaml.safe_load(copy_saved_appearance(original,15,[2,3]))
    for dest in (2,3):
        assert 'image' not in result['keys'][dest]
        assert 'appearance' not in result['keys'][dest]
        assert 'action' in result['keys'][dest]


def test_cannot_populate_missing_key(profile):
    with pytest.raises(ValueError,match='04'):
        copy_saved_appearance(profile.read_bytes(),1,[4])


def test_no_partial_write_when_one_invalid_destination(profile):
    original=profile.read_bytes()
    with pytest.raises(ValueError):
        copy_saved_appearance(original,1,[2,4])
    assert profile.read_bytes()==original


def test_cannot_copy_from_missing_source(profile):
    with pytest.raises(ValueError,match='origem'):
        copy_saved_appearance(profile.read_bytes(),8,[2])


@pytest.mark.parametrize('invalid', [b'', b'null', b'[]', b'keys: 1', b'[]\nkeys: {}'])
def test_reject_invalid_yaml(invalid):
    with pytest.raises(ValueError):
        copy_saved_appearance(invalid,1,[2])


def test_inspect_lists_configured_destinations(profile):
    result=backend.run('quick_inspect',{'profile':'Em Lote','key_id':1},project=profile.parent.parent.parent.parent)
    assert result['configured_keys']==[1,2,3,15]


def test_batch_backend_atomic_save_and_one_backup(profile):
    root=profile.parent.parent.parent.parent
    before=profile.read_bytes()
    mode=profile.stat().st_mode & 0o777
    result=backend.run('quick_batch_appearance',request(root,targets=(2,3,15)),project=root)
    assert result['ok']
    assert result['source_key']==1 and result['targets']==[2,3,15]
    assert Path(result['backup']).read_bytes()==before
    assert profile.stat().st_mode & 0o777 == mode
    assert result['sha256']!=request(root, sha='0'*64)['sha256']
    assert list(Path(result['backup']).parent.glob('*batch-v9*')) == [Path(result['backup'])]
    result_data=yaml.safe_load(profile.read_bytes())
    before_data=yaml.safe_load(before)
    for key_id in (1, 2, 3, 15):
        assert result_data['keys'][key_id]['action']==before_data['keys'][key_id]['action']
        assert result_data['keys'][key_id]['label']==before_data['keys'][key_id]['label']
    for key_id in (2,3,15):
        assert result_data['keys'][key_id]['appearance']==before_data['keys'][1]['appearance']


def test_backend_rejects_stale_snapshot_without_backup(profile):
    root=profile.parent.parent.parent.parent
    payload=request(root)
    profile.write_bytes(profile.read_bytes()+b'\n# alterado externamente\n')
    content=profile.read_bytes()
    with pytest.raises(RuntimeError,match='mudou'):
        backend.run('quick_batch_appearance',payload,project=root)
    assert profile.read_bytes()==content
    assert not (root/'state').exists()


@pytest.mark.parametrize('extra', [
    {'targets': [4]}, {'source_key':2,'targets':[2]},
    {'targets':[]}, {'targets':[2,2]}, {'targets':[True]},
    {'sha256':'123'}, {'sha256':'Z'*64}, {'profile':42},
    {'profile':'Outro perfil'}, {'source_key':'1'},
    {'targets':[2], 'danger':'x'},
])
def test_backend_rejects_bad_inputs_before_save(profile,extra):
    root=profile.parent.parent.parent.parent
    payload=request(root)
    payload.update(extra)
    original=profile.read_bytes()
    with pytest.raises((ValueError, TypeError)):
        backend.run('quick_batch_appearance',payload,project=root)
    assert profile.read_bytes()==original
    assert not (root/'state').exists()


def test_backend_checks_file_again_just_before_commit(profile,monkeypatch):
    root=profile.parent.parent.parent.parent
    payload=request(root)
    original=profile.read_bytes()
    original_validate=__import__('vision02_editor_backend')._validate_at_same_location
    # Imported module name in standalone tests resolves to studio backend module.
    editor=__import__('vision02_editor_backend')
    def concurrent_change(path, data):
        temp, parsed=original_validate(path,data)
        path.write_bytes(original+b'\n# outra edicao\n')
        return temp, parsed
    monkeypatch.setattr(editor,'_validate_at_same_location',concurrent_change)
    with pytest.raises(RuntimeError,match='durante'):
        backend.run('quick_batch_appearance',payload,project=root)
    assert profile.read_bytes()==original+b'\n# outra edicao\n'


def source_between(code, start, end):
    return code.split(start,1)[1].split(end,1)[0]


def test_gtk_exposes_copy_controls_without_extra_tabs():
    gtk=(ROOT/'apps/vision02_studio.py').read_text()
    area=source_between(gtk,'def _build_quick_properties(', 'def _build_batch_appearance_v9(')
    assert area.count('= make_tab(')==4
    assert 'Gtk.Expander(' in area and 'self._build_batch_appearance_v9(batch_box)' in area
    for name in ('_quick_batch_copy','_quick_batch_apply','_quick_batch_controls'):
        assert 'def '+name+'(' in gtk
    assert 'quick_batch_appearance' in gtk


def test_backend_has_no_hid_or_ipc_for_batch():
    source=(ROOT/'apps/vision02_editor_backend.py').read_text()
    part=source_between(source,'def save_batch_appearance(', 'def preview_key(')
    for forbidden in ('ipc_request(', 'Vision02(', 'execute_action(', 'subprocess.'):
        assert forbidden not in part
    assert 'os.replace(' in part and '_validate_at_same_location(' in part


def test_batch_gui_uses_persisted_origin_revision():
    source=(ROOT/'apps/vision02_studio.py').read_text()
    code=source_between(source,'def _quick_batch_copy(', 'def _quick_batch_apply(')
    assert "'sha256': self._quick_loaded['sha256']" in code
    assert 'self._quick_dirty' in code
    assert "self._call('quick_batch_appearance'" in source_between(
        source,'def _quick_batch_apply(', 'def _build_composition_canvas(')


def test_batch_failure_not_trigger_ipc():
    source=(ROOT/'apps/vision02_studio.py').read_text()
    snippet=source_between(source,"elif command == 'quick_batch_appearance':",'self._quick_controls()')
    assert "self._call('previews')" in snippet
    assert "self._call('reload')" not in snippet


class FakeCheck:
    def __init__(self,active=False):
        self.active=active
        self.sensitive=False
    def get_active(self):return self.active
    def set_active(self,val):self.active=val
    def get_sensitive(self):return self.sensitive
    def set_sensitive(self,val):self.sensitive=val


def fake_window():
    controls={i:FakeCheck() for i in range(1,16)}
    return SimpleNamespace(
        _quick_loaded={'sha256':'a'*64},_quick_dirty=False,_busy=set(),
        _current='Teste',_selected_key=1,_quick_batch_configured={1,2,3},
        _quick_batch_clipboard=None, quick_batch_apply_btn=FakeCheck(),
        quick_batch_copy_btn=FakeCheck(),quick_batch_confirm=FakeCheck(),
        quick_batch_targets=controls,quick_batch_status=Mock(),quick_batch_source=Mock(),
        _call=Mock(),_quick_batch_controls=None,
    )


def studio_class():
    # GTK não está instalado no Python isolado dos testes. Verifica a lógica
    # de callbacks por AST, sem executar o import GTK no ambiente virtual.
    import ast
    tree=ast.parse((ROOT/'apps/vision02_studio.py').read_text())
    klass=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='StudioWindow')
    methods={x.name:x for x in klass.body if isinstance(x,ast.FunctionDef) and x.name.startswith('_quick_batch_')}
    namespace={}
    exec(compile(ast.Module(body=list(methods.values()),type_ignores=[]),str(ROOT/'apps/vision02_studio.py'),'exec'),namespace)
    return namespace


def test_batch_gui_safety_and_explicit_confirmation():
    funcs=studio_class()
    obj=fake_window()
    obj._quick_batch_controls=lambda *x: funcs['_quick_batch_controls'](obj,*x)
    funcs['_quick_batch_controls'](obj)
    assert obj.quick_batch_copy_btn.sensitive
    funcs['_quick_batch_copy'](obj)
    assert obj._quick_batch_clipboard['source_key']==1
    assert not obj.quick_batch_targets[1].sensitive
    assert obj.quick_batch_targets[2].sensitive
    obj.quick_batch_targets[2].active=True
    funcs['_quick_batch_controls'](obj)
    assert not obj.quick_batch_apply_btn.sensitive
    obj.quick_batch_confirm.active=True
    funcs['_quick_batch_controls'](obj)
    assert obj.quick_batch_apply_btn.sensitive
    funcs['_quick_batch_apply'](obj)
    obj._call.assert_called_once_with('quick_batch_appearance',profile='Teste',source_key=1,
                                      targets=[2],sha256='a'*64)


def test_batch_gui_never_copies_unsaved_changes():
    f=studio_class();obj=fake_window();obj._quick_dirty=True
    obj._quick_batch_controls=lambda *x: f['_quick_batch_controls'](obj,*x)
    f['_quick_batch_copy'](obj)
    assert obj._quick_batch_clipboard is None
    obj._call.assert_not_called()


def test_batch_gui_rejects_revision_change_and_unconfigured_targets():
    f=studio_class();obj=fake_window();obj._quick_batch_controls=lambda *x:f['_quick_batch_controls'](obj,*x)
    f['_quick_batch_copy'](obj)
    obj.quick_batch_targets[4].active=True
    f['_quick_batch_controls'](obj)
    assert not obj.quick_batch_targets[4].active
    obj.quick_batch_targets[2].active=True
    obj.quick_batch_confirm.active=True
    obj._quick_loaded['sha256']='b'*64
    f['_quick_batch_apply'](obj)
    obj._call.assert_not_called()


def test_batch_gui_disables_when_busy():
    f=studio_class();obj=fake_window();obj._quick_batch_controls=lambda *x:f['_quick_batch_controls'](obj,*x)
    f['_quick_batch_copy'](obj)
    obj.quick_batch_targets[2].active=True
    obj.quick_batch_confirm.active=True
    obj._busy.add('quick_batch_appearance')
    f['_quick_batch_controls'](obj)
    assert not obj.quick_batch_apply_btn.sensitive
    assert not obj.quick_batch_targets[2].active


def test_targets_changed_must_reset_confirmation():
    f=studio_class();obj=fake_window()
    obj._quick_batch_controls=lambda *x:f['_quick_batch_controls'](obj,*x)
    f['_quick_batch_copy'](obj)
    obj.quick_batch_targets[2].active=True
    obj.quick_batch_confirm.active=True
    f['_quick_batch_target_toggled'](obj)
    assert not obj.quick_batch_confirm.get_active()
    assert not obj.quick_batch_apply_btn.sensitive


def test_batch_success_enables_explicit_ipc_only_after_refetch():
    gtk=(ROOT/'apps/vision02_studio.py').read_text()
    handler=source_between(gtk, "elif command == 'quick_batch_appearance':", 'self._quick_controls()')
    assert 'self._quick_batch_pending_apply = True' in handler
    assert 'self._quick_load()' in handler
    assert "self._call('reload')" not in handler
    inspect=source_between(gtk,"if command == 'quick_inspect':", "elif command == 'quick_preview':")
    assert 'self._quick_saved = self._quick_batch_pending_apply' in inspect
    assert 'self._quick_batch_pending_apply = False' in inspect
