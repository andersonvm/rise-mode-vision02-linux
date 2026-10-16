"""Preferência local da largura grade/propriedades do Vision 02 Studio.

Sem dependências GTK e independente de YAML pessoal ou serviço HID.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

DEFAULT_PANEL_WIDTH = 535
MIN_PANEL_WIDTH = 220
MAX_PANEL_WIDTH = 950


def normalize_panel_width(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_PANEL_WIDTH
    return max(MIN_PANEL_WIDTH, min(MAX_PANEL_WIDTH, value))


def panel_settings_path() -> Path:
    base = Path(os.environ.get('XDG_CONFIG_HOME') or (Path.home() / '.config'))
    if not base.is_absolute():
        base = Path.home() / '.config'
    return base / 'vision02' / 'studio-editor-layout.json'


def load_panel_width() -> int:
    path = panel_settings_path()
    if path.is_symlink():
        return DEFAULT_PANEL_WIDTH
    try:
        settings = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(settings, dict):
            return DEFAULT_PANEL_WIDTH
        return normalize_panel_width(settings.get('grid_width'))
    except (OSError, UnicodeError, ValueError):
        return DEFAULT_PANEL_WIDTH


def save_panel_width(width: int) -> Path:
    path = panel_settings_path()
    if path.is_symlink():
        raise ValueError('Preferências de painel não podem ser link simbólico')
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    content = (json.dumps({'grid_width': normalize_panel_width(width)},
                          ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    fd, tmp_name = tempfile.mkstemp(prefix='.studio-editor-', dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, 'wb') as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        if path.is_symlink():
            raise ValueError('Preferências alteradas durante a gravação')
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path
