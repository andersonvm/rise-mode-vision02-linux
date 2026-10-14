"""Descoberta dinâmica de perfis pessoais; sem acessar USB/HID."""
from __future__ import annotations
import os
from pathlib import Path

EXAMPLES = (
    'examples/profiles/desenvolvimento-switch.yaml',
    'examples/profiles/observabilidade.yaml',
)


def config_profile_dir() -> Path:
    raw = os.environ.get('XDG_CONFIG_HOME', '')
    base = Path(raw).expanduser() if raw else Path.home() / '.config'
    return base / 'vision02' / 'profiles'


def default_profile_paths(project: Path) -> tuple[Path, ...]:
    """Retorna todos os YAML pessoais ou exemplos quando não há nenhum."""
    root = config_profile_dir()
    if root.exists():
        if root.is_symlink() or not root.is_dir():
            raise ValueError(f'Diretório de perfis inválido: {root}')
        files = tuple(sorted(root.glob('*.yaml')))
        if files:
            for path in files:
                if path.is_symlink() or not path.is_file():
                    raise ValueError(f'Perfil pessoal inválido: {path}')
            if len(files) > 64:
                raise ValueError('Limite de 64 perfis pessoais excedido')
            return files
    return tuple(Path(project) / rel for rel in EXAMPLES)
