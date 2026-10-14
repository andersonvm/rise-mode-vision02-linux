"""Perfis pessoais dinâmicos: testes offline, sem dispositivos HID."""
from __future__ import annotations
import json
import pytest
import yaml
from vision02.profile_catalog import ProfileCatalog, choose_initial, read_settings, read_last_active, write_last_active
from vision02.user_profiles import default_profile_paths


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    folder = tmp_path / 'config/vision02/profiles'
    folder.mkdir(parents=True)
    (folder / 'dev.yaml').write_text('version: 1\nname: Dev\nkeys:\n  15:\n    label: Ir observabilidade\n    action: {type: profile, target: Observabilidade}\n')
    (folder / 'observabilidade.yaml').write_text('version: 1\nname: Observabilidade\nkeys:\n  15:\n    label: Ir Dev\n    action: {type: profile, target: Dev}\n')
    return ProfileCatalog(folder)


def test_discovers_arbitrary_number_of_profiles(catalog, tmp_path):
    assert len(default_profile_paths(tmp_path)) == 2
    snapshot = catalog.snapshot()
    catalog.create('Extra', snapshot['version'])
    assert len(default_profile_paths(tmp_path)) == 3
    assert {p['name'] for p in catalog.snapshot()['profiles']} == {'Dev', 'Observabilidade', 'Extra'}


def test_duplicate_preserves_actions_and_references(catalog):
    source = catalog.root / 'dev.yaml'
    before = source.read_bytes()
    catalog.duplicate('Dev', 'Cópia Dev', catalog.snapshot()['version'])
    duplicated = catalog.root / 'copia-dev.yaml'
    assert yaml.safe_load(duplicated.read_text())['name'] == 'Cópia Dev'
    assert yaml.safe_load(duplicated.read_text())['keys'][15]['action']['target'] == 'Observabilidade'
    assert source.read_bytes() == before


def test_rename_updates_references_and_preserves_untouched_yaml(catalog):
    dev = catalog.root / 'dev.yaml'
    old = dev.read_bytes()
    catalog.rename('Observabilidade', 'SRE', catalog.snapshot()['version'])
    assert yaml.safe_load(dev.read_text())['keys'][15]['action']['target'] == 'SRE'
    other = catalog.root / 'observabilidade.yaml'
    assert yaml.safe_load(other.read_text())['keys'][15]['action']['target'] == 'Dev'
    assert catalog.snapshot()['profiles'][0]['name'] in {'Dev', 'SRE'}
    assert dev.read_bytes() != old


def test_unreferenced_delete_works_but_referenced_is_rejected(catalog):
    snapshot = catalog.snapshot()
    with pytest.raises(ValueError, match='referencia'):
        catalog.delete('Dev', snapshot['version'])
    snapshot = catalog.create('Extra', snapshot['version'])
    result = catalog.delete('Extra', snapshot['version'])
    assert len(result['profiles']) == 2


def test_active_profile_cannot_be_deleted_or_renamed(catalog):
    version = catalog.snapshot()['version']
    with pytest.raises(ValueError, match='perfil em uso'):
        catalog.delete('Dev', version, active='Dev')
    with pytest.raises(ValueError, match='perfil em uso'):
        catalog.rename('Dev', 'Outro', version, active='Dev')


def test_stale_catalog_rejected(catalog):
    before = catalog.snapshot()['version']
    catalog.create('Novo', before)
    with pytest.raises(RuntimeError, match='alterado'):
        catalog.create('Segundo', before)


def test_invalid_name_rejected(catalog):
    for name in ('', '../../escape', 'carro\nfoo', ' Outro '):
        with pytest.raises(ValueError):
            catalog.create(name, catalog.snapshot()['version'])


def test_last_active_and_startup_selection(catalog):
    assert choose_initial(['Dev', 'Observabilidade']) == 'Dev'
    catalog.set_startup('Observabilidade', restore_last=False)
    assert choose_initial(['Dev', 'Observabilidade']) == 'Observabilidade'
    write_last_active('Dev')
    assert read_last_active() == 'Dev'
    assert choose_initial(['Dev', 'Observabilidade']) == 'Observabilidade'
    catalog.set_startup('Observabilidade', restore_last=True)
    assert choose_initial(['Dev', 'Observabilidade']) == 'Dev'
    assert choose_initial(['Observabilidade']) == 'Observabilidade'


def test_rename_updates_saved_preferences(catalog):
    catalog.set_startup('Observabilidade', restore_last=True)
    write_last_active('Observabilidade')
    catalog.rename('Observabilidade', 'SRE', catalog.snapshot()['version'])
    assert read_settings()['startup_profile'] == 'SRE'
    assert read_last_active() == 'SRE'


def test_backup_created_for_mutation(catalog):
    result = catalog.create('Novo', catalog.snapshot()['version'])
    from pathlib import Path
    folder = Path(result['backup'])
    assert (folder / 'dev.yaml').exists()
    assert (folder / 'observabilidade.yaml').exists()
    assert not (folder / 'novo.yaml').exists()


def test_cli_catalog_flag_and_profile_persistence(catalog, tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch
    from vision02.cli import main
    monkeypatch.chdir(tmp_path)
    device = MagicMock()
    device.read_event.side_effect = [(15, True), None, (15, False), KeyboardInterrupt()]
    # catalog organiza por nome de arquivo: dev.yaml inicia primeiro
    with (patch('vision02.cli.Vision02') as vision,
          patch('vision02.cli.Vision02Controller')):
        vision.return_value.__enter__.return_value = device
        main(['profile', 'run', '--catalog'])
    assert read_last_active() == 'Observabilidade'
    assert device.set_image.call_count == 30


def test_cli_catalog_resumes_last_profile(catalog, tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch
    from vision02.cli import main
    monkeypatch.chdir(tmp_path)
    write_last_active('Observabilidade')
    device = MagicMock()
    device.read_event.side_effect = KeyboardInterrupt()
    with (patch('vision02.cli.Vision02') as vision,
          patch('vision02.cli.Vision02Controller') as controller):
        vision.return_value.__enter__.return_value = device
        main(['profile', 'run', '--catalog'])
    assert controller.call_args.args[0].name == 'Observabilidade'


def test_backend_list_and_create(catalog, tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    from unittest.mock import patch
    filename = Path(__file__).resolve().parents[1] / 'apps/vision02_profile_manager_backend.py'
    spec = importlib.util.spec_from_file_location('profile_manager_backend', filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with patch.object(module, 'active_profile', return_value='Dev'):
        listed = module.process('list', catalog=catalog)
        assert listed['active'] == 'Dev'
        created = module.process('create', {'name': 'Novo', 'version': listed['version']}, catalog=catalog)
    assert 'Novo' in created['profiles']


def test_hotplug_catalog_command(catalog, tmp_path, monkeypatch):
    from unittest.mock import patch
    from vision02 import hotplug
    monkeypatch.chdir(tmp_path)
    commands = []
    class FakeSupervisor:
        def __init__(self, command, **kwargs):
            commands.append(command)
            self.stop = __import__('threading').Event()
        def run(self):
            pass
    with patch.object(hotplug, 'HotplugSupervisor', FakeSupervisor):
        hotplug.main(['--catalog'])
    assert commands[0][-2:] == ['--catalog', '--ipc']
