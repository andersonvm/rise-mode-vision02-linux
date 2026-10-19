#!/usr/bin/env python3
"""Build a self-contained-in-source Debian package using system Python dependencies.

This includes the application tree, not just a .desktop launcher for a checkout.
No post-install hooks, service activation, or changes to a user's profiles.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

PACKAGE = 'vision02-studio-desktop'
DEST = Path('opt/vision02-studio')
BIN = Path('usr/bin')
APPLICATIONS = Path('usr/share/applications')
ICONS = Path('usr/share/icons/hicolor/scalable/apps')
REQUIRED = ('apps/vision02_studio.py', 'apps/vision02_studio_backend.py',
            'src/vision02/__init__.py', 'scripts/vision02-studio', 'pyproject.toml')
DEPENDENCIES = (
    'python3 (>= 3.10)', 'python3-gi', 'python3-gi-cairo',
    'gir1.2-gtk-4.0', 'gir1.2-adw-1', 'python3-pil', 'python3-yaml',
    'python3-dbus-next',
)


def build(source: Path, output: Path, version: str) -> Path:
    source = source.resolve()
    output = output.resolve()
    if not re.fullmatch(r'[0-9][0-9A-Za-z.+~]*-[0-9A-Za-z.+~]+', version):
        raise ValueError(f'Invalid Debian version: {version!r}')
    for item in REQUIRED:
        if not (source / item).is_file():
            raise FileNotFoundError(f'Required project file not found: {source / item}')
    image = source / 'packaging/debian/io.github.vision02.Studio.svg'
    if not image.is_file():
        raise FileNotFoundError(image)
    output.mkdir(parents=True, exist_ok=True)
    deb = output / f'{PACKAGE}_{version}_all.deb'

    with tempfile.TemporaryDirectory(prefix='vision02-deb-') as tmp:
        stage = Path(tmp) / 'root'
        stage.mkdir()
        root = stage / DEST
        root.mkdir(parents=True)
        skip = shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache', '.venv',
                                      '.mypy_cache', '.ruff_cache', '.git', '*.egg-info')
        for folder in ('apps', 'src', 'scripts', 'examples', 'docs'):
            if (source / folder).is_dir():
                shutil.copytree(source / folder, root / folder, ignore=skip)
        for file in ('README.md', 'CHANGELOG.md', 'pyproject.toml', 'LICENSE'):
            if (source / file).is_file():
                shutil.copy2(source / file, root / file)
        # Existing apps expect ROOT/.venv/bin/python for YAML/Pillow backend.
        # In the DEB the equivalent interpreter is the Ubuntu system Python,
        # with all dependencies declared in DEBIAN/control.
        python = root / '.venv/bin/python'
        python.parent.mkdir(parents=True)
        python.symlink_to('/usr/bin/python3')

        bin_dir = stage / BIN
        bin_dir.mkdir(parents=True)
        launchers = {
            'vision02-studio-launch': 'exec /usr/bin/python3 /opt/vision02-studio/apps/vision02_studio.py "$@"',
            'vision02-studio-control': 'exec /usr/bin/python3 -m vision02.cli "$@"',
        }
        for name, command in launchers.items():
            exe = bin_dir / name
            exe.write_text('#!/bin/sh\nset -eu\n'
                'export PYTHONPATH="/opt/vision02-studio/src${PYTHONPATH:+:$PYTHONPATH}"\n'
                + command + '\n', encoding='utf-8')
            exe.chmod(0o755)

        app_dir = stage / APPLICATIONS
        app_dir.mkdir(parents=True)
        (app_dir / 'io.github.vision02.Studio.desktop').write_text(
            '[Desktop Entry]\nType=Application\n'
            'Name=Vision 02 Studio\n'
            'Comment=Configure as 15 teclas LCD do Rise Mode Vision 02\n'
            'Exec=vision02-studio-launch\n'
            'Icon=io.github.vision02.Studio\n'
            'Terminal=false\nCategories=Utility;Settings;\n'
            'StartupNotify=true\n'
            'StartupWMClass=io.github.vision02.Studio\n',
            encoding='utf-8',
        )
        # Maintain compatibility with launchers pinned before desktop ID was fixed.
        (app_dir / 'vision02-studio.desktop').write_text(
            '[Desktop Entry]\nType=Application\nName=Vision 02 Studio (legacy)\n'
            'Exec=vision02-studio-launch\nIcon=io.github.vision02.Studio\n'
            'Terminal=false\nCategories=Utility;Settings;\nNoDisplay=true\n',
            encoding='utf-8',
        )
        icon_dir = stage / ICONS
        icon_dir.mkdir(parents=True)
        shutil.copy2(image, icon_dir / image.name)

        control_dir = stage / 'DEBIAN'
        control_dir.mkdir()
        (control_dir / 'control').write_text(
            f'Package: {PACKAGE}\n'
            f'Version: {version}\n'
            'Architecture: all\n'
            'Maintainer: Rise Mode Vision 02 Linux Community <noreply@users.noreply.github.com>\n'
            'Section: utils\nPriority: optional\n'
            f'Depends: {", ".join(DEPENDENCIES)}\n'
            'Recommends: xdotool\n'
            'Homepage: https://github.com/andersonvm/rise-mode-vision02-linux\n'
            'Description: Vision 02 Studio GTK4 and USB/HID controller for Linux\n'
            ' Includes the Studio app, Python runtime sources, profiles, icons,\n'
            ' editor tools and CLI. System Python dependencies are installed\n'
            ' through apt. Does not start or modify a user systemd service,\n'
            ' profiles or OBS credentials during installation.\n',
            encoding='utf-8',
        )
        subprocess.run(['dpkg-deb', '--build', '--root-owner-group', str(stage), str(deb)],
                       check=True)
    return deb


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, default=Path('dist'))
    parser.add_argument('--version', default='15.0.0',
                        help='Debian upstream version, for example 15.0.0 or 15.0.0~ci23')
    parser.add_argument('--revision', default='1')
    args = parser.parse_args()
    deb = build(args.source, args.output, f'{args.version}-{args.revision}')
    print(f'Created: {deb} ({deb.stat().st_size} bytes)')


if __name__ == '__main__':
    main()
