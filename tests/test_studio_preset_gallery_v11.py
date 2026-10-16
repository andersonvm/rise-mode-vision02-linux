"""Galeria v11: metadados locais e miniaturas sem modificar ações nem YAML."""
import importlib.util
import json
import os
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest
import yaml

from vision02 import studio_presets_v10 as v10
from vision02 import studio_preset_gallery_v11 as gallery

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('backend_gallery_v11', ROOT/'apps/vision02_studio_backend.py')
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)


@pytest.fixture
def sample(tmp_path, monkeypatch):
    for name in ('CONFIG', 'CACHE', 'DATA', 'STATE'):
        monkeypatch.setenv('XDG_'+name+'_HOME', str(tmp_path/name.lower()))
    original = tmp_path/'personal.yaml'
    picture = tmp_path/'logo.png'
    Image.new('RGBA', (72, 56), (50, 110, 180, 130)).save(picture)
    original.write_text(yaml.safe_dump({'version':1,'name':'Testes','keys':{
        1:{'label':'Firefox','action':{'type':'url','url':'https://example.com'},
           'appearance':{'background':'#334455','text':'Imagem visual'}, 'image':str(picture)},
        2:{'label':'Terminal','action':{'type':'command','argv':['echo','hello']},
           'appearance':{'background':'#101010'}},
        3:{'label':'OBS','action':{'type':'obs','operation':'scene_name','scene':'Ao vivo'}}}},sort_keys=False))
    return tmp_path, original


def created(sample, name='Meu Azul', key_id=1):
    return v10.create_preset(name, sample[1], key_id, sha256(sample[1].read_bytes()).hexdigest())['id']


def test_empty_gallery(sample):
    assert gallery.gallery_items() == []
    assert not gallery.metadata_path().exists()


def test_default_properties_and_png_thumbnail(sample):
    ident=created(sample)
    cards=gallery.gallery_items()
    assert len(cards)==1
    assert cards[0]['id']==ident
    assert cards[0]['favorite'] is False
    assert cards[0]['category']==''
    assert Path(cards[0]['thumbnail']).is_file()
    with Image.open(cards[0]['thumbnail']) as img:
        assert img.size==(100,100) and img.format=='PNG'


def test_gallery_id_does_not_change_v10_manifest(sample):
    ident=created(sample)
    before=v10._file_for(ident).read_bytes()
    gallery.update_metadata(ident, favorite=True, category='OBS / not valid') if False else None
    gallery.update_metadata(ident, favorite=True, category='OBS')
    assert v10._file_for(ident).read_bytes()==before
    assert gallery.gallery_items()[0]['favorite'] is True
    assert gallery.gallery_items()[0]['category']=='OBS'
    assert sample[1].read_bytes()


def test_metadata_permissions_and_structure(sample):
    ident=created(sample)
    gallery.update_metadata(ident, favorite=True)
    path=gallery.metadata_path()
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text())['entries'][ident]['favorite']
    assert json.loads(path.read_text())['schema']==1


@pytest.mark.parametrize('category', ['Meu tema', 'DevOps', 'áéíô', '', '  OBS  ', 'Todas as categorias'])
def test_valid_categories(sample,category):
    ident=created(sample)
    meta=gallery.update_metadata(ident, category=category)
    assert meta['category']==category.strip()


@pytest.mark.parametrize('category', ['/' , 'Infra/OBS', 'Infra\\OBS', '\t', '\n', 'a'*33, 123, None])
def test_bad_categories(sample,category):
    ident=created(sample)
    before=gallery.metadata_path().read_bytes() if gallery.metadata_path().exists() else None
    if category is None:
        with pytest.raises(ValueError):
            gallery.update_metadata(ident)
    else:
        with pytest.raises(ValueError):
            gallery.update_metadata(ident, category=category)
    assert (gallery.metadata_path().read_bytes() if gallery.metadata_path().exists() else None) == before


@pytest.mark.parametrize('favorite', [1, 0, 'yes', [], {}, 0.0])
def test_favorite_requires_boolean(sample,favorite):
    ident=created(sample)
    with pytest.raises(ValueError, match='booleano'):
        gallery.update_metadata(ident, favorite=favorite)


def test_favorite_toggle_and_order(sample):
    a=created(sample,'A')
    b=created(sample,'B',2)
    gallery.update_metadata(b,favorite=True)
    assert [x['id'] for x in gallery.gallery_items()]==[b,a]
    gallery.update_metadata(b,favorite=False)
    assert [x['id'] for x in gallery.gallery_items()]==[a,b]


def test_gallery_filter_favorites_category_query(sample):
    a=created(sample,'Azul Cloud')
    b=created(sample,'OBS Rosa',2)
    gallery.update_metadata(b,category='Streaming',favorite=True)
    cards=gallery.gallery_items()
    assert [p['id'] for p in gallery.filter_items(cards, 'obs')]==[b]
    assert [p['id'] for p in gallery.filter_items(cards, 'sTrEaM')]==[b]
    assert [p['id'] for p in gallery.filter_items(cards, favorites_only=True)]==[b]
    assert [p['id'] for p in gallery.filter_items(cards, category='Streaming')]==[b]
    assert gallery.filter_items(cards, query='Inexistente')==[]
    assert len(gallery.filter_items(cards))==2
    assert a in {p['id'] for p in cards}


