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
    obs_operation: str | None = None
    obs_slot: int | None = None
    obs_source: str | None = None
    obs_scene: str | None = None


@dataclass(frozen=True)
class KeyAppearance:
    """Aparência opcional; ausente mantém a renderização legada."""
    background: str = "#080C16"
    text: str | None = None
    font_family: str = "sans"
    font_size: int = 18
    font_weight: str = "bold"
    text_color: str = "#F5F7FA"
    horizontal: str = "center"
    vertical: str = "center"
    offset_x: int = 0
    offset_y: int = 0
    image_fit: str = "cover"
    show_text: bool = True


@dataclass(frozen=True)
class KeyConfig:
    key_id: int
    label: str
    action: Action
    image: Path | None = None
    appearance: KeyAppearance | None = None


@dataclass(frozen=True)
class Profile:
    name: str
    version: int = 1
    keys: dict[int, KeyConfig] = field(default_factory=dict)
    source: Path | None = None
