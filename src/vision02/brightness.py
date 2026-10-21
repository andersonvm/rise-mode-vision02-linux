"""Preferência XDG do brilho global dos 15 LCDs (não altera perfis YAML)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

DEFAULT_BRIGHTNESS = 25


def validate_brightness(value: int) -> int:
    if type(value) is not int or not 0 <= value <= 100:
        raise ValueError("Brilho deve ser um inteiro entre 0 e 100")
    return value


def brightness_path() -> Path:
    base = Path(os.getenv("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "vision02" / "brightness.json"


def load_brightness() -> int:
    try:
        data = json.loads(brightness_path().read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {"brightness"}:
            return DEFAULT_BRIGHTNESS
        return validate_brightness(data["brightness"])
    except (FileNotFoundError, PermissionError, ValueError, TypeError, OSError):
        return DEFAULT_BRIGHTNESS


def save_brightness(value: int) -> None:
    value = validate_brightness(value)
    destination = brightness_path()
    directory = destination.parent
    if directory.is_symlink() or destination.is_symlink():
        raise ValueError("Configuração de brilho não pode utilizar links simbólicos")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix=".brightness-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            os.fchmod(out.fileno(), 0o600)
            json.dump({"brightness": value}, out)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, destination)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
