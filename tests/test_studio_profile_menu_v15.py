"""Integração do Menu de Perfis no Studio: segurança, compatibilidade, IPC explícito."""
from __future__ import annotations
import ast
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
import yaml
from PIL import Image

from vision02 import studio_profile_menu_v15 as menu

ROOT = Path(__file__).resolve().parents[1]
GUI_SOURCE = (ROOT/'apps/vision02_studio.py').read_text(encoding='utf-8')
GUI_AST = ast.parse(GUI_SOURCE)
WINDOW = next(x for x in GUI_AST.body if isinstance(x,ast.ClassDef) and x.name=='StudioWindow')


def gui_method(name):
    node=next(x for x in WINDOW.body if isinstance(x, ast.FunctionDef) and x.name==name)
    return ast.get_source_segment(GUI_SOURCE,node)


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'config'))
    monkeypatch.setenv('XDG_STATE_HOME',str(tmp_path/'state'))
    root=menu.config_root()/'profiles'
    root.mkdir(parents=True)
    for label in ('Sistema', 'Spotify', 'OBS Studio'):
        data={'version':1,'name':label,'keys':{
            1:{'label':'Abrir '+label,'action':{'type':'command','argv':['true']}},
            15:{'label':'Captura antiga', 'action':{'type':'command','argv':['echo','original']}}
        }}
        (root/(label.casefold().replace(' ','-')+'.yaml')).write_text(yaml.safe_dump(data,sort_keys=False,allow_unicode=True))
    return root


def test_menu_page_added_to_sidebar():
    constructor=gui_method('__init__')
    assert 'self._build_profile_menu()' in constructor
    assert "self._build_profiles()" in constructor
    assert "self._build_keys()" in constructor
    assert "self._build_profile_menu()" in constructor


def test_menu_page_inside_studio_not_external_app():
    method=gui_method('_build_profile_menu')
    assert "self._page(" in method
    assert "'profile_menu', 'Menu de Perfis'" in method
    assert 'Inspecionar catálogo' in method
    assert 'Sincronizar menu e tecla 15' in method
    assert 'Restaurar último backup' in method


def test_buttons_do_not_auto_reload_or_switch():
    src=gui_method('_menu_finished')
    assert "self._call('reload')" not in src
    assert "self._call('switch'" not in src
    assert 'Clique em Recarregar catálogo (IPC)' in src


def test_ipc_explicit_methods():
    assert "self._call('reload')" in gui_method('_menu_reload')
    assert "self._call('switch', target='Menu de Perfis')" in gui_method('_menu_open')


def test_guard_unsaved_edit_and_confirmation():
    apply=gui_method('_menu_run')
    assert 'self._quick_dirty' in apply
    assert "self.menu_confirm.get_active()" in apply
    assert "revision = self._menu_plan['revision']" in apply
    controls=gui_method('_menu_update_controls')
    assert 'and self.menu_confirm.get_active()' in controls


def test_main_python_for_backend_is_venv():
    src=gui_method('_menu_run')
    assert 'str(PYTHON)' in src
    assert "'-m', 'vision02.studio_profile_menu_v15'" in src
    assert "environment['PYTHONPATH']" in src
    assert 'threading.Thread' in src


def test_plan_lists_names_and_old_actions(profiles):
    info=menu.plan_result(menu.build_plan())
    assert info['ok'] is True
    assert info['count']==3
    assert len(info['pages'])==1
    assert info['files_to_write']>0
    assert {x['name'] for x in info['profiles']}=={'Sistema','Spotify','OBS Studio'}
    assert all(x['key15_before']=='Captura antiga' for x in info['profiles'])
    assert len(info['revision'])==64


def test_catalog_revision_stable_without_content_changes(profiles):
    before=menu.catalog_revision(profiles)
    paths=list(profiles.glob('*.yaml'))
    paths[0].touch()
    assert menu.catalog_revision(profiles)==before


def test_catalog_revision_detects_external_edit(profiles):
    before=menu.catalog_revision(profiles)
    item=next(profiles.glob('*.yaml'))
    item.write_text(item.read_text()+'\n# Comentário local\n')
    assert menu.catalog_revision(profiles)!=before


