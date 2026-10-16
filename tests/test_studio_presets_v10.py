"""v10: presets portáveis, segurança de armazenamento e compatibilidade com v9."""
import importlib.util
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
from zipfile import ZipFile

import pytest
import yaml
from PIL import Image

from vision02 import studio_presets_v10 as presets

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('presets_backend', ROOT/'apps/vision02_studio_backend.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    for name in ('CONFIG','DATA','STATE','CACHE'):
        monkeypatch.setenv('XDG_'+name+'_HOME', str(tmp_path / name.lower()))
    project = tmp_path / 'project'
    directory = project / 'examples/profiles'
    directory.mkdir(parents=True)
    picture = directory / 'logo.png'
    Image.new('RGBA', (40, 30), (14, 62, 91, 180)).save(picture)
    data = {'version': 1, 'name': 'Presets', 'keys': {
        1: {'label':'Origem', 'action':{'type':'url','url':'https://example.org'},
            'image': 'logo.png', 'appearance':{'background':'#334455','text':'Visual','font_size':24}},
        2: {'label':'OBS', 'action':{'type':'obs','operation':'scene_name','scene':'Ao vivo'},
            'appearance':{'background':'#112233'}},
        3: {'label':'Outra', 'action':{'type':'command','argv':['echo','hello']},
            'image':'logo.png'},
    }}
    profile = directory / 'preset.yaml'
    profile.write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False),encoding='utf-8')
    return project, profile


def call(ws, action, **kwargs):
    project, _ = ws
    # Profiles loader needs explicit path since temporary test profiles do not
    # participate in default_profile_paths. Monkeypatch only this test call.
    return backend.run(action,kwargs,project=project)


def original_sha(ws):
    return sha256(ws[1].read_bytes()).hexdigest()


def created(ws, name='Tema Azul'):
    return presets.create_preset(name, ws[1], 1, original_sha(ws))


def test_create_saves_style_image_and_no_action(workspace):
    saved=created(workspace)
    manifest,image=presets._read(saved['id'])
    assert manifest['name']=='Tema Azul'
    assert manifest['appearance']['background']=='#334455'
    assert 'action' not in manifest and 'label' not in manifest
    assert image is not None and image.startswith(b'\x89PNG')
    assert len(presets.list_presets())==1


@pytest.mark.parametrize('name', ['', '   ', '/danger', 'hi\\bad', 'a'*61, '🪁'])
def test_bad_names(workspace,name):
    with pytest.raises(ValueError):
        created(workspace,name)


@pytest.mark.parametrize('ident', ['../oops','UPPER','/etc/passwd', '', 'a'*70, 'a.b','-bad'])
def test_bad_ident(workspace,ident):
    with pytest.raises(ValueError):
        presets._read(ident)


def test_duplicate_name_and_unrelated_file_untouched(workspace):
    created(workspace)
    original=workspace[1].read_bytes()
    with pytest.raises(ValueError,match='existe'):
        created(workspace)
    assert workspace[1].read_bytes()==original


def test_stale_snapshot_rejected(workspace):
    initial=original_sha(workspace)
    workspace[1].write_bytes(workspace[1].read_bytes()+b'\n# alterado')
    with pytest.raises(RuntimeError,match='mudou'):
        presets.create_preset('Mais um',workspace[1],1,initial)
    assert presets.list_presets()==[]


def test_rename_preserves_asset_and_id(workspace):
    item=created(workspace)
    presets.rename_preset(item['id'],'Tema para OBS')
    assert presets.list_presets()[0]['name']=='Tema para OBS'
    assert presets.list_presets()[0]['id']==item['id']
    assert presets._read(item['id'])[1] is not None


def test_delete_preserves_applied_image(workspace):
    item=created(workspace)
    applied=presets.apply_preset(item['id'],workspace[1],[2],original_sha(workspace),_fake_validate)
    applied_yaml=yaml.safe_load(workspace[1].read_bytes())
    asset=Path(applied_yaml['keys'][2]['image'])
    assert asset.is_file() and asset.name.endswith('.png')
    presets.delete_preset(item['id'])
    assert asset.is_file() and not presets.list_presets()
    assert applied['ok']


def _fake_validate(path, payload):
    # Em integração real: load_profile + Image.verify no diretório do perfil.
    import tempfile
    import os
    fd, name = tempfile.mkstemp(dir=path.parent, suffix='.yaml')
    with os.fdopen(fd,'wb') as out:
        out.write(payload)
    yaml.safe_load(payload)
    return Path(name), None


