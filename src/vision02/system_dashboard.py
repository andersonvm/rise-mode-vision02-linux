"""Dashboard Linux para cinco LCDs do perfil Sistema.

Leitura de métricas em thread própria; transmissão HID SOMENTE no loop principal.
Não altera perfis pessoais nem o protocolo USB/HID.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections import deque
import re
import shutil
import subprocess
import threading
import time

from PIL import Image, ImageDraw, ImageFont

from .protocol import physical_key_to_display_id
from .system_status import StatusWorker, status_mapping, status_image
from .obs_control import OBSWorker, obs_mapping, obs_image


METRIC_LABELS = {
    1: {"CPU": "cpu"},
    2: {"RAM": "ram"},
    3: {"GPU": "gpu"},
    4: {"DISCO": "disk", "DISK": "disk", "TEMP": "temp", "TEMPERATURA": "temp"},
    5: {"REDE": "network", "NET": "network"},
}
DEFAULT_INTERVAL = 8.0


@dataclass(frozen=True)
class Snapshot:
    cpu: float | None = None
    ram: float | None = None
    ram_gib: float | None = None
    gpu: float | None = None
    disk: float | None = None
    temp: float | None = None
    rx_bps: float | None = None
    tx_bps: float | None = None


def _read_cpu(path: Path) -> tuple[int, int]:
    first = path.read_text(encoding="ascii").splitlines()[0].split()
    if first[0] != 'cpu' or len(first) < 5:
        raise ValueError('Formato inesperado em /proc/stat')
    values = [int(number) for number in first[1:]]
    # iowait computado como idle; irq, softirq, steal, etc. no total.
    return sum(values), values[3] + (values[4] if len(values) > 4 else 0)


def cpu_percent(before: tuple[int, int] | None, after: tuple[int, int]) -> float | None:
    if before is None:
        return None
    total = after[0] - before[0]
    idle = after[1] - before[1]
    if total <= 0 or idle < 0:
        return None
    return max(0.0, min(100.0, (1 - idle / total) * 100.0))


def memory_usage(path: Path) -> tuple[float, float]:
    values: dict[str, int] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].endswith(':') and parts[1].isdigit():
            values[parts[0][:-1]] = int(parts[1])
    total = values.get('MemTotal', 0)
    available = values.get('MemAvailable', values.get('MemFree', 0))
    if total <= 0:
        raise ValueError('MemTotal não encontrado')
    used = max(0, total - min(available, total))
    return used / total * 100, used / (1024 * 1024)


def parse_network(data: str) -> tuple[int, int]:
    rx = tx = 0
    for line in data.splitlines():
        if ':' not in line:
            continue
        iface, counters = line.split(':', 1)
        iface = iface.strip()
        if (iface == 'lo' or iface.startswith(
            ('veth', 'docker', 'br-', 'virbr', 'vboxnet', 'tap', 'tun', 'wg', 'tailscale', 'podman')
        )):
            continue
        columns = counters.split()
        if len(columns) < 16:
            continue
        try:
            rx += int(columns[0])
            tx += int(columns[8])
        except ValueError:
            continue
    return rx, tx


def network_rates(before: tuple[float, int, int] | None,
                  after: tuple[float, int, int]) -> tuple[float | None, float | None]:
    if before is None:
        return None, None
    interval = after[0] - before[0]
    rx = after[1] - before[1]
    tx = after[2] - before[2]
    if interval <= 0 or rx < 0 or tx < 0:
        return None, None
    return rx / interval, tx / interval


def _temperature(hwmon: Path, thermal: Path) -> float | None:
    ranked: list[tuple[int, float]] = []
    for folder in hwmon.glob('hwmon[0-9]*'):
        try:
            chip = (folder / 'name').read_text(encoding='utf-8').strip().lower()
        except OSError:
            chip = ''
        if chip in ('coretemp', 'k10temp', 'zenpower'):
            rank = 0
        elif chip in ('acpitz', 'thinkpad', 'asus', 'asusec'):
            rank = 1
        else:
            rank = 3
        for sensor in folder.glob('temp[0-9]*_input'):
            try:
                value = int(sensor.read_text().strip()) / 1000
                if 5 <= value <= 115:
                    ranked.append((rank, value))
            except (OSError, ValueError):
                continue
    if ranked:
        rank = min(item[0] for item in ranked)
        # Prefere máximo entre sensores CPU do mesmo chip/nível.
        return max(value for r, value in ranked if r == rank)
    for zone in thermal.glob('thermal_zone[0-9]*'):
        try:
            value = int((zone / 'temp').read_text().strip()) / 1000
            if 5 <= value <= 115:
                return value
        except (OSError, ValueError):
            continue
    return None


def _gpu_utilization(drm: Path) -> float | None:
    for card in drm.glob('card[0-9]*'):
        busy = card / 'device' / 'gpu_busy_percent'
        try:
            value = float(busy.read_text().strip())
            if 0 <= value <= 100:
                return value
        except (OSError, ValueError):
            continue
    if shutil.which('nvidia-smi'):
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits'],
                check=False, capture_output=True, text=True, timeout=1.0,
            )
            if result.returncode == 0:
                match = re.search(r'\d+(?:\.\d+)?', result.stdout)
                if match:
                    value = float(match.group())
                    if 0 <= value <= 100:
                        return value
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
    return None


class LinuxSampler:
    """Leitor de /proc e /sys sem privilégios; acessado por uma única thread."""

    def __init__(self, proc: Path = Path('/proc'), sysfs: Path = Path('/sys'), disk_root: Path = Path('/')):
        self.proc = proc
        self.sysfs = sysfs
        self.disk_root = disk_root
        self._previous_cpu: tuple[int, int] | None = None
        self._previous_net: tuple[float, int, int] | None = None

    def collect(self) -> Snapshot:
        def optional(read):
            try:
                return read()
            except (OSError, ValueError, IndexError, ZeroDivisionError):
                return None
        values = optional(lambda: _read_cpu(self.proc / 'stat'))
        cpu = cpu_percent(self._previous_cpu, values) if values is not None else None
        if values is not None:
            self._previous_cpu = values
        mem = optional(lambda: memory_usage(self.proc / 'meminfo'))
        disk = optional(lambda: shutil.disk_usage(self.disk_root))
        net = optional(lambda: parse_network((self.proc / 'net/dev').read_text(encoding='ascii')))
        rates = (None, None)
        if net is not None:
            now = (time.monotonic(), net[0], net[1])
            rates = network_rates(self._previous_net, now)
            self._previous_net = now
        return Snapshot(
            cpu=cpu, ram=mem[0] if mem else None, ram_gib=mem[1] if mem else None,
            gpu=_gpu_utilization(self.sysfs / 'class/drm'),
            disk=(disk.used / disk.total * 100) if disk and disk.total else None,
            temp=_temperature(self.sysfs / 'class/hwmon', self.sysfs / 'class/thermal'),
            rx_bps=rates[0], tx_bps=rates[1],
        )


def _font(size: int, bold: bool = True):
    for name in (('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'),):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _text_center(draw: ImageDraw.ImageDraw, y: int, text: str, font, fill):
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((100 - (box[2] - box[0])) / 2 - box[0], y - box[1]), text, font=font, fill=fill)


def _rate(rate: float | None) -> str:
    if rate is None:
        return '--'
    for unit in ('B', 'K', 'M', 'G'):
        if rate < 1024 or unit == 'G':
            return f'{rate:.0f}{unit}' if unit == 'B' else f'{rate:.1f}{unit}'
        rate /= 1024
    return '--'


def metric_image(metric: str, data: Snapshot) -> Image.Image:
    """Composição RGB 100x100, sem depender da GUI; pronta para set_image()."""
    if metric not in ('cpu', 'ram', 'gpu', 'temp', 'disk', 'network'):
        raise ValueError('Métrica não suportada')
    picture = Image.new('RGB', (100, 100), (8, 12, 22))
    draw = ImageDraw.Draw(picture)
    draw.rounded_rectangle((2, 2, 97, 97), radius=10, outline=(43, 66, 93), width=2)
    headline = dict(cpu='CPU', ram='RAM', gpu='GPU', temp='TEMP', disk='DISCO', network='REDE')[metric]
    _text_center(draw, 9, headline, _font(14), (166, 194, 228))
    stat = getattr(data, metric) if metric != 'network' else None
    if metric == 'network':
        _text_center(draw, 35, '↓ ' + _rate(data.rx_bps) + '/s', _font(13), (105, 218, 215))
        _text_center(draw, 58, '↑ ' + _rate(data.tx_bps) + '/s', _font(13), (235, 183, 112))
        _text_center(draw, 84, 'RX / TX', _font(9, False), (136, 150, 167))
        return picture
    if metric == 'temp':
        main = f'{round(stat):d}°C' if stat is not None else 'N/D'
    else:
        main = f'{round(stat):d}%' if stat is not None else 'N/D'
    _text_center(draw, 32, main, _font(25), (236, 244, 252))
    if metric == 'cpu':
        aux = f'{round(data.temp):d}°C' if data.temp is not None else 'TEMP N/D'
    elif metric == 'ram':
        aux = f'{data.ram_gib:.1f} GiB' if data.ram_gib is not None else 'SEM DADOS'
    elif metric == 'gpu':
        aux = 'USO GPU' if stat is not None else 'GPU INDISP.'
    elif metric == 'disk':
        aux = 'RAIZ /'
    else:
        aux = 'SENSOR CPU'
    _text_center(draw, 69, aux, _font(10), (164, 177, 199))
    if metric != 'temp' and stat is not None:
        draw.rounded_rectangle((12, 85, 88, 92), radius=3, fill=(36, 49, 67))
        width = round(76 * max(0, min(100, stat)) / 100)
        if width:
            draw.rounded_rectangle((12, 85, 12 + width, 92), radius=3, fill=(0, 167, 223))
    return picture


class MetricsWorker:
    """Amostragem em background: não acessa o HID, não altera YAML."""

    def __init__(self, sampler: LinuxSampler | None = None, *, interval: float = DEFAULT_INTERVAL):
        if not 3 <= interval <= 60:
            raise ValueError('intervalo entre 3 e 60 segundos')
        self.sampler = sampler if sampler is not None else LinuxSampler()
        self.interval = interval
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._snapshot: Snapshot | None = None
        self._revision = 0
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name='vision02-metrics', daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                snapshot = self.sampler.collect()
            except Exception:
                # Se coleta opcional falhar, mostrar N/D, nunca parar a leitura HID.
                snapshot = Snapshot()
            with self._lock:
                self._snapshot = snapshot
                self._revision += 1
            if self._stop.wait(self.interval):
                break

    def latest(self) -> tuple[int, Snapshot | None]:
        with self._lock:
            return self._revision, self._snapshot

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


class Dashboard:
    """Só a thread HID chama tick(). Uma escrita por tick no máximo."""

    def __init__(
        self, worker: MetricsWorker, *, minimum_gap: float = 0.20,
        status_worker: StatusWorker | None = None,
        obs_worker: OBSWorker | None = None,
    ):
        if minimum_gap < 0.0:
            raise ValueError('minimum_gap negativo')
        self.worker = worker
        self.status_worker = status_worker
        self.obs_worker = obs_worker
        self.minimum_gap = minimum_gap
        self._active: str | None = None
        self._revision = -1
        self._waiting: deque[tuple[int, Image.Image]] = deque()
        self._status_waiting: deque[tuple[int, Image.Image]] = deque()
        self._status_revision = -1
        self._next_status = False
        self._obs_revision = -1
        self._obs_waiting: deque[tuple[int, Image.Image]] = deque()
        self._last_write = -float('inf')

    @staticmethod
    def mapping(profile) -> dict[int, str]:
        if profile.name != 'Sistema':
            return {}
        result = {}
        for index, choices in METRIC_LABELS.items():
            key = profile.keys.get(index)
            if (key is not None and key.appearance is None
                    and key.label.strip().upper() in choices):
                result[index] = choices[key.label.strip().upper()]
        return result

    def invalidate(self) -> None:
        """Chamar após switch/reload de perfis para reemitir apenas a grade ativa."""
        self._active = None
        self._revision = -1
        self._waiting.clear()
        self._status_revision = -1
        self._status_waiting.clear()
        self._next_status = False
        self._obs_revision = -1
        self._obs_waiting.clear()

    def tick(self, profile, device, *, now: float | None = None) -> bool:
        """No máximo UMA transmissão potencial por passagem e intervalo global.

        Enfileira métricas e estados separadamente; alterna filas para que
        atualizações de CPU/RAM não adiem áudio, microfone e rede.
        """
        now = time.monotonic() if now is None else now
        metrics = self.mapping(profile)
        status = status_mapping(profile) if self.status_worker is not None else {}
        obs = obs_mapping(profile) if self.obs_worker is not None else {}
        if not metrics and not status and not obs:
            self.invalidate()
            return False
        if profile.name != self._active:
            self.invalidate()
            self._active = profile.name

        if metrics:
            revision, values = self.worker.latest()
            if revision != self._revision and values is not None:
                self._revision = revision
                self._waiting = deque(
                    (key, metric_image(name, values)) for key, name in metrics.items()
                )

        if status and self.status_worker is not None:
            revision, snapshot = self.status_worker.latest()
            if revision != self._status_revision and snapshot is not None:
                self._status_revision = revision
                self._status_waiting = deque(
                    (key, status_image(category, snapshot))
                    for key, category in status.items()
                )

        if obs and self.obs_worker is not None:
            revision, snapshot = self.obs_worker.latest()
            if revision != self._obs_revision:
                self._obs_revision = revision
                self._obs_waiting = deque(
                    (key, obs_image(action, snapshot))
                    for key, action in obs.items()
                )

        if now - self._last_write < self.minimum_gap:
            return False
        if self._obs_waiting:
            key, image = self._obs_waiting.popleft()
        elif self._status_waiting and (self._next_status or not self._waiting):
            key, image = self._status_waiting.popleft()
            self._next_status = False
        elif self._waiting:
            key, image = self._waiting.popleft()
            self._next_status = True
        elif self._status_waiting:
            key, image = self._status_waiting.popleft()
            self._next_status = False
        else:
            return False
        # Único ponto de saída HID para ambas as categorias.
        device.set_image(physical_key_to_display_id(key), image, skip_unchanged=True)
        self._last_write = now
        return True
