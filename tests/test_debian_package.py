"""Checks that the distributed .deb bundles the Studio and does not contain user secrets."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'packaging/debian/build_deb.py'


def _builder():
    spec = importlib.util.spec_from_file_location('vision02_debian_builder', SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rejects_invalid_package_version(tmp_path):
    with pytest.raises(ValueError, match='Invalid Debian version'):
        _builder().build(ROOT, tmp_path, '../../1.0.0-1')


@pytest.mark.skipif(shutil.which('dpkg-deb') is None, reason='Needs Debian dpkg-deb')
def test_deb_bundles_full_app_without_user_state(tmp_path):
    deb = _builder().build(ROOT, tmp_path / 'out', '1.0.0~test1-1')
    assert deb.name == 'vision02-studio-desktop_1.0.0~test1-1_all.deb'
    assert deb.stat().st_size > 10_000
    fields = subprocess.check_output(['dpkg-deb', '-f', str(deb)], text=True)
    assert 'Package: vision02-studio-desktop' in fields
    assert 'Version: 1.0.0~test1-1' in fields
    assert 'python3-pil' in fields and 'python3-dbus-next' in fields

    extracted = tmp_path / 'extracted'
    subprocess.run(['dpkg-deb', '-x', str(deb), str(extracted)], check=True)
    launcher = extracted / 'usr/bin/vision02-studio-launch'
    assert launcher.stat().st_mode & 0o111
    assert 'PYTHONPATH=' in launcher.read_text()
    assert (extracted / 'opt/vision02-studio/apps/vision02_studio.py').is_file()
    assert (extracted / 'opt/vision02-studio/src/vision02/studio_profile_menu_v15.py').is_file()
    assert (extracted / 'opt/vision02-studio/examples/profiles/openboard.yaml').is_file()
    assert (extracted / 'opt/vision02-studio/.venv/bin/python').is_symlink()
    assert (extracted / 'usr/share/applications/io.github.vision02.Studio.desktop').is_file()
    assert not (extracted / 'opt/vision02-studio/.git').exists()
    assert not (extracted / 'opt/vision02-studio/.venv/lib').exists()
    assert not (extracted / 'opt/vision02-studio/.config').exists()
