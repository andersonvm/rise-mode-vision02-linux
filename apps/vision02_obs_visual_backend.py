"""JSON backend for visual scene editor and OBS audio mixer (no USB/HID)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'apps'))

from vision02.obs_profile_bundle import SCENES, AUDIO
from vision02.obs_visual_layout import inspect_layout, save_layout
from vision02.obs_websocket import OBSConnection, OBSError, read_config
from vision02.control_ipc import request as ipc_request
from vision02_obs_panel_backend import discover


def audio_state(*, connector=None, reader=read_config) -> dict:
    """Read-only OBS input levels, mute flags and current scene."""
    config = reader()
    connection = (connector or OBSConnection.connect)(config)
    try:
        names = [row.get('inputName') for row in connection.call('GetInputList').get('inputs', [])
                 if isinstance(row, dict) and isinstance(row.get('inputName'), str)]
        result = []
        for name in names[:64]:
            try:
                response = connection.call('GetInputVolume', {'inputName': name})
                muted = connection.call('GetInputMute', {'inputName': name}).get('inputMuted')
                mult = response.get('inputVolumeMul')
                pct = round(mult * 100) if isinstance(mult, (float, int)) and not isinstance(mult, bool) else None
                result.append({'name': name, 'volume': pct, 'muted': muted if type(muted) is bool else None})
            except (OBSError, ValueError, KeyError, TypeError):
                result.append({'name': name, 'volume': None, 'muted': None})
        return {'ok': True, 'inputs': result}
    finally:
        connection.close()


def change_audio(request: dict, *, connector=None, reader=read_config) -> dict:
    """Explicit idempotent OBS volume/mute write; never toggles implicitly."""
    if not isinstance(request, dict) or set(request) not in ({'name', 'volume'}, {'name', 'muted'}):
        raise ValueError('Informe name + volume ou name + muted')
    name = request['name']
    if not isinstance(name, str) or not name or len(name) > 128:
        raise ValueError('Nome de fonte inválido')
    if 'volume' in request and (type(request['volume']) is not int or not 0 <= request['volume'] <= 100):
        raise ValueError('Volume deve estar entre 0 e 100%')
    if 'muted' in request and type(request['muted']) is not bool:
        raise ValueError('muted deve ser booleano')
    config = reader()
    connection = (connector or OBSConnection.connect)(config)
    try:
        inputs = connection.call('GetInputList').get('inputs', [])
        available = {item.get('inputName') for item in inputs if isinstance(item, dict)}
        if name not in available:
            raise ValueError('Fonte não encontrada no OBS; atualize a lista')
        if 'volume' in request:
            connection.call('SetInputVolume', {'inputName': name, 'inputVolumeMul': request['volume'] / 100.0})
        else:
            connection.call('SetInputMute', {'inputName': name, 'inputMuted': request['muted']})
        return {'ok': True, 'name': name}
    finally:
        connection.close()


def run(command: str, body: dict | None = None) -> dict:
    body = body or {}
    if command == 'discover':
        return {'ok': True, 'obs': discover()}
    if command == 'live':
        response = {'ok': True, 'obs': discover()}
        try:
            response['audio'] = audio_state()
        except (OBSError, OSError, RuntimeError, ValueError):
            pass  # A falha na leitura do mixer não impede o estado das cenas.
        return response
    if command == 'inspect':
        return inspect_layout(body.get('profile'))
    if command == 'save':
        return save_layout(body.get('profile'), body.get('entries'), body.get('version'))
    if command == 'audio':
        return audio_state()
    if command == 'audio_set':
        return change_audio(body)
    if command == 'apply':
        response = ipc_request('reload')
        if not response.get('ok'):
            raise RuntimeError(response.get('error') or 'Falha no reload IPC')
        return {'ok': True, 'ipc': response}
    raise ValueError('Comando desconhecido')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Backend visual OBS / Vision02')
    parser.add_argument('--command', required=True,
                        choices=('discover', 'live', 'inspect', 'save', 'audio', 'audio_set', 'apply'))
    args = parser.parse_args(argv)
    try:
        body = json.load(sys.stdin) if args.command in ('inspect', 'save', 'audio_set') else None
        result = run(args.command, body)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, OBSError) as exc:
        result = {'ok': False, 'error': str(exc)}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