def test_apply_preserves_actions_labels_and_backup(workspace):
    ident=created(workspace)['id']
    before=workspace[1].read_bytes()
    result=presets.apply_preset(ident,workspace[1],[2,3],original_sha(workspace),_fake_validate)
    after=yaml.safe_load(workspace[1].read_bytes())
    old=yaml.safe_load(before)
    assert result['targets']==[2,3]
    assert Path(result['backup']).read_bytes()==before
    for dest in (2,3):
        assert after['keys'][dest]['action']==old['keys'][dest]['action']
        assert after['keys'][dest]['label']==old['keys'][dest]['label']
        assert after['keys'][dest]['appearance']['text']=='Visual'
        assert Path(after['keys'][dest]['image']).is_file()
    assert after['keys'][1]==old['keys'][1]


@pytest.mark.parametrize('dest', [[],[16],[True],['2'],[2,2],[4],[0],list(range(16)),[2.1]])
def test_bad_targets_no_yaml_change(workspace,dest):
    ident=created(workspace)['id']; before=workspace[1].read_bytes()
    with pytest.raises(ValueError):
        presets.apply_preset(ident,workspace[1],dest,original_sha(workspace),_fake_validate)
    assert workspace[1].read_bytes()==before


def test_apply_stale_no_backup(workspace):
    ident=created(workspace)['id']
    old=original_sha(workspace)
    workspace[1].write_bytes(workspace[1].read_bytes()+b'\n# edited')
    with pytest.raises(RuntimeError,match='mudou'):
        presets.apply_preset(ident,workspace[1],[2],old,_fake_validate)
    assert not (Path(os.environ['XDG_STATE_HOME'])/'vision02').exists()


def test_apply_rejects_concurrent_change_and_leaves_updated_file(workspace):
    ident=created(workspace)['id']
    def concurrent(path, payload):
        temp,_=_fake_validate(path,payload)
        path.write_bytes(path.read_bytes()+b'\n# outra edicao')
        return temp,None
    with pytest.raises(RuntimeError,match='durante'):
        presets.apply_preset(ident,workspace[1],[2],original_sha(workspace),concurrent)
    assert workspace[1].read_bytes().endswith(b'\n# outra edicao')


def test_image_export_import_roundtrip(workspace):
    item=created(workspace)
    target=workspace[0]/'exportado.zip'
    presets.export_preset(item['id'],target)
    with ZipFile(target) as z:
        assert z.namelist()==['preset.json','image.png']
    original_manifest, original_image=presets._read(item['id'])
    presets.delete_preset(item['id'])
    imported=presets.import_preset(target)
    manifest,image=presets._read(imported['id'])
    assert image==original_image and manifest==original_manifest


def test_import_rejects_zip_extra_path(workspace):
    path=workspace[0]/'unsafe.zip'
    with ZipFile(path,'w') as z:
        z.writestr('preset.json','{}')
        z.writestr('../escape','malicious')
    with pytest.raises(ValueError,match='somente'):
        presets.import_preset(path)
    assert presets.list_presets()==[]


def test_import_wrong_checksum_fails(workspace):
    item=created(workspace)
    manifest,_=presets._read(item['id'])
    path=workspace[0]/'bad.zip'
    manifest['image_sha256']='0'*64
    with ZipFile(path,'w') as z:
        z.writestr('preset.json',json.dumps(manifest))
        z.writestr('image.png',presets._read(item['id'])[1])
    with pytest.raises(ValueError,match='Checksum'):
        presets.import_preset(path)


def test_import_rejects_executable_metadata(workspace):
    item=created(workspace)
    manifest,image=presets._read(item['id'])
    manifest['action']={'type':'command','argv':['bad']}
    path=workspace[0]/'bad.zip'
    with ZipFile(path,'w') as z:
        z.writestr('preset.json',json.dumps(manifest))
        z.writestr('image.png',image)
    with pytest.raises(ValueError,match='Formato'):
        presets.import_preset(path)


def test_export_refuses_overwrite(workspace):
    item=created(workspace)
    path=workspace[0]/'exists.zip'; path.write_bytes(b'dont change')
    with pytest.raises(ValueError):
        presets.export_preset(item['id'],path)
    assert path.read_bytes()==b'dont change'


def test_safe_symlink_preset_rejected(workspace):
    item=created(workspace)
    manifest=presets._file_for(item['id'])
    data=manifest.read_bytes(); manifest.unlink()
    other=workspace[0]/'external';other.write_bytes(data)
    manifest.symlink_to(other)
    with pytest.raises(ValueError):
        presets._read(item['id'])
    with pytest.raises(ValueError):
        presets.rename_preset(item['id'],'new')
    assert other.read_bytes()==data


