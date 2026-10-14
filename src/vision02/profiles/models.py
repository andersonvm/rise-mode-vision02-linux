"""Modelos imutáveis dos perfis da Vision 02."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Action:
    type: str
    argv: tuple[str, ...] = ()
    url: str | None = None
    target: str | None = None
    script_path: Path | None = None
    interpreter: str | None = None
    keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class KeyConfig:
    key_id: int
    label: str
    action: Action
    image: Path | None = None


@dataclass(frozen=True)
class Profile:
    name: str
    version: int = 1
    keys: dict[int, KeyConfig] = field(default_factory=dict)
    source: Path | None = None
