"""Galeria visual: testes puros, sem GTK, HID ou sessão gráfica."""
from __future__ import annotations

from pathlib import Path
import re

import pytest

from vision02.studio_icon_gallery import (
    MAX_GALLERY_ICONS, filtered_icons, icon_by_path, normalized,
)

ROOT = Path(__file__).resolve().parents[1]


def catalog():
    return [
        {'name': 'Grafana', 'path': '/tmp/grafana.png', 'id': '1'},
        {'name': 'Observação', 'path': '/tmp/observacao.png', 'id': '2'},
        {'name': 'OBS Studio', 'path': '/tmp/obs.png', 'id': '3'},
        {'name': 'Python', 'path': '/tmp/python.png', 'id': '4'},
    ]


@pytest.mark.parametrize('text,expected', [
    ('Câmera', 'camera'),
    ('ÃO', 'ao'),
    (' ÍCONES ', 'icones'),
    ('OBS STUDIO', 'obs studio'),
    ('Straße', 'strasse'),
    ('', ''),
    ('a\u0301', 'a'),
])
def test_normalized_search(text, expected):
    assert normalized(text) == expected


@pytest.mark.parametrize('text', [None, 45, ['OBS']])
def test_normalized_rejects_other_types(text):
    with pytest.raises(ValueError):
        normalized(text)


def test_filter_without_query_retains_order():
    assert filtered_icons(catalog()) == catalog()


@pytest.mark.parametrize('query,expected', [
    ('OBS', ['Observação', 'OBS Studio']),
    ('obs', ['Observação', 'OBS Studio']),
    ('servação', ['Observação']),
    ('observacao', ['Observação']),
    ('GRÁF', ['Grafana']),
    ('grafana', ['Grafana']),
    ('', ['Grafana', 'Observação', 'OBS Studio', 'Python']),
    ('inexistente', []),
])
def test_filter_matches_names_accent_insensitive(query, expected):
    assert [icon['name'] for icon in filtered_icons(catalog(), query)] == expected


def test_filter_does_not_mutate_source():
    source = catalog()
    before = [dict(item) for item in source]
    filtered_icons(source, 'py')
    assert source == before


def test_filter_deduplicates_paths():
    icons = catalog()
    icons.append({'name': 'Duplicado', 'path': '/tmp/obs.png'})
    assert len(filtered_icons(icons)) == len(catalog())


def test_filter_rejects_relative_empty_or_non_dict_entries():
    icons = [None, {'name': 'Inseguro', 'path': '../out.png'},
             {'name': 'Vazio', 'path': ''}, {'name': 'Sem caminho'},
             {'name': 'Ok', 'path': '/tmp/grafana.png'}]
    assert filtered_icons(icons) == [icons[-1]]


@pytest.mark.parametrize('limit', [0, -1, 501, True])
def test_invalid_limits_rejected(limit):
    if limit is True:
        # Python trata booleano como inteiro; não é interface pública de segurança.
        assert len(filtered_icons(catalog(), limit=limit)) == 1
    else:
        with pytest.raises(ValueError):
            filtered_icons(catalog(), limit=limit)


def test_invalid_catalog_rejected():
    with pytest.raises(ValueError):
        filtered_icons('não é lista')


def test_limit_keeps_stable_first_matches():
    assert filtered_icons(catalog(), limit=2) == catalog()[:2]


def test_default_limit_90():
    icons = [{'name': f'Ícone {i}', 'path': f'/tmp/{i}.png'} for i in range(200)]
    result = filtered_icons(icons)
    assert len(result) == MAX_GALLERY_ICONS == 90
    assert result[-1]['path'] == '/tmp/89.png'


def test_select_requires_exact_catalog_entry():
    assert icon_by_path(catalog(), '/tmp/obs.png')['name'] == 'OBS Studio'
    assert icon_by_path(catalog(), '/tmp/missing.png') is None
    assert icon_by_path(catalog(), 'obs.png') is None
    assert icon_by_path(catalog(), None) is None


def test_selection_never_modifies_source():
    icons = catalog()
    old = [dict(item) for item in icons]
    selected = icon_by_path(icons, '/tmp/obs.png')
    assert selected == icons[2]
    assert icons == old


def test_gtk_gallery_reuses_same_icon_service():
    gtk = (ROOT/'apps/vision02_studio.py').read_text()
    assert "self._call('icons')" in gtk
    assert 'filtered_icons(self._icons, needle)' in gtk
    assert 'Gtk.Picture.new_for_file(' in gtk
    assert 'quick_icon_flow' in gtk
    assert "self._quick_preview()" in gtk


def test_single_click_only_changes_image_and_local_preview():
    gtk = (ROOT/'apps/vision02_studio.py').read_text()
    method = gtk.split('    def _quick_pick_icon(', 1)[1].split('    def _render_quick_icons(', 1)[0]
    assert 'icon_by_path(self._icons, path)' in method
    assert 'self.quick_image.set_text(path)' in method
    assert 'self._quick_preview()' in method
    assert "self._call('reload')" not in method
    assert 'save_key(' not in method


def test_import_uses_existing_backend_and_updates_catalog():
    gtk = (ROOT/'apps/vision02_studio.py').read_text()
    backend = (ROOT/'apps/vision02_studio_backend.py').read_text()
    assert 'Gtk.FileChooserNative.new(' in gtk
    assert "self._call('import_icon', path=selected.get_path())" in gtk
    assert "self._call('icons')" in gtk
    assert "return {'ok': True, 'icon': import_icon(Path(body['path']))}" in backend


def test_import_does_not_change_another_key():
    gtk = (ROOT/'apps/vision02_studio.py').read_text()
    assert 'target == (self._current, self._selected_key)' in gtk
    assert 'self._quick_import_target = None' in gtk


def test_gallery_preserves_existing_save_apply_confirmation():
    gtk = (ROOT/'apps/vision02_studio.py').read_text()
    assert "self._call('quick_save'," in gtk
    assert "self._call('reload')" in gtk
    assert "'Salvar YAML com backup'" in gtk
    assert "'Aplicar ao dispositivo (IPC)'" in gtk


def test_no_hid_or_direct_obs_command_in_new_gallery():
    gtk = (ROOT/'apps/vision02_studio.py').read_text()
    module = (ROOT/'src/vision02/studio_icon_gallery.py').read_text()
    assert 'Vision02(' not in gtk
    assert 'hidraw' not in module
    assert 'subprocess' not in module
    assert 'obs.json' not in module


def test_gallery_is_in_keys_not_separate_window():
    gtk = (ROOT/'apps/vision02_studio.py').read_text()
    assert "def _build_quick_properties(self, editor_split):" in gtk
    assert "Gtk.Expander(label='Galeria visual de ícones')" in gtk
    assert 'gallery.set_child(gallery_box)' in gtk
    assert 'editor_split.set_end_child(props_scroll)' in gtk
