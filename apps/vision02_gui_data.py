"""Metadados e prévias dos perfis para a GUI, sem abrir USB/HID.

Executado no Python do projeto (venv), pois depende de Pillow/PyYAML.
A janela GTK é executada separadamente pelo Python do sistema.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from PIL import Image

# Executar também a partir do script, sem exigir instalação editável.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vision02.profiles import load_profile
from vision02.user_profiles import default_profile_paths
from vision02.protocol import physical_key_to_display_id
from vision02.rendering import render_profile


DEFAULT_PROFILES = (
    "examples/profiles/desenvolvimento-switch.yaml",
    "examples/profiles/observabilidade.yaml",
)


def cache_root() -> Path:
    value = os.environ.get("XDG_CACHE_HOME")
    root = Path(value) if value else Path.home() / ".cache"
    return root / "vision02" / "gui"


def build_metadata(
    project: Path,
    profile_paths: list[str | Path] | tuple[str | Path, ...] = DEFAULT_PROFILES,
    *,
    cache: Path | None = None,
) -> dict:
    project = Path(project).resolve()
    output = Path(cache) if cache is not None else cache_root()
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    profiles = {}

    for filename in profile_paths:
        profile_path = Path(filename)
        if not profile_path.is_absolute():
            profile_path = project / profile_path
        profile = load_profile(profile_path)
        if profile.name in profiles:
            raise ValueError(f"Perfis com nomes duplicados: {profile.name}")

        digest = hashlib.sha256(str(profile.source).encode()).hexdigest()[:16]
        images = render_profile(profile)
        keys = []
        for key_id in range(1, 16):
            config = profile.keys.get(key_id)
            source = images[key_id]
            dest = output / f"{digest}-{key_id:02d}.png"
            if isinstance(source, Path):
                with Image.open(source) as pil:
                    preview = pil.convert("RGB").resize((100, 100))
            else:
                preview = source.convert("RGB")
                if preview.size != (100, 100):
                    preview = preview.resize((100, 100))
            preview.save(dest, format="PNG")
            keys.append(
                {
                    "id": key_id,
                    "display_id": physical_key_to_display_id(key_id),
                    "label": config.label if config else "",
                    "action": config.action.type if config else "",
                    "image": str(dest),
                }
            )
        profiles[profile.name] = {
            "source": str(profile.source),
            "keys": keys,
        }
    return {"profiles": profiles}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Prepara prévias GTK sem acessar USB")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--profile", action="append", default=None)
    parser.add_argument("--cache", type=Path)
    args = parser.parse_args(argv)
    paths = args.profile if args.profile is not None else default_profile_paths(args.project)
    result = build_metadata(args.project, paths, cache=args.cache)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
