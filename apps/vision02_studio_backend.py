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


def run(command: str, body: dict | None = None, *, project: Path = ROOT) -> dict:
    """Operações de acesso restrito, sem execução de ações HID ou OBS."""
    body = body or {}
    if not isinstance(body, dict):
        raise ValueError('Payload inválido')
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
                                 'import_icon', 'system', 'obs'))
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