def test_backend_commands_exposed_and_no_hid(workspace):
    code=(ROOT/'apps/vision02_studio_backend.py').read_text()
    gtk=(ROOT/'apps/vision02_studio.py').read_text()
    assert 'preset_create' in code and 'preset_apply' in code
    assert 'preset_import' in code and 'preset_export' in code
    assert 'Biblioteca de presets visuais (v10)' in gtk
    assert 'def _preset_received(' in gtk
    assert "= make_tab('" in gtk and gtk.count('= make_tab(')==4


def test_backend_list_and_payload_validation(workspace):
    assert backend.run('preset_list',{},project=workspace[0]) == {'ok':True,'presets':[]}
    with pytest.raises(ValueError):
        backend.run('preset_list',{'danger':True},project=workspace[0])
    for command in ['preset_create','preset_delete','preset_rename','preset_apply','preset_import','preset_export','preset_preview']:
        with pytest.raises(ValueError):
            backend.run(command, {'danger':True}, project=workspace[0])


def test_create_no_image_works(workspace):
    saved=presets.create_preset('Sem imagem',workspace[1],2,original_sha(workspace))
    manifest,image=presets._read(saved['id'])
    assert image is None and manifest['appearance']['background']=='#112233'
    dest=workspace[0]/'nopic.zip'
    presets.export_preset(saved['id'],dest)
    with ZipFile(dest) as z:
        assert z.namelist()==['preset.json']


def test_preset_file_modes_and_layout(workspace):
    item=created(workspace)
    assert presets._file_for(item['id']).stat().st_mode & 0o777 == 0o600
    assert presets.presets_dir().stat().st_mode & 0o777 == 0o700
    assert presets.assets_dir().stat().st_mode & 0o777 == 0o700


def test_backend_end_to_end_create_preview_apply_rename_export_delete(workspace,monkeypatch):
    editor = __import__('vision02_editor_backend')
    from vision02.profiles import load_profile
    monkeypatch.setattr(editor, 'allowed_profiles', lambda project, paths=None: {'Presets': workspace[1]})
    monkeypatch.setattr(backend, '_resolve_profile', lambda project, name: editor._resolve_profile(project,name))
    snapshot=editor.inspect_profile(workspace[0],'Presets')
    created=backend.run('preset_create',{
        'profile':'Presets','key_id':1,'sha256':snapshot['sha256'],'name':'Fundo Azul',
    }, project=workspace[0])
    assert created['ok']
    ident=created['id']
    assert backend.run('preset_list',{},project=workspace[0])['presets'][0]['id']==ident
    preview=backend.run('preset_preview',{'profile':'Presets','key_id':2,'id':ident},project=workspace[0])
    assert Path(preview['image']).is_file()
    assert preview['id']==ident
    saved=backend.run('preset_apply',{'profile':'Presets','sha256':snapshot['sha256'],
                        'id':ident,'targets':[2,3]}, project=workspace[0])
    assert saved['ok'] and Path(saved['backup']).exists()
    assert backend.run('preset_rename',{'id':ident,'name':'OBS Azul'},project=workspace[0])['name']=='OBS Azul'
    export=workspace[0]/'preset-bundle.zip'
    backend.run('preset_export',{'id':ident,'path':str(export)},project=workspace[0])
    assert export.is_file()
    backend.run('preset_delete',{'id':ident},project=workspace[0])
    assert backend.run('preset_list',{},project=workspace[0])['presets']==[]
    imported=backend.run('preset_import',{'path':str(export)},project=workspace[0])
    assert imported['ok'] and backend.run('preset_list',{},project=workspace[0])['presets'][0]['name']=='OBS Azul'


def test_preset_import_rejects_invalid_appearance_metadata(workspace):
    item=created(workspace)
    manifest,image=presets._read(item['id'])
    manifest['appearance']['font_size']=100000
    file=workspace[0]/'bad-style.zip'
    with ZipFile(file,'w') as z:
        z.writestr('preset.json',json.dumps(manifest))
        z.writestr('image.png',image)
    with pytest.raises(ValueError):
        presets.import_preset(file)


def test_image_in_preset_survives_original_deletion(workspace):
    item=created(workspace)
    (workspace[1].parent/'logo.png').unlink()
    assert presets._read(item['id'])[1] is not None


def test_asset_names_are_content_addressed(workspace):
    item=created(workspace)
    manifest,image=presets._read(item['id'])
    path=presets._asset(image)
    assert path.name==sha256(image).hexdigest()+'.png'
    assert presets._asset(image)==path
    assert path.stat().st_mode & 0o777==0o600


def test_preview_controls_are_local_only():
    gtk=(ROOT/'apps/vision02_studio.py').read_text()
    area=gtk.split('    def _preset_preview(self, *_):')[1].split('    def _preset_apply',1)[0]
    assert "self._call('preset_preview'" in area
    assert "self._call('reload'" not in area
    assert "self._call('quick_save'" not in area
