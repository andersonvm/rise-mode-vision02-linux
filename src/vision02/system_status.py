"""Estados operacionais Linux para os LCDs da Vision 02.

Consulta serviços e sysfs sem privilégio; esta unidade NUNCA toca USB/HID.
As ações das teclas continuam pertencendo aos perfis do usuário.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import shutil
import subprocess
import threading

from PIL import Image, ImageDraw, ImageFont


STATUS_INTERVAL = 3.0
STATUS_LABELS = {
    'MUDO': 'audio', 'AUDIO MUDO': 'audio', 'ÁUDIO MUDO': 'audio',
    'MIC MUDO': 'microphone', 'MICROFONE MUDO': 'microphone',
    'WIFI': 'wifi', 'WI-FI': 'wifi',
    'BLUETOOTH': 'bluetooth', 'BT': 'bluetooth',
}


@dataclass(frozen=True)
class StatusSnapshot:
    """None corresponde a estado indisponível, e não a desativado."""
    audio_muted: bool | None = None
    microphone_muted: bool | None = None
    wifi: str | None = None  # connected, disconnected, disabled
    bluetooth_enabled: bool | None = None


def parse_mute(text: str) -> bool | None:
    """Lê saída de wpctl ou pactl, sem confundir falha com MUDO."""
    text = text.strip().lower()
    if not text:
        return None
    if re.search(r'\[muted\]', text):
        return True
    if re.search(r'\b(?:mute|muted):\s*(?:yes|true|1)\b', text):
        return True
    if re.search(r'\b(?:mute|muted):\s*(?:no|false|0)\b', text):
        return False
    if re.search(r'\bvolume:\s*\d+(?:\.\d+)?\b', text):
        return False
    return None


def parse_wifi(radio: str, devices: str) -> str | None:
    """Diferencia rádio desligado de rádio ligado sem associação."""
    state = radio.strip().lower()
    if state in ('disabled', 'desativado'):
        return 'disabled'
    if state not in ('enabled', 'ativado'):
        return None
    for line in devices.splitlines():
        # Saída nmcli -t -f TYPE,STATE device status com locale=C.
        parts = line.strip().lower().split(':', 1)
        if len(parts) != 2 or parts[0] not in ('wifi', '802-11-wireless'):
            continue
        if parts[1] in ('connected', 'connecting') or parts[1].startswith('connected '):
            return 'connected'
    return 'disconnected'


def bluetooth_state(rfkill: Path) -> bool | None:
    """Obtém estado de rádio bluetooth via sysfs, sem ativá-lo."""
    enabled: list[bool] = []
    for radio in sorted(rfkill.glob('rfkill[0-9]*')):
        try:
            if (radio / 'type').read_text(encoding='ascii').strip().lower() != 'bluetooth':
                continue
            soft = (radio / 'soft').read_text(encoding='ascii').strip()
            hard = (radio / 'hard').read_text(encoding='ascii').strip()
            if soft not in ('0', '1') or hard not in ('0', '1'):
                continue
            enabled.append(soft == '0' and hard == '0')
        except (OSError, UnicodeError):
            continue
    return any(enabled) if enabled else None


class LinuxStatusSampler:
    """Leitura não invasiva de áudio, microfone, Wi-Fi e Bluetooth."""

    def __init__(self, *, rfkill: Path = Path('/sys/class/rfkill')):
        self.rfkill = rfkill

    @staticmethod
    def _command(argv: list[str]) -> str | None:
        if shutil.which(argv[0]) is None:
            return None
        try:
            completed = subprocess.run(
                argv, text=True, capture_output=True, check=False, timeout=1.0,
                env={**os.environ, 'LC_ALL': 'C', 'LANG': 'C'},
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.strip()

    def _mute(self, target: str, pactl_target: str) -> bool | None:
        value = self._command(['wpctl', 'get-volume', target])
        state = parse_mute(value) if value is not None else None
        if state is None:
            value = self._command(['pactl', f'get-{pactl_target}-mute',
                                   '@DEFAULT_SINK@' if pactl_target == 'sink' else '@DEFAULT_SOURCE@'])
            state = parse_mute(value) if value is not None else None
        return state

    def collect(self) -> StatusSnapshot:
        audio = self._mute('@DEFAULT_AUDIO_SINK@', 'sink')
        microphone = self._mute('@DEFAULT_AUDIO_SOURCE@', 'source')
        radio = self._command(['nmcli', 'radio', 'wifi'])
        # Se o rádio está desligado, não consulta dispositivos.
        devices = self._command(['nmcli', '-t', '-f', 'TYPE,STATE', 'device', 'status']) if (
            radio is not None and radio.strip().lower() in ('enabled', 'ativado')
        ) else ''
        wifi = parse_wifi(radio, devices or '') if radio is not None else None
        return StatusSnapshot(
            audio_muted=audio, microphone_muted=microphone,
            wifi=wifi, bluetooth_enabled=bluetooth_state(self.rfkill),
        )


class StatusWorker:
    """Polling independente do USB, com snapshot imutável e revisão."""

    def __init__(self, sampler: LinuxStatusSampler | None = None, *, interval: float = STATUS_INTERVAL):
        if not 1.0 <= interval <= 60.0:
            raise ValueError('intervalo de estado fora de 1–60 segundos')
        self.sampler = sampler if sampler is not None else LinuxStatusSampler()
        self.interval = interval
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._revision = 0
        self._snapshot: StatusSnapshot | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name='vision02-status', daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                current = self.sampler.collect()
            except Exception:
                current = StatusSnapshot()
            with self._lock:
                if self._snapshot != current:
                    self._snapshot = current
                    self._revision += 1
            if self._stop.wait(self.interval):
                break

    def latest(self) -> tuple[int, StatusSnapshot | None]:
        with self._lock:
            return self._revision, self._snapshot

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


def status_mapping(profile) -> dict[int, str]:
    """Apenas teclas de controle no perfil Sistema, preservando aparência customizada."""
    if profile.name != 'Sistema':
        return {}
    mapping: dict[int, str] = {}
    for index in range(6, 15):
        key = profile.keys.get(index)
        if key is None or key.appearance is not None:
            continue
        category = STATUS_LABELS.get(' '.join(key.label.upper().split()))
        if category:
            mapping[index] = category
    return mapping


def _font(size: int, bold: bool = True):
    try:
        return ImageFont.truetype('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf', size)
    except OSError:
        return ImageFont.load_default()


def _center(draw, y: int, text: str, font, color) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((100 - (box[2] - box[0])) / 2 - box[0], y - box[1]),
              text, font=font, fill=color)


def status_image(category: str, snapshot: StatusSnapshot) -> Image.Image:
    """Imagem RGB 100×100 indicando estado real, nunca executa ações."""
    if category not in ('audio', 'microphone', 'wifi', 'bluetooth'):
        raise ValueError('Indicador desconhecido')
    if category == 'audio':
        title, state = 'AUDIO', ('MUDO' if snapshot.audio_muted else 'ATIVO') if (
            snapshot.audio_muted is not None) else 'N/D'
        on = snapshot.audio_muted is False
        known = snapshot.audio_muted is not None
    elif category == 'microphone':
        title, state = 'MIC', ('MUDO' if snapshot.microphone_muted else 'ATIVO') if (
            snapshot.microphone_muted is not None) else 'N/D'
        on = snapshot.microphone_muted is False
        known = snapshot.microphone_muted is not None
    elif category == 'wifi':
        title = 'WI-FI'
        state = {'connected': 'CONECTADO', 'disconnected': 'SEM REDE',
                 'disabled': 'DESLIGADO'}.get(snapshot.wifi, 'N/D')
        on = snapshot.wifi == 'connected'
        known = snapshot.wifi is not None
    else:
        title, state = 'BT', ('LIGADO' if snapshot.bluetooth_enabled else 'DESLIGADO') if (
            snapshot.bluetooth_enabled is not None) else 'N/D'
        on = snapshot.bluetooth_enabled is True
        known = snapshot.bluetooth_enabled is not None
    fg = ((72, 215, 172) if on else (243, 171, 104)) if known else (155, 166, 185)
    image = Image.new('RGB', (100, 100), (8, 12, 22))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, 97, 97), radius=10, outline=(43, 66, 93), width=2)
    _center(draw, 12, title, _font(15), (166, 194, 228))
    size = 12 if len(state) > 8 else 16
    _center(draw, 46, state, _font(size), fg)
    draw.rounded_rectangle((21, 81, 78, 87), radius=3, fill=fg)
    return image