def test_duplicate_keeps_v10_appearance_and_image(sample):
    a=created(sample)
    gallery.update_metadata(a, favorite=True,category='Jogos')
    b=gallery.duplicate_preset(a,'Variação Azul')['id']
    ma, ia=v10._read(a)
    mb, ib=v10._read(b)
    assert ma['appearance']==mb['appearance']
    assert ia==ib
    assert mb['name']=='Variação Azul'
    cards={p['id']:p for p in gallery.gallery_items()}
    assert cards[b]['category']=='Jogos'
    assert cards[b]['favorite'] is False
    assert cards[a]['favorite'] is True
    assert 'action' not in mb and 'label' not in mb


def test_duplicate_existing_name_no_change(sample):
    a=created(sample)
    with pytest.raises(ValueError, match='existe'):
        gallery.duplicate_preset(a,'Meu Azul')
    assert len(gallery.gallery_items())==1


def test_delete_metadata_not_reinherited(sample):
    ident=created(sample)
    gallery.update_metadata(ident,favorite=True,category='Temporária')
    v10.delete_preset(ident)
    gallery.remove_metadata(ident)
    assert gallery._read_meta()=={}
    created(sample)
    assert gallery.gallery_items()[0]['favorite'] is False


def test_old_manifest_is_unchanged_when_gallery_is_used(sample):
    ident=created(sample)
    out=sample[0]/'export.zip'
    v10.export_preset(ident,out)
    digest=sha256(out.read_bytes()).digest()
    gallery.update_metadata(ident, favorite=True,category='Infra')
    gallery.gallery_items()
    out2=sample[0]/'export2.zip'
    v10.export_preset(ident,out2)
    assert sha256(out2.read_bytes()).digest()==digest


def test_thumbnails_cache_reused_and_updated_after_rename(sample):
    ident=created(sample)
    first=gallery.gallery_items()[0]['thumbnail']
    second=gallery.gallery_items()[0]['thumbnail']
    assert first==second
    v10.rename_preset(ident,'Outro Azul')
    third=gallery.gallery_items()[0]['thumbnail']
    assert third!=first


def test_gallery_invalid_png_skipped(sample):
    ident=created(sample)
    (v10.presets_dir()/(ident+'.png')).write_bytes(b'invalid')
    assert gallery.gallery_items()==[]


def test_bad_metadata_detected(sample):
    created(sample)
    path=gallery.metadata_path()
    path.write_text('{invalid')
    with pytest.raises(ValueError,match='inválidos'):
        gallery.gallery_items()


def test_metadata_symlink_rejected(sample):
    ident=created(sample)
    outside=sample[0]/'outside'
    outside.write_text('secret')
    gallery.metadata_path().symlink_to(outside)
    with pytest.raises(ValueError,match='simbólico'):
        gallery.update_metadata(ident,favorite=True)
    assert outside.read_text()=='secret'


def test_cache_symlink_rejected(sample):
    created(sample)
    cache=Path(os.environ['XDG_CACHE_HOME'])/'vision02'
    cache.mkdir(parents=True)
    target=sample[0]/'other'
    target.mkdir()
    (cache/'preset-gallery-v11').symlink_to(target, target_is_directory=True)
    assert gallery.gallery_items()==[]
    assert list(target.iterdir())==[]


def test_backend_lists_gallery_without_modifying_profile(sample):
    ident=created(sample)
    raw=sample[1].read_bytes()
    response=backend.run('preset_gallery', {})
    assert response['ok'] and response['items'][0]['id']==ident
    assert sample[1].read_bytes()==raw


def test_backend_updates_and_duplicate(sample):
    a=created(sample)
    raw=sample[1].read_bytes()
    result=backend.run('preset_gallery_favorite',{'id':a,'favorite':True})
    assert result['favorite'] is True
    result=backend.run('preset_gallery_category',{'id':a,'category':'Transmissão'})
    assert result['category']=='Transmissão'
    result=backend.run('preset_gallery_duplicate',{'id':a,'name':'Uma cópia'})
    assert len(v10.list_presets())==2 and result['name']=='Uma cópia'
    assert sample[1].read_bytes()==raw


@pytest.mark.parametrize('cmd,payload', [
    ('preset_gallery', {'unused':True}),
    ('preset_gallery_favorite', {'id':'aaa'}),
    ('preset_gallery_favorite', {'id':'aaa','favorite':'true'}),
    ('preset_gallery_category', {'id':'aaa'}),
    ('preset_gallery_duplicate', {'id':'aaa','name':'x','extra':1}),
])
def test_backend_rejects_incorrect_payload(sample,cmd,payload):
    with pytest.raises(ValueError):
        backend.run(cmd,payload)


def test_gallery_is_not_new_notebook_tab(sample):
    source=(ROOT/'apps/vision02_studio.py').read_text()
    assert source.count("make_tab('Ação')")==1
    assert source.count("make_tab('Imagem')")==1
    assert source.count("make_tab('Texto')")==1
    assert source.count("make_tab('Composição')")==1
    for method in ('_gallery_render', '_gallery_choose','_gallery_duplicate'):
        assert 'def '+method in source
    assert "_call('preset_gallery')" in source


def test_backend_no_new_ipc(sample):
    text=(ROOT/'apps/vision02_studio_backend.py').read_text()
    section=text[text.index("if command == 'preset_gallery':"):text.index("if command == 'preset_list':")]
    assert 'ipc_request(' not in section
    assert 'save_key(' not in section
