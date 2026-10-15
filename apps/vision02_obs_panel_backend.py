"""Backend do painel OBS GTK; não acessa HID nem altera obs.json.

Toda escrita nos perfis usa a mesma validação, backup e detecção de
concorrência do editor GTK existente. Credenciais nunca retornam ao painel.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'apps'))

from vision02.obs_websocket import OBSConnection, OBSError, read_config
from vision02.obs_control import OBS_OPERATIONS
import vision02_editor_backend as editor

PROFILE = 'OBS Studio'


def discover(connector=None, reader=read_config) -> dict:
    """Somente consultas. Nunca envia requests que modificam o OBS."""
    config = reader()
    connection = (connector or OBSConnection.connect)(config)
    try:
        version = connection.call('GetVersion')
        scenes_data = connection.call('GetSceneList')
        inputs_data = connection.call('GetInputList')
        special = connection.call('GetSpecialInputs')
        scenes = [row['sceneName'] for row in scenes_data.get('scenes', [])
                  if isinstance(row, dict) and isinstance(row.get('sceneName'), str)]
        inputs = [{'name': row['inputName'], 'kind': row.get('inputKind', '')}
                  for row in inputs_data.get('inputs', []) if isinstance(row, dict)
                  and isinstance(row.get('inputName'), str)]
        # Estado informativo; algumas instalações OBS não expõem todos os outputs.
        states = {}
        for name, method in [('recording', 'GetRecordStatus'),
                             ('streaming', 'GetStreamStatus'),
                             ('virtualcam', 'GetVirtualCamStatus')]:
            try:
                states[name] = connection.call(method).get('outputActive')
            except OBSError:
                states[name] = None
        return {
            'connected': True,
            'obs_version': version.get('obsVersion'),
            'websocket_version': version.get('obsWebSocketVersion'),
            'scenes': scenes,
            'active_scene': scenes_data.get('currentProgramSceneName'),
            'inputs': inputs,
            'mic_input': config.get('mic_input') or special.get('mic1'),
            'desktop_input': config.get('desktop_input') or special.get('desktop1'),
            'states': states,
        }
    finally:
        connection.close()


def profile_info(project: Path = ROOT) -> dict:
    return editor.inspect_profile(project, PROFILE)


def mapping_action(operation: str, *, scene: str = '', input_name: str = '', slot: int | None = None) -> dict:
    """Retorna ação OBS validada, sem operações arbitrárias do WebSocket."""
    if operation not in OBS_OPERATIONS:
        raise ValueError('Operação OBS desconhecida')
    result = {'type': 'obs', 'operation': operation}
    if operation == 'scene_name':
        if not isinstance(scene, str) or not scene.strip():
            raise ValueError('Selecione uma cena por nome')
        result['scene'] = scene.strip()
    elif scene:
        raise ValueError('Cena só é permitida em scene_name')
    if operation in ('toggle_mic', 'toggle_desktop'):
        if input_name:
            if not isinstance(input_name, str) or not input_name.strip():
                raise ValueError('Entrada OBS inválida')
            result['input'] = input_name.strip()
    elif input_name:
        raise ValueError('Entrada de áudio só é permitida no controle de áudio')
    if operation == 'scene_slot':
        if type(slot) is not int or not 1 <= slot <= 3:
            raise ValueError('Slot deve ser de 1 a 3')
        result['slot'] = slot
    elif slot is not None:
        raise ValueError('Slot só é permitido para scene_slot')
    return result


def save_mapping(project: Path, request: dict) -> dict:
    """Preserva ícone/aparência e outras teclas; rejeita mudanças concorrentes."""
    if not isinstance(request, dict):
        raise ValueError('Requisição deve ser objeto')
    key_id = request.get('key_id')
    if type(key_id) is not int or not 1 <= key_id <= 14:
        raise ValueError('Teclas OBS configuráveis: 01 a 14; tecla 15 reservada para Voltar')
    name = request.get('label')
    if not isinstance(name, str) or not name.strip() or len(name) > 70:
        raise ValueError('Rótulo deve conter de 1 a 70 caracteres')
    expected = request.get('sha256')
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError('SHA-256 esperado ausente')
    action = mapping_action(request.get('operation'),
                            scene=request.get('scene', ''),
                            input_name=request.get('input', ''),
                            slot=request.get('slot'))
    current = profile_info(project)
    if current['sha256'] != expected:
        raise RuntimeError('O perfil mudou no disco: recarregue a janela antes de salvar')
    if action['operation'] == 'scene_name':
        for other_key, value in current['keys'].items():
            other = value.get('action') or {}
            if int(other_key) != key_id and other.get('type') == 'obs' and other.get('operation') == 'scene_name' and other.get('scene') == action['scene']:
                raise ValueError(f'A cena {action["scene"]!r} já está vinculada à tecla {int(other_key):02d}. Use Organizar cenas para reorganizar.')
    previous = current['keys'][str(key_id)]
    # Não altera configurações visuais personalizadas nem recursos já importados.
    edited = {'label': name, 'image': previous.get('image', ''), 'action': action}
    return editor.save_key(project, PROFILE, key_id, edited, expected)


def save_scene_assignments(project: Path, request: dict) -> dict:
    """Grava múltiplas cenas por nome numa substituição atômica de YAML.

    Requer confirmação explícita na GUI. Só reconfigura as teclas escolhidas;
    preserva imagens, aparência, outros comandos e a tecla 15.
    """
    if not isinstance(request, dict):
        raise ValueError('Requisição inválida')
    expected = request.get('sha256')
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError('SHA-256 esperado ausente')
    assignments = request.get('assignments')
    if not isinstance(assignments, list) or not 1 <= len(assignments) <= 14:
        raise ValueError('Informe de 1 a 14 cenas')
    selected: dict[int, str] = {}
    used: set[str] = set()
    for row in assignments:
        if not isinstance(row, dict):
            raise ValueError('Associação inválida')
        key, scene = row.get('key_id'), row.get('scene')
        if type(key) is not int or not 1 <= key <= 14 or key in selected:
            raise ValueError('Teclas devem ser únicas e estar entre 01 e 14')
        mapping_action('scene_name', scene=scene)
        if scene in used:
            raise ValueError(f'Cena duplicada: {scene!r}. Escolha uma cena diferente por tecla.')
        selected[key] = scene
        used.add(scene)

    current = profile_info(project)
    if current['sha256'] != expected:
        raise RuntimeError('O perfil mudou no disco: recarregue antes de salvar')
    for other, cfg in current['keys'].items():
        action = cfg.get('action') or {}
        if int(other) not in selected and action.get('type') == 'obs' and action.get('operation') == 'scene_name' and action.get('scene') in used:
            raise ValueError(f'A cena {action["scene"]!r} já está atribuída à tecla {int(other):02d}. Inclua essa tecla na reorganização.')

    path = Path(current['path'])
    if path.is_symlink() or not path.is_file():
        raise ValueError('Perfil OBS inválido ou link simbólico')
    original = path.read_bytes()
    if editor._sha(original) != expected:
        raise RuntimeError('O perfil mudou no disco: recarregue antes de salvar')
    data = yaml.safe_load(original)
    if not isinstance(data, dict) or not isinstance(data.get('keys'), dict):
        raise ValueError('YAML OBS inválido')
    for key, scene in selected.items():
        key_config = data['keys'].setdefault(key, {})
        if not isinstance(key_config, dict):
            raise ValueError(f'Tecla {key:02d} inválida')
        key_config['label'] = scene[:70]
        key_config['action'] = {'type': 'obs', 'operation': 'scene_name', 'scene': scene}
    payload = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=90).encode('utf-8')
    temp, _ = editor._validate_at_same_location(path, payload)
    try:
        if path.read_bytes() != original:
            raise RuntimeError('O perfil mudou durante a gravação; nenhuma associação foi alterada')
        storage = (Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state'))
                   / 'vision02' / 'editor-backups')
        storage.mkdir(parents=True, exist_ok=True, mode=0o700)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = storage / f'{path.stem}-scene-batch-{stamp}-{expected[:12]}.yaml'
        with backup.open('xb') as dest:
            os.fchmod(dest.fileno(), 0o600)
            dest.write(original)
            dest.flush()
            os.fsync(dest.fileno())
        os.chmod(temp, path.stat().st_mode & 0o777)
        os.replace(temp, path)
        temp = None
        return {'ok': True, 'path': str(path), 'backup': str(backup),
                'sha256': editor._sha(payload), 'count': len(selected)}
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def apply_to_device(ipc=None) -> dict:
    if ipc is None:
        from vision02.control_ipc import request
        ipc = request
    result = ipc('reload')
    if not result.get('ok'):
        raise RuntimeError(result.get('error') or 'Falha no reload IPC')
    return result


def run(command: str, request: dict | None = None) -> dict:
    if command == 'discover':
        return {'ok': True, 'obs': discover()}
    if command == 'inspect':
        return {'ok': True, 'profile': profile_info()}
    if command == 'save':
        return save_mapping(ROOT, request or {})
    if command == 'apply':
        return {'ok': True, 'ipc': apply_to_device()}
    if command == 'save_scenes':
        return save_scene_assignments(ROOT, request or {})
    raise ValueError('Comando inválido')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Backend da configuração OBS da Vision 02')
    parser.add_argument('--command', required=True, choices=('discover', 'inspect', 'save', 'save_scenes', 'apply'))
    args = parser.parse_args(argv)
    try:
        request = json.load(sys.stdin) if args.command in ('save', 'save_scenes') else None
        result = run(args.command, request)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get('ok') else 2
    except (OSError, ValueError, KeyError, RuntimeError, TypeError, OBSError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
