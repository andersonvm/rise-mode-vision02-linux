"""Seleção dos perfis pessoais da Vision 02, sem acessar HID."""
from __future__ import annotations
import os
from pathlib import Path

EXAMPLES = (
    "examples/profiles/desenvolvimento-switch.yaml",
    "examples/profiles/observabilidade.yaml",
)
USER_NAMES = ("desenvolvimento.yaml", "observabilidade.yaml")


def config_profile_dir() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(raw).expanduser() if raw else Path.home() / ".config"
    return base / "vision02" / "profiles"


def default_profile_paths(project: Path) -> tuple[Path, Path]:
    """Prefere os dois perfis pessoais; rejeita migração incompleta."""
    paths = tuple(config_profile_dir() / name for name in USER_NAMES)
    present = [p.is_file() for p in paths]
    if all(present):
        return paths
    if any(present):
        raise ValueError(
            "Configuração Vision 02 incompleta: são necessários os dois YAML "
            f"em {config_profile_dir()}"
        )
    return tuple(Path(project) / rel for rel in EXAMPLES)