def test_stale_inspection_refuses_apply(profiles):
    revision=menu.build_plan()['revision']
    changed=next(profiles.glob('*.yaml'))
    raw=changed.read_bytes()
    changed.write_bytes(raw+b'\n# nova configuracao\n')
    with pytest.raises(RuntimeError,match='alterados após a inspeção'):
        menu.apply(ROOT,expected_revision=revision)
    assert not (profiles/'menu-de-perfis.yaml').exists()
    assert changed.read_bytes()==raw+b'\n# nova configuracao\n'


def test_apply_preserves_existing_keys_and_labels(profiles):
    originals={p.name:yaml.safe_load(p.read_text()) for p in profiles.glob('*.yaml')}
    result=menu.apply(ROOT,expected_revision=menu.build_plan()['revision'])
    assert result['ok']
    for name,old in originals.items():
        new=yaml.safe_load((profiles/name).read_text())
        assert old['keys'][1]==new['keys'][1]
        assert new['keys'][15]['action']=={'type':'profile','target':'Menu de Perfis'}
    assert (profiles/'menu-de-perfis.yaml').is_file()


def test_apply_creates_valid_png_icons(profiles):
    menu.apply(ROOT)
    iconroot=menu.config_root()/'profile-icons/menu-de-perfis'
    for i in range(1,4):
        data=(iconroot/f'perfil-{i:02}.png').read_bytes()
        with Image.open(BytesIO(data)) as picture:
            assert picture.size==(100,100)
            assert picture.format=='PNG'
    assert (iconroot/'voltar-menu.png').exists()


def test_apply_is_idempotent(profiles):
    menu.apply(ROOT)
    plan=menu.build_plan()
    assert plan['changes']=={}
    assert menu.apply(ROOT,expected_revision=plan['revision'])['files']==0


def test_backup_restore_exact_original_bytes(profiles):
    original={p.name:p.read_bytes() for p in profiles.glob('*.yaml')}
    result=menu.apply(ROOT)
    backup=Path(result['backup'])
    assert backup.is_dir()
    assert menu.restore(backup)['ok'] is True
    for name,raw in original.items():
        assert (profiles/name).read_bytes()==raw
    assert not (profiles/'menu-de-perfis.yaml').exists()


def test_restore_refuses_if_modified_after_install(profiles):
    result=menu.apply(ROOT)
    p=profiles/'sistema.yaml'
    raw=p.read_bytes()
    p.write_bytes(raw+b'\n# alteracao do usuario\n')
    with pytest.raises(RuntimeError,match='alteração local'):
        menu.restore(Path(result['backup']))
    assert p.read_bytes()==raw+b'\n# alteracao do usuario\n'


def test_multiple_pages_keep_key15_for_next_menu(profiles):
    for index in range(16):
        data={'version':1,'name':f'Programa {index:02}', 'keys':{
            1:{'label':'Abrir', 'action':{'type':'command','argv':['true']}}
        }}
        (profiles/f'programa-{index:02}.yaml').write_text(yaml.safe_dump(data,sort_keys=False))
    plan=menu.build_plan()
    assert len(plan['pages'])==2
    main=plan['changes'][profiles/'menu-de-perfis.yaml']
    second=plan['changes'][profiles/'menu-de-perfis-2.yaml']
    assert yaml.safe_load(main)['keys'][15]['action']['target']=='Menu de Perfis 2'
    assert yaml.safe_load(second)['keys'][15]['action']['target']=='Menu de Perfis'


def test_menu_does_not_appear_as_its_own_destination(profiles):
    menu.apply(ROOT)
    result=menu.plan_result(menu.build_plan())
    assert result['count']==3
    assert all(not menu.is_menu_name(p['name']) for p in result['profiles'])


def test_invalid_profile_rejected_without_changes(profiles):
    bad=profiles/'broken.yaml'
    bad.write_text('version: 1\nname: Inválido\nkeys: nao-e-um-mapa\n')
    with pytest.raises(ValueError,match='Perfil YAML inválido'):
        menu.build_plan()
    assert not (profiles/'menu-de-perfis.yaml').exists()


def test_menu_updates_not_entangled_with_profiles_or_service():
    src=gui_method('_menu_run')
    for forbidden in ('git reset','systemctl','hidapi','usb.core','--force'):
        assert forbidden not in src
    assert 'self._menu_run' not in gui_method('_menu_reload')
