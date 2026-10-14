"""CLI JSON offline para gerenciar perfis; jamais abre USB/HID.

Recebe payload JSON por stdin. Mutações protegidas por versão e lock.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from vision02.profile_catalog import ProfileCatalog, read_settings
from vision02.control_ipc import request as ipc_request


def active_profile() -> str | None:
    try:
        info = ipc_request('status', timeout=2)
        return info.get('active') if info.get('ok') else None
    except (OSError, ConnectionError, RuntimeError, ValueError, TimeoutError):
        return None


def process(command: str, payload: dict | None = None, *, catalog: ProfileCatalog | None = None) -> dict:
    catalog = catalog or ProfileCatalog()
    if command == 'list':
        result = catalog.snapshot()
        result.update({'ok': True, 'active': active_profile()})
        return result
    payload = payload or {}
    if not isinstance(payload, dict):
        raise ValueError('Corpo da requisição deve ser um objeto JSON')
    expected = payload.get('version')
    if command != 'startup' and not isinstance(expected, str):
        raise ValueError('Versão do catálogo ausente')
    if command == 'create':
        return catalog.create(payload.get('name'), expected)
    if command == 'duplicate':
        return catalog.duplicate(payload.get('source'), payload.get('name'), expected)
    if command == 'rename':
        return catalog.rename(payload.get('source'), payload.get('name'), expected, active=active_profile())
    if command == 'delete':
        return catalog.delete(payload.get('name'), expected, active=active_profile())
    if command == 'startup':
        current = catalog.snapshot()
        if payload.get('version') != current['version']:
            raise RuntimeError('Catálogo modificado. Recarregue antes de alterar preferências.')
        names = [item['name'] for item in current['profiles']]
        if payload.get('name') not in names:
            raise ValueError('Perfil inicial não encontrado')
        return {'ok': True, 'settings': catalog.set_startup(payload['name'], restore_last=payload.get('restore_last'))}
    raise ValueError('Operação desconhecida')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--command', choices=('list', 'create', 'duplicate', 'rename', 'delete', 'startup'), required=True)
    args = parser.parse_args()
    try:
        request = None if args.command == 'list' else json.load(sys.stdin)
        result = process(args.command, request)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
