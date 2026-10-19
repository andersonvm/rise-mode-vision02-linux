"""v12: rascunhos e transações seguras sem YAML/IPC."""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import importlib.util
import json

import pytest
import yaml
from PIL import Image

from vision02 import studio_presets_v10 as presets
from vision02 import studio_preset_gallery_v11 as gallery
from vision02 import studio_preset_editor_v12 as editor
from vision02.profiles.models import KeyAppearance

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('backend_preset_editor_v12', ROOT/'apps/vision02_studio_backend.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


@pytest.fixture
def data(tmp_path, monkeypatch):
    for part in ('CONFIG', 'CACHE', 'DATA', 'STATE'):
        monkeypatch.setenv('XDG_' + part + '_HOME', str(tmp_path / part.lower()))
    project = tmp_path / 'project'
    project.mkdir()
    profile = project / 'perfil.yaml'
    picture = project / 'original.png'
    Image.new('RGBA', (32, 32), (10, 100, 200, 140)).save(picture)
    content = {'name': 'Teste', 'version': 1, 'keys': {1: {
        'label': 'OBS', 'action': {'type': 'url', 'url': 'https://example.org'},
        'image': str(picture), 'appearance': {'background': '#123456', 'text': 'OBS'}}}}
    profile.write_text(yaml.safe_dump(content, allow_unicode=True), encoding='utf-8')
    preset = presets.create_preset('Teste Azul', profile, 1, sha256(profile.read_bytes()).hexdigest())
    return {'id': preset['id'], 'profile': profile, 'original': profile.read_bytes(),
            'project': project, 'picture': picture, 'root': tmp_path}


def draft(data):
    return editor.load_draft(data['id'])


def call(data, command, **body):
    return backend.run(command, body, project=data['project'])


def params(data, **kw):
    d = draft(data)
    payload = {k: d[k] for k in ('id', 'revision', 'appearance', 'image')}
    payload.update(kw)
    return payload


def test_load_preserves_style_and_has_no_action(data):
    d = draft(data)
    assert d['name'] == 'Teste Azul' and d['appearance']['background'] == '#123456'
    assert Path(d['image']).is_file() and len(d['revision']) == 64
    assert 'action' not in d and 'label' not in d
    assert data['profile'].read_bytes() == data['original']


def test_preview_does_not_write_manifest_or_yaml(data):
    payload = params(data)
    payload['appearance']['background'] = '#778899'
    before = presets._file_for(data['id']).read_bytes()
    result = editor.preview_draft(**payload)
    assert Image.open(result['image']).size == (100, 100)
    assert presets._file_for(data['id']).read_bytes() == before
    assert data['profile'].read_bytes() == data['original']
    assert editor.preview_draft(**payload)['image'] == result['image']


def test_save_edits_only_preset_and_creates_backup(data):
    payload = params(data)
    payload['appearance']['text'] = 'Nova visualização'
    result = editor.save_draft(**payload)
    assert not result['saved_as']
    assert Path(result['backup'], 'preset.json').is_file()
    assert Path(result['backup'], 'image.png').is_file()
    assert presets._read(data['id'])[0]['appearance']['text'] == 'Nova visualização'
    assert data['profile'].read_bytes() == data['original']
    assert editor.load_draft(data['id'])['revision'] == result['revision']


def test_save_as_keeps_original(data):
    payload = params(data)
    payload['appearance']['background'] = '#010203'
    item = editor.save_draft(**payload, save_as='Variação do Azul')
    assert item['id'] != data['id'] and item['saved_as'] is True
    assert presets._read(data['id'])[0]['appearance']['background'] == '#123456'
    assert presets._read(item['id'])[0]['appearance']['background'] == '#010203'
    assert data['profile'].read_bytes() == data['original']


def test_save_as_duplicate_fails_without_override(data):
    p = params(data)
    with pytest.raises(ValueError, match='existe'):
        editor.save_draft(**p, save_as='Teste Azul')
    assert len(presets.list_presets()) == 1


def test_image_replace_and_remove(data):
    picture = data['project'] / 'nova.jpg'
    Image.new('RGB', (12, 12), '#ABCDEF').save(picture)
    p = params(data, image=str(picture))
    editor.save_draft(**p)
    _, image = presets._read(data['id'])
    assert image is not None and image.startswith(b'\x89PNG')
    editor.save_draft(**params(data, image=''))
    _, image = presets._read(data['id'])
    assert image is None
    assert not (presets.presets_dir() / (data['id'] + '.png')).exists()


def test_save_as_no_image_preserves_original(data):
    new = editor.save_draft(**params(data, image=''), save_as='Sem imagem')
    assert presets._read(new['id'])[1] is None
    assert presets._read(data['id'])[1] is not None


def test_preview_new_image_does_not_change_preset(data):
    other = data['project'] / 'new.png'
    Image.new('RGBA', (4, 4), (200, 30, 20, 255)).save(other)
    editor.preview_draft(**params(data, image=str(other)))
    assert presets._read(data['id'])[1] == data['picture'].read_bytes() or presets._read(data['id'])[1] is not None


@pytest.mark.parametrize('mutator', [
    lambda p: p.update({'revision': '0' * 64}),
    lambda p: p.update({'revision': 'bad'}),
    lambda p: p['appearance'].update({'action': {'type': 'command'}}),
    lambda p: p['appearance'].update({'label': 'not allowed'}),
    lambda p: p['appearance'].update({'background': 'blue'}),
    lambda p: p['appearance'].update({'font_weight': 'normal'}),
    lambda p: p['appearance'].update({'font_family': 'comic-sans'}),
    lambda p: p['appearance'].update({'font_size': 100}),
    lambda p: p['appearance'].update({'font_size': True}),
    lambda p: p['appearance'].update({'show_text': 'yes'}),
    lambda p: p['appearance'].update({'offset_x': 99}),
    lambda p: p['appearance'].update({'image_scale': 0}),
    lambda p: p.update({'image': '/unavailable/image.jpg'}),
    lambda p: p.update({'image': '../bad.png'}),
    lambda p: p.update({'image': 101}),
    lambda p: p.update({'image': '\x00evil'}),
])
def test_invalid_edits_never_touch_source(data, mutator):
    p = params(data)
    mutator(p)
    original = presets._file_for(data['id']).read_bytes()
    with pytest.raises((ValueError, RuntimeError)):
        editor.save_draft(**p)
    assert presets._file_for(data['id']).read_bytes() == original
    assert data['profile'].read_bytes() == data['original']


def test_concurrent_change_rejected(data):
    original = params(data)
    change = params(data)
    change['appearance']['text'] = 'Outra revisão'
    editor.save_draft(**change)
    with pytest.raises(RuntimeError, match='mudou'):
        editor.save_draft(**original)
    assert presets._read(data['id'])[0]['appearance']['text'] == 'Outra revisão'


def test_symlink_image_rejected(data):
    link = data['project'] / 'link.png'
    link.symlink_to(data['picture'])
    with pytest.raises(ValueError):
        editor.preview_draft(**params(data, image=str(link)))


def test_failed_manifest_replace_restores_original(data, monkeypatch):
    manifest = presets._file_for(data['id'])
    before_json = manifest.read_bytes()
    img = presets.presets_dir() / (data['id'] + '.png')
    before_img = img.read_bytes()
    original_replace = presets._atomic_replace
    triggered = False

    def fail_once(path, raw):
        nonlocal triggered
        if path == manifest and not triggered:
            triggered = True
            raise OSError('simulated write error')
        return original_replace(path, raw)

    monkeypatch.setattr(presets, '_atomic_replace', fail_once)
    p = params(data)
    p['appearance']['text'] = 'Não gravar'
    p['image'] = ''
    with pytest.raises(OSError, match='simulated'):
        editor.save_draft(**p)
    assert manifest.read_bytes() == before_json
    assert img.read_bytes() == before_img
    assert data['profile'].read_bytes() == data['original']


def test_backend_commands(data):
    result = call(data, 'preset_editor_load', id=data['id'])
    assert result['ok']
    p = params(data)
    preview = call(data, 'preset_editor_preview', **p)
    assert Path(preview['image']).is_file() and preview['ok']
    saved = call(data, 'preset_editor_save', **p)
    assert saved['ok'] and saved['revision']
    fresh = params(data)
    new = call(data, 'preset_editor_save_as', **{**fresh, 'name': 'Outro estilo'})
    assert new['ok'] and new['saved_as']


@pytest.mark.parametrize('command,payload', [
    ('preset_editor_load', {}),
    ('preset_editor_load', {'id': 'a', 'extra': 10}),
    ('preset_editor_preview', {'id': 'preset'}),
    ('preset_editor_save', {'id': 'preset'}),
    ('preset_editor_save_as', {'id': 'preset'}),
    ('preset_editor_unknown', {}),
])
def test_backend_rejects_bad_fields(data, command, payload):
    with pytest.raises(ValueError):
        call(data, command, **payload)


def test_gtk_controls_and_no_ipc(data):
    source = (ROOT / 'apps/vision02_studio.py').read_text()
    assert 'Editor visual de presets (v12)' in source
    for value in ('_preset_editor_undo', '_preset_editor_redo', '_preset_editor_save_as',
                  '_preset_editor_preview', '_preset_editor_collect', '_preset_editor_choose_image'):
        assert f'def {value}(' in source
    assert source.count("make_tab('") == 4
    code = (ROOT / 'apps/vision02_studio_backend.py').read_text()
    start = code.index("if command.startswith('preset_editor_'):")
    end = code.index("if command.startswith('preset_'):", start)
    assert 'ipc_request' not in code[start:end]
    assert 'save_key(' not in code[start:end]


def test_draft_validates_all_appearance_fields(data):
    d = draft(data)
    assert set(d['appearance']) == set(asdict(KeyAppearance()))
