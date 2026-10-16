"""Preferências locais da divisão de painéis da interface Vision 02 Studio.

Independente de GTK, USB/HID, credenciais e YAML dos perfis.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

DEFAULT_SIDEBAR_WIDTH = 265
MIN_SIDEBAR_WIDTH = 230
MAX_SIDEBAR_WIDTH = 480


def normalize_sidebar_width(width: object) -> int:
    """Aceita somente inteiros e limita larguras excessivas."""
    if isinstance(width, bool) or not isinstance(width, int):
        return DEFAULT_SIDEBAR_WIDTH
    return max(MIN_SIDEBAR_WIDTH, min(width, MAX_SIDEBAR_WIDTH))


def ui_settings_path() -> Path:
    base = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    if not base.is_absolute():
        base = Path.home() / '.config'
    return base / 'vision02' / 'studio-ui.json'


def load_sidebar_width() -> int:
    path = ui_settings_path()
    if path.is_symlink():
        return DEFAULT_SIDEBAR_WIDTH
    try:
        settings = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(settings, dict):
            return DEFAULT_SIDEBAR_WIDTH
        return normalize_sidebar_width(settings.get('sidebar_width'))
    except (FileNotFoundError, OSError, ValueError, UnicodeError):
        return DEFAULT_SIDEBAR_WIDTH


def save_sidebar_width(width: int) -> Path:
    """Grava atomicamente, com permissões somente para o usuário."""
    path = ui_settings_path()
    if path.is_symlink():
        raise ValueError('Arquivo de preferências não pode ser link simbólico')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    content = (json.dumps({'sidebar_width': normalize_sidebar_width(width)},
                          ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    fd, name = tempfile.mkstemp(prefix='.studio-ui-', dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink():
            raise ValueError('Arquivo de preferências foi alterado durante gravação')
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path
