"""Layout físico da grade e tamanho inicial da janela (sem dependências GTK)."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

DECK_KEY_WIDTH = 106
DECK_KEY_HEIGHT = 116
DECK_ICON_SIZE = 86
DECK_COLUMN_SPACING = 11
DECK_ROW_SPACING = 11

def deck_dimensions() -> tuple[int, int]:
    """Dimensão reservada para as 15 teclas (sem moldura externa)."""
    return (5 * DECK_KEY_WIDTH + 4 * DECK_COLUMN_SPACING,
            3 * DECK_KEY_HEIGHT + 2 * DECK_ROW_SPACING)

def deck_key_position(ident: int) -> tuple[int, int]:
    """Posicionamento 5x3 sem depender da alocacao extra do GTK/Paned."""
    if isinstance(ident, bool) or not isinstance(ident, int) or not 1 <= ident <= 15:
        raise ValueError('Tecla deve estar entre 1 e 15')
    index = ident - 1
    return ((index % 5) * (DECK_KEY_WIDTH + DECK_COLUMN_SPACING),
            (index // 5) * (DECK_KEY_HEIGHT + DECK_ROW_SPACING))


def recommended_window_size(monitor_width: int | None,
                            monitor_height: int | None) -> tuple[int, int]:
    """Ocupa espaço útil sem ultrapassar monitores menores ou a área do dock.

    O compositor controla a posição da janela em Wayland. Não tentamos
    centralizar a janela usando API obsoleta.
    """
    if not isinstance(monitor_width, int) or isinstance(monitor_width, bool) or monitor_width < 640:
        monitor_width = 1600
    if not isinstance(monitor_height, int) or isinstance(monitor_height, bool) or monitor_height < 480:
        monitor_height = 1000
    width = max(640, min(1740, int(monitor_width * .90)))
    height = max(480, min(960, int(monitor_height * .84)))
    return width, height


def window_size_path() -> Path:
    root = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    if not root.is_absolute():
        root = Path.home() / '.config'
    return root / 'vision02' / 'studio-window.json'


def load_window_size(default_width: int, default_height: int) -> tuple[int, int]:
    """Restaura a última geometria sem abrir maior que a área disponível."""
    path = window_size_path()
    if path.is_symlink():
        return default_width, default_height
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        width, height = data['width'], data['height']
        if any(isinstance(value, bool) or not isinstance(value, int)
               for value in (width, height)):
            return default_width, default_height
        if width < 960 or height < 600:
            return default_width, default_height
        return min(width, default_width), min(height, default_height)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        return default_width, default_height


def save_window_size(width: int, height: int) -> Path | None:
    """Persiste a geometria do usuário por escrita atômica (0600)."""
    if any(isinstance(v, bool) or not isinstance(v, int)
           for v in (width, height)) or width < 640 or height < 480:
        return None
    path = window_size_path()
    if path.is_symlink():
        raise ValueError('Preferências de janela não podem ser link simbólico')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix='.studio-window-', dir=path.parent)
    temporary = Path(temp)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump({'width': width, 'height': height}, stream)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink():
            raise ValueError('Preferências de janela foram substituídas')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
