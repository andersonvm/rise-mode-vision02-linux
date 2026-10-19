"""Regressão para a exportação ZIP determinística (correção v11/v12)."""
from hashlib import sha256
from zipfile import ZipFile

from PIL import Image
import yaml

from vision02 import studio_presets_v10 as presets


def test_export_zip_has_stable_members_and_bytes(tmp_path, monkeypatch):
    for name in ('CONFIG', 'CACHE', 'DATA', 'STATE'):
        monkeypatch.setenv('XDG_' + name + '_HOME', str(tmp_path / name.lower()))
    picture = tmp_path / 'art.png'
    Image.new('RGBA', (8, 8), (50, 90, 140, 210)).save(picture)
    profile = tmp_path / 'perfil.yaml'
    profile.write_text(yaml.safe_dump({'version': 1, 'name': 'Teste', 'keys': {
        1: {'label': 'Item', 'action': {'type': 'none'},
            'image': str(picture), 'appearance': {'background': '#223344'}}
    }}), encoding='utf-8')
    ident = presets.create_preset('Preset Teste', profile, 1,
                                  sha256(profile.read_bytes()).hexdigest())['id']
    first, second = tmp_path / 'primeiro.zip', tmp_path / 'segundo.zip'
    presets.export_preset(ident, first)
    presets.export_preset(ident, second)
    assert first.read_bytes() == second.read_bytes()
    with ZipFile(first) as archive:
        assert archive.namelist() == ['preset.json', 'image.png']
        assert all(item.date_time == (1980, 1, 1, 0, 0, 0)
                   for item in archive.infolist())
