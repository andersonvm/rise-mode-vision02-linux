"""Ações e estados do OBS. Única thread de rede, sem USB/HID."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging
import queue
import threading
import time
from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageFont

from .obs_websocket import OBSConnection, OBSError, read_config
from .profiles.models import Action
from .protocol import physical_key_to_display_id

logger = logging.getLogger(__name__)

OBS_OPERATIONS = frozenset((
    'toggle_record', 'toggle_pause', 'toggle_stream', 'toggle_mic', 'toggle_desktop',
    'scene_slot', 'scene_name', 'next_scene', 'previous_scene', 'toggle_virtualcam',
    'save_replay', 'screenshot', 'refresh',
))


@dataclass(frozen=True)
class OBSSnapshot:
    connected: bool = False
    recording: bool | None = None
    paused: bool | None = None
    streaming: bool | None = None
    virtualcam: bool | None = None
    replay: bool | None = None
    mic_muted: bool | None = None
    desktop_muted: bool | None = None
    scene: str | None = None
    scenes: tuple[str, ...] = ()
    input_mutes: tuple[tuple[str, bool], ...] = ()


def _bool_response(connection, request, field):
    try:
        return connection.call(request).get(field)
    except OBSError:
        return None


def _bool_response_input(connection, name: str) -> bool | None:
    try:
        return connection.call('GetInputMute', {'inputName': name}).get('inputMuted')
    except OBSError:
        return None


def collect_snapshot(connection, config: dict) -> OBSSnapshot:
    record = connection.call('GetRecordStatus')
    stream = _bool_response(connection, 'GetStreamStatus', 'outputActive')
    cam = _bool_response(connection, 'GetVirtualCamStatus', 'outputActive')
    replay = _bool_response(connection, 'GetReplayBufferStatus', 'outputActive')
    scenes = connection.call('GetSceneList')
    names = tuple(item['sceneName'] for item in scenes.get('scenes', ()) if isinstance(item, dict) and isinstance(item.get('sceneName'), str))
    # OBS devolve as cenas na ordem da coleção; os três primeiros slots usam essa ordem.
    special = connection.call('GetSpecialInputs')
    mic = config.get('mic_input') or special.get('mic1')
    desktop = config.get('desktop_input') or special.get('desktop1')
    def mute(input_name):
        if not input_name:
            return None
        try:
            return connection.call('GetInputMute', {'inputName': input_name}).get('inputMuted')
        except OBSError:
            return None
    # Consulta apenas um conjunto limitado de fontes para preservar a latência.
    # Fontes que não suportam mute são ignoradas, sem derrubar a sessão OBS.
    input_mutes = []
    try:
        inputs = connection.call('GetInputList').get('inputs', [])
        for row in inputs[:32]:
            name = row.get('inputName') if isinstance(row, dict) else None
            if not isinstance(name, str) or not name:
                continue
            muted = _bool_response_input(connection, name)
            if isinstance(muted, bool):
                input_mutes.append((name, muted))
    except (OBSError, KeyError, TypeError, ValueError):
        pass
    return OBSSnapshot(
        input_mutes=tuple(input_mutes),
        connected=True, recording=record.get('outputActive'), paused=record.get('outputPaused'),
        streaming=stream, virtualcam=cam, replay=replay,
        mic_muted=mute(mic), desktop_muted=mute(desktop),
        scene=scenes.get('currentProgramSceneName'), scenes=names,
    )


def perform_action(connection, action: Action, snapshot: OBSSnapshot, config: dict):
    operation = action.obs_operation
    if operation not in OBS_OPERATIONS:
        raise OBSError('Operação OBS não permitida')
    if operation == 'refresh':
        return
    methods = {
        'toggle_record': 'ToggleRecord',
        'toggle_stream': 'ToggleStream',
        'toggle_virtualcam': 'ToggleVirtualCam',
    }
    if operation in methods:
        connection.call(methods[operation]); return
    if operation == 'toggle_pause':
        status = connection.call('GetRecordStatus')
        if status.get('outputActive') is not True:
            raise OBSError('Inicie a gravação antes de pausar')
        connection.call('ResumeRecord' if status.get('outputPaused') else 'PauseRecord')
        return
    if operation in ('toggle_mic', 'toggle_desktop'):
        special = connection.call('GetSpecialInputs')
        key = 'mic1' if operation == 'toggle_mic' else 'desktop1'
        custom = 'mic_input' if operation == 'toggle_mic' else 'desktop_input'
        name = action.obs_source or config.get(custom) or special.get(key)
        if not name:
            raise OBSError(f'Entrada {key} não encontrada; configure {custom} em obs.json')
        connection.call('ToggleInputMute', {'inputName': name})
        return
    if operation in ('scene_slot', 'scene_name', 'next_scene', 'previous_scene'):
        response = connection.call('GetSceneList')
        names = [item['sceneName'] for item in response.get('scenes', ())]
        if not names:
            raise OBSError('OBS não possui cenas')
        if operation == 'scene_name':
            if action.obs_scene not in names:
                raise OBSError(f'Cena não existe no OBS: {action.obs_scene!r}')
            target = action.obs_scene
        elif operation == 'scene_slot':
            if action.obs_slot is None or len(names) < action.obs_slot:
                raise OBSError('Slot de cena não existe no OBS')
            target = names[action.obs_slot - 1]
        else:
            current = response.get('currentProgramSceneName')
            position = names.index(current) if current in names else 0
            step = 1 if operation == 'next_scene' else -1
            target = names[(position + step) % len(names)]
        connection.call('SetCurrentProgramScene', {'sceneName': target})
        return
    if operation == 'save_replay':
        connection.call('SaveReplayBuffer'); return
    if operation == 'screenshot':
        current = connection.call('GetCurrentProgramScene').get('currentProgramSceneName')
        if not current:
            raise OBSError('Cena atual indisponível')
        folder = Path.home() / 'Pictures' / 'Vision02-OBS'
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = folder / ('obs-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.png')
        connection.call('SaveSourceScreenshot', {'sourceName': current,
                                                 'imageFormat': 'png', 'imageFilePath': str(target)})
        return


class OBSWorker:
    """Conexão/reconexão/polling e execução por fila; nunca toca no HID."""
    def __init__(self, *, interval: float = 3.0, connector=None, reader=read_config):
        if not 1.0 <= interval <= 60.0:
            raise ValueError('Intervalo OBS fora de 1–60 segundos')
        self.interval = interval
        self.connector = connector or OBSConnection.connect
        self.reader = reader
        self._stop = threading.Event()
        self._queue: queue.Queue[Action] = queue.Queue(maxsize=32)
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._rev = 0
        self._snapshot = OBSSnapshot()
        self._last_error = ''

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name='vision02-obs', daemon=True)
            self._thread.start()

    def submit(self, action: Action):
        if action.type != 'obs' or action.obs_operation not in OBS_OPERATIONS:
            raise OBSError('Ação não é OBS')
        if not self.latest()[1].connected:
            raise OBSError('OBS desconectado; ação não executada')
        try:
            self._queue.put_nowait(action)
        except queue.Full as exc:
            raise OBSError('Fila de comandos OBS cheia') from exc

    def latest(self):
        with self._lock:
            return self._rev, self._snapshot

    def last_error(self):
        with self._lock:
            return self._last_error

    def _update(self, snapshot, error=''):
        with self._lock:
            if self._snapshot != snapshot:
                self._snapshot = snapshot
                self._rev += 1
            self._last_error = error

    def _run(self):
        connection = None
        config = None
        deadline = 0.0
        retry_after = 0.0
        try:
            while not self._stop.is_set():
                if connection is None:
                    if time.monotonic() < retry_after:
                        self._stop.wait(0.25)
                        continue
                    try:
                        config = self.reader()
                        connection = self.connector(config)
                        deadline = 0
                        self._update(OBSSnapshot())
                    except (OSError, ValueError, KeyError, TypeError, OBSError) as exc:
                        self._update(OBSSnapshot(), str(exc))
                        retry_after = time.monotonic() + 3.0
                        self._stop.wait(0.25)
                        continue
                try:
                    pending = None
                    try:
                        pending = self._queue.get_nowait()
                    except queue.Empty:
                        pass
                    if pending is not None:
                        try:
                            perform_action(connection, pending, self.latest()[1], config)
                            deadline = 0
                        finally:
                            self._queue.task_done()
                    if time.monotonic() >= deadline:
                        self._update(collect_snapshot(connection, config))
                        deadline = time.monotonic() + self.interval
                    self._stop.wait(0.1)
                except (OSError, ValueError, KeyError, TypeError, OBSError) as exc:
                    logger.warning('OBS: %s', exc)
                    self._update(OBSSnapshot(), str(exc))
                    # Nunca reproduzir comandos antigos após uma reconexão.
                    while True:
                        try:
                            self._queue.get_nowait()
                            self._queue.task_done()
                        except queue.Empty:
                            break
                    connection.close()
                    connection = None
                    retry_after = time.monotonic() + 3.0
        finally:
            if connection is not None:
                connection.close()

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)


def obs_mapping(profile) -> dict[int, Action]:
    return {k: cfg.action for k, cfg in profile.keys.items()
            if cfg.action.type == 'obs' and cfg.appearance is None}


def _font(size=14):
    try:
        return ImageFont.truetype('DejaVuSans-Bold.ttf', size)
    except OSError:
        return ImageFont.load_default()


def resolved_scene(action: Action, snapshot: OBSSnapshot) -> str | None:
    """Resolve um slot legado contra o snapshot OBS; nomes não dependem da ordem."""
    if action.obs_operation == 'scene_name':
        return action.obs_scene if action.obs_scene in snapshot.scenes else None
    if action.obs_operation == 'scene_slot':
        slot = action.obs_slot
        return snapshot.scenes[slot - 1] if isinstance(slot, int) and 1 <= slot <= len(snapshot.scenes) else None
    return None


def scene_claims(mapping: dict[int, Action], snapshot: OBSSnapshot) -> set[int]:
    """Uma única tecla representa cada cena: prioriza associação por nome.

    Um perfil legado pode conter slot e nome resolvendo para a mesma cena.
    A duplicidade não deverá acender duas teclas como ATIVA.
    """
    grouped: dict[str, list[tuple[int, Action]]] = {}
    for key, action in mapping.items():
        scene = resolved_scene(action, snapshot)
        if scene is not None:
            grouped.setdefault(scene, []).append((key, action))
    claims = set()
    for members in grouped.values():
        key, _ = min(members, key=lambda item: (item[1].obs_operation != 'scene_name', item[0]))
        claims.add(key)
    return claims


def scene_render_queue(mapping: dict[int, Action], snapshot: OBSSnapshot) -> list[tuple[int, Image.Image]]:
    """Envia a desativação das cenas anteriores ANTES de ativar a cena atual."""
    claims = scene_claims(mapping, snapshot)
    updates = []
    for key, action in mapping.items():
        scene = resolved_scene(action, snapshot)
        duplicate = scene is not None and key not in claims
        active = (snapshot.connected and key in claims and scene == snapshot.scene)
        updates.append((active, key, obs_image(action, snapshot, duplicate=duplicate)))
    updates.sort(key=lambda item: (item[0], item[1]))
    return [(key, image) for _, key, image in updates]


def _scene_title(scene: str | None) -> str:
    if not scene:
        return 'CENA ?'
    # O nome configurado é mais estável e útil que CENA 1/2/3.
    title = scene.strip()
    while len(title) > 1 and ImageDraw.Draw(Image.new('RGB', (1, 1))).textbbox(
        (0, 0), title, font=_font(12))[2] > 86:
        title = title[:-2] + '…'
    return title


def obs_image(action: Action, snapshot: OBSSnapshot, *, duplicate: bool = False) -> Image.Image:
    op = action.obs_operation
    labels = {
        'toggle_record': ('REC', snapshot.recording, 'GRAVANDO', 'PARADO'),
        'toggle_pause': ('PAUSA', snapshot.paused, 'PAUSADO', 'GRAVANDO'),
        'toggle_stream': ('LIVE', snapshot.streaming, 'AO VIVO', 'OFFLINE'),
        'toggle_mic': ('MIC', None if snapshot.mic_muted is None else not snapshot.mic_muted, 'ATIVO', 'MUDO'),
        'toggle_desktop': ('AUDIO', None if snapshot.desktop_muted is None else not snapshot.desktop_muted, 'ATIVO', 'MUDO'),
        'toggle_virtualcam': ('CAM VIRT', snapshot.virtualcam, 'ATIVA', 'OFFLINE'),
        'save_replay': ('REPLAY', snapshot.replay, 'ATIVO', 'PARADO'),
        'refresh': ('OBS', snapshot.connected, 'CONECTADO', 'OFFLINE'),
    }
    if op in ('scene_slot', 'scene_name'):
        scene = resolved_scene(action, snapshot)
        title = _scene_title(scene or action.obs_scene or f'CENA {action.obs_slot or "?"}')
        active = snapshot.scene == scene if scene is not None else None
        yes, no = 'ATIVA', 'INATIVA'
    elif op in labels:
        title, active, yes, no = labels[op]
        if op in ('toggle_mic', 'toggle_desktop') and action.obs_source:
            muted = dict(snapshot.input_mutes).get(action.obs_source)
            active = (not muted) if isinstance(muted, bool) else None
            title = _scene_title(action.obs_source)
        if op == 'toggle_pause' and snapshot.recording is False:
            active = None
    else:
        title, active, yes, no = ({'next_scene': ('PROX CENA',None,'',''),
                                  'previous_scene': ('ANT CENA',None,'',''),
                                  'screenshot': ('CAPTURA',None,'','')}[op])
    if not snapshot.connected:
        text, color = 'OFFLINE', (237, 155, 98)
    elif duplicate:
        text, color = 'DUPLICADA', (242, 174, 103)
    elif active is None:
        text, color = 'N/D' if op in labels or op in ('scene_slot', 'scene_name') else 'PRONTO', (160, 173, 195)
    else:
        text, color = (yes, (82, 220, 169)) if active else (no, (242, 174, 103))
    result = Image.new('RGB', (100, 100), (8, 12, 22))
    draw = ImageDraw.Draw(result)
    draw.rounded_rectangle((2, 2, 97, 97), radius=10, outline=(43, 66, 93), width=2)
    for yy, value, font, ink in [(15, title, _font(12 if op in ('scene_name', 'scene_slot') else 14), (164, 195, 228)), (49, text, _font(11 if len(text)>8 else 14), color)]:
        box = draw.textbbox((0, 0), value, font=font)
        draw.text(((100 - (box[2]-box[0]))/2-box[0], yy-box[1]), value, font=font, fill=ink)
    draw.rounded_rectangle((22, 83, 78, 88), radius=2, fill=color)
    return result
