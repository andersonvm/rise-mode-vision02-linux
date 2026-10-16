"""Backend JSON do Vision 02 Studio; nunca abre USB/HID.

Executado na .venv. A interface GTK roda no Python do sistema. Só comandos
IPC explícitos alteram o perfil; o restante é leitura ou importação de ícones.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'apps'))

from vision02.control_ipc import request as ipc_request
from vision02.icon_library import import_icon, list_icons
from vision02.system_dashboard import LinuxSampler
from vision02_gui_data import build_metadata
from vision02.user_profiles import default_profile_paths
from vision02_editor_backend import inspect_profile, preview_key, save_key, save_batch_appearance
from vision02.studio_inline_edit import form_to_key
from vision02.studio_presets_v10 import (
    list_presets, create_preset, rename_preset, delete_preset, apply_preset,
    export_preset, import_preset, preview_data,
)
from vision02_editor_backend import _resolve_profile, _validate_at_same_location, preview_appearance
from vision02.studio_preset_gallery_v11 import (
    gallery_items, update_metadata, duplicate_preset, remove_metadata,
)


def run(command: str, body: dict | None = None, *, project: Path = ROOT) -> dict:
    """Operações de acesso restrito, sem execução de ações HID ou OBS."""
    body = body or {}
    if not isinstance(body, dict):
        raise ValueError('Payload inválido')
    if command in ('quick_inspect', 'quick_preview', 'quick_save'):
        if command == 'quick_inspect':
            if set(body) != {'profile', 'key_id'}:
                raise ValueError('Informe perfil e tecla para edição')
        elif set(body) != {'profile', 'key_id', 'sha256', 'form'}:
            raise ValueError('Informe perfil, tecla, revisão e formulário')
        name, key_id = body['profile'], body['key_id']
        if not isinstance(name, str) or not name or type(key_id) is not int or not 1 <= key_id <= 15:
            raise ValueError('Perfil ou número de tecla inválido')
        if command == 'quick_inspect':
            info = inspect_profile(project, name)
            return {'ok': True, 'profile': name, 'key_id': key_id,
                    'sha256': info['sha256'], 'edited': info['keys'][str(key_id)],
                    'configured_keys': [int(k) for k, v in info['keys'].items()
                                        if v['action'].get('type') != 'none']}
        expected = body['sha256']
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError('Revisão SHA-256 inválida')
        edited = form_to_key(body['form'])
        if command == 'quick_preview':
            result = preview_key(project, name, key_id, edited, expected)
            return {'ok': True, 'profile': name, 'key_id': key_id,
                    'image': result['previews'][str(key_id)]['image'],
                    'layers': result.get('layers', {}),
                    'components': result.get('components', {})}
        return {'ok': True, 'profile': name, 'key_id': key_id,
                **save_key(project, name, key_id, edited, expected)}
    if command == 'quick_batch_appearance':
        if set(body) != {'profile', 'source_key', 'targets', 'sha256'}:
            raise ValueError('Informe perfil, origem, destinos e revisão SHA-256')
        name = body['profile']
        expected = body['sha256']
        if not isinstance(name, str) or not name:
            raise ValueError('Perfil inválido')
        if not isinstance(expected, str) or len(expected) != 64 or any(
                c not in '0123456789abcdef' for c in expected):
            raise ValueError('Revisão SHA-256 inválida')
        return {'profile': name, **save_batch_appearance(
            project, name, body['source_key'], body['targets'], expected)}
    if command.startswith('preset_'):
        if command == 'preset_gallery':
            if body:
                raise ValueError('Galeria não recebe argumentos')
            return {'ok': True, 'items': gallery_items()}
        if command == 'preset_gallery_favorite':
            if set(body) != {'id', 'favorite'}:
                raise ValueError('Informe preset e estado favorito')
            return {'ok': True, **update_metadata(body['id'], favorite=body['favorite'])}
        if command == 'preset_gallery_category':
            if set(body) != {'id', 'category'}:
                raise ValueError('Informe preset e categoria')
            return {'ok': True, **update_metadata(body['id'], category=body['category'])}
        if command == 'preset_gallery_duplicate':
            if set(body) != {'id', 'name'}:
                raise ValueError('Informe preset e nome da cópia')
            return {'ok': True, **duplicate_preset(body['id'], body['name'])}
        if command == 'preset_list':
            if body:
                raise ValueError('Listagem não recebe argumentos')
            return {'ok': True, 'presets': list_presets()}
        if command == 'preset_create':
            if set(body) != {'name', 'profile', 'key_id', 'sha256'}:
                raise ValueError('Informe nome, perfil, origem e revisão')
            path = _resolve_profile(project, body['profile'])
            return {'ok': True, **create_preset(body['name'], path, body['key_id'], body['sha256'])}
        if command == 'preset_rename':
            if set(body) != {'id', 'name'}:
                raise ValueError('Informe preset e novo nome')
            return {'ok': True, **rename_preset(body['id'], body['name'])}
        if command == 'preset_delete':
            if set(body) != {'id'}:
                raise ValueError('Informe preset')
            result = delete_preset(body['id'])
            remove_metadata(body['id'])
            return {'ok': True, **result}
        if command == 'preset_import':
            if set(body) != {'path'} or not isinstance(body['path'], str):
                raise ValueError('Selecione o ZIP')
            return {'ok': True, **import_preset(Path(body['path']))}
        if command == 'preset_export':
            if set(body) != {'id', 'path'} or not isinstance(body['path'], str):
                raise ValueError('Informe preset e ZIP')
            return {'ok': True, **export_preset(body['id'], Path(body['path']))}
        if command == 'preset_apply':
            if set(body) != {'id', 'profile', 'targets', 'sha256'}:
                raise ValueError('Informe preset, perfil, destinos e revisão')
            path = _resolve_profile(project, body['profile'])
            return {'ok': True, 'profile': body['profile'], **apply_preset(
                body['id'], path, body['targets'], body['sha256'], _validate_at_same_location)}
        if command == 'preset_preview':
            if set(body) != {'id', 'profile', 'key_id'} or type(body['key_id']) is not int or not 1 <= body['key_id'] <= 15:
                raise ValueError('Informe preset, perfil e tecla')
            info = inspect_profile(project, body['profile'])
            entry = info['keys'][str(body['key_id'])]
            manifest, image = preview_data(body['id'])
            result = preview_appearance(project, body['profile'], {
                'label': entry['label'] or ' ',
                'image': str(image) if image else '',
                'appearance': manifest['appearance'],
            })
            return {'ok': True, 'image': result['image'], 'id': body['id']}
        raise ValueError('Comando de preset desconhecido')
    if command == 'status':
        if body:
            raise ValueError('status não recebe argumentos')
        return ipc_request('status', timeout=7)
    if command == 'switch':
        if set(body) != {'target'} or not isinstance(body['target'], str):
            raise ValueError('Informe target')
        return ipc_request('switch', body['target'], timeout=12)
    if command == 'reload':
        if body:
            raise ValueError('reload não recebe argumentos')
        return ipc_request('reload', timeout=25)
    if command == 'previews':
        if body:
            raise ValueError('previews não recebe argumentos')
        result = build_metadata(project, default_profile_paths(project))
        return {'ok': True, **result}
    if command == 'key_activity':
        if body:
            raise ValueError('key_activity não recebe argumentos')
        return ipc_request('key_activity', timeout=7)
    if command == 'live_preview':
        if body:
            raise ValueError('live_preview não recebe argumentos')
        return ipc_request('display_preview', timeout=7)
    if command == 'icons':
        if body:
            raise ValueError('icons não recebe argumentos')
        return {'ok': True, 'icons': list_icons()}
    if command == 'import_icon':
        if set(body) != {'path'} or not isinstance(body['path'], str) or not body['path']:
            raise ValueError('Selecione uma imagem')
        return {'ok': True, 'icon': import_icon(Path(body['path']))}
    if command == 'system':
        if body:
            raise ValueError('system não recebe argumentos')
        sampler = LinuxSampler()
        sampler.collect()
        time.sleep(0.22)
        return {'ok': True, 'metrics': asdict(sampler.collect())}
    if command == 'obs':
        if body:
            raise ValueError('obs não recebe argumentos')
        from vision02_obs_panel_backend import discover
        return {'ok': True, 'obs': discover()}
    raise ValueError('Comando do Studio desconhecido')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Vision 02 Studio — backend JSON seguro')
    parser.add_argument('--command', required=True,
                        choices=('status', 'switch', 'reload', 'previews', 'live_preview', 'key_activity', 'icons',
                                 'quick_inspect', 'quick_preview', 'quick_save', 'quick_batch_appearance',
                                 'import_icon', 'system', 'obs', 'preset_list', 'preset_create', 'preset_rename',
                                 'preset_delete', 'preset_import', 'preset_export', 'preset_apply', 'preset_preview',
                                 'preset_gallery', 'preset_gallery_favorite', 'preset_gallery_category',
                                 'preset_gallery_duplicate'))
    args = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin) if not sys.stdin.isatty() and not sys.stdin.closed else {}
        output = run(args.command, payload)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, TimeoutError) as exc:
        output = {'ok': False, 'error': str(exc)}
    print(json.dumps(output, ensure_ascii=False))
    return 0 if output.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
