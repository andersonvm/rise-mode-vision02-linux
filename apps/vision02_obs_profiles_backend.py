"""Backend JSON para criar três perfis OBS; executado exclusivamente na .venv."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'apps'))
from vision02.obs_profile_bundle import create_bundle, preview
from vision02.obs_websocket import OBSError
from vision02.control_ipc import request as ipc_request
from vision02_obs_panel_backend import discover


def run(command: str, payload: dict | None = None):
    if command == 'catalog':
        return {'ok': True, 'catalog': preview()}
    if command == 'discover':
        return {'ok': True, 'obs': discover(), 'catalog': preview()}
    if command == 'create':
        if not isinstance(payload, dict):
            raise ValueError('Parâmetros ausentes')
        return create_bundle(payload.get('scenes'), payload.get('inputs'), payload.get('version'))
    if command == 'apply':
        response = ipc_request('reload')
        if not response.get('ok'):
            raise RuntimeError(response.get('error') or 'Falha no reload IPC')
        return response
    raise ValueError('Comando desconhecido')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Backend perfis OBS Vision02')
    parser.add_argument('--command', choices=['catalog', 'discover', 'create', 'apply'], required=True)
    args = parser.parse_args(argv)
    try:
        body = json.load(sys.stdin) if args.command == 'create' else None
        response = run(args.command, body)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, OBSError) as exc:
        response = {'ok': False, 'error': str(exc)}
    print(json.dumps(response, ensure_ascii=False))
    return 0 if response.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
