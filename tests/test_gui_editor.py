"""Testes sem USB/HID para o editor de perfis GTK."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "vision02_editor_backend", ROOT / "apps" / "vision02_editor_backend.py"
)
assert SPEC and SPEC.loader
editor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(editor)


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "primeiro.yaml").write_text(
        "version: 1\nname: Desenvolvimento\nkeys:\n  1:\n    label: Terminal\n    action:\n      type: command\n      argv: [gnome-terminal]\n  15:\n    label: Observar\n    action:\n      type: profile\n      target: Observabilidade\n", encoding="utf8"
    )
    (folder / "segundo.yaml").write_text(
        "version: 1\nname: Observabilidade\nkeys:\n  15:\n    label: Desenvolv.\n    action:\n      type: profile\n      target: Desenvolvimento\n", encoding="utf8"
    )
    paths = ("primeiro.yaml", "segundo.yaml")
    return folder, paths


def req(project, profile="Desenvolvimento"):
    root, paths = project
    return editor.inspect_profile(root, profile, paths)


def test_inspect_has_15_physical_keys_and_checksum(project):
    info = req(project)
    assert len(info["keys"]) == 15
    assert info["keys"]["1"]["action"]["argv"] == ["gnome-terminal"]
    assert info["keys"]["5"]["action"]["type"] == "none"
    assert info["keys"]["15"]["action"]["target"] == "Observabilidade"


def test_preview_does_not_modify_yaml(project, tmp_path, monkeypatch):
    root, paths = project
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    info = req(project)
    before = (root / "primeiro.yaml").read_bytes()
    edited = {"label": "Observabilidade", "image": "", "action": {"type": "url", "url": "https://example.org"}}
    result = editor.preview_key(root, "Desenvolvimento", 2, edited, info["sha256"], paths)
    assert len(result["previews"]) == 15
    with Image.open(result["previews"]["2"]["image"]) as picture:
        assert picture.size == (100, 100)
    assert result["previews"]["15"]["display_id"] == 5
    assert (root / "primeiro.yaml").read_bytes() == before


def test_save_writes_valid_yaml_and_backup(project, tmp_path):
    root, paths = project
    info = req(project)
    edited = {"label": "Grafana", "image": "", "action": {"type": "url", "url": "https://grafana.com"}}
    result = editor.save_key(root, "Desenvolvimento", 2, edited, info["sha256"], paths,
                             backup_dir=tmp_path / "backup")
    current = editor.inspect_profile(root, "Desenvolvimento", paths)
    assert current["keys"]["2"]["label"] == "Grafana"
    assert current["keys"]["2"]["action"]["url"] == "https://grafana.com"
    assert b"Grafana" not in Path(result["backup"]).read_bytes()
    assert current["sha256"] == result["sha256"]


def test_rejects_stale_writes(project, tmp_path):
    root, paths = project
    original = req(project)
    (root / "primeiro.yaml").write_text((root / "primeiro.yaml").read_text() + "\n# alterado\n")
    with pytest.raises(RuntimeError, match="mudou no disco"):
        editor.save_key(root, "Desenvolvimento", 3,
                        {"label": "Site", "action": {"type": "url", "url": "https://example.org"}},
                        original["sha256"], paths, backup_dir=tmp_path / "backup")
    assert not (tmp_path / "backup").exists()


def test_remove_key_by_none_action(project, tmp_path):
    root, paths = project
    info = req(project)
    editor.save_key(root, "Desenvolvimento", 1, {"label": "", "action": {"type": "none"}},
                    info["sha256"], paths, backup_dir=tmp_path / "backup")
    assert 1 not in yaml.safe_load((root / "primeiro.yaml").read_text())["keys"]


def test_unknown_target_is_rejected_without_overwriting(project, tmp_path):
    root, paths = project
    info = req(project)
    original = (root / "primeiro.yaml").read_bytes()
    with pytest.raises(ValueError, match="destino"):
        editor.save_key(root, "Desenvolvimento", 2,
                        {"label": "Trocar", "action": {"type": "profile", "target": "Inexistente"}},
                        info["sha256"], paths, backup_dir=tmp_path / "backup")
    assert (root / "primeiro.yaml").read_bytes() == original


def test_loader_rejects_bad_script_and_image(project, tmp_path):
    root, paths = project
    original = req(project)
    action = {"type": "script", "path": "nao-existe.sh", "interpreter": "bash", "args": []}
    with pytest.raises(ValueError, match="não encontrado"):
        editor.save_key(root, "Desenvolvimento", 2, {"label": "Script", "action": action},
                        original["sha256"], paths, backup_dir=tmp_path / "backup")
    action = {"type": "command", "argv": ["echo", "ok"]}
    with pytest.raises(ValueError, match="não encontrado"):
        editor.preview_key(root, "Desenvolvimento", 2,
                           {"label": "Imagem", "action": action, "image": "perdida.png"},
                           original["sha256"], paths)


def test_hotkey_and_script_roundtrip(project, tmp_path):
    root, paths = project
    info = req(project)
    editor.save_key(root, "Desenvolvimento", 3,
                    {"label": "Nova aba", "action": {"type": "hotkey", "keys": ["ctrl", "shift", "t"]}},
                    info["sha256"], paths, backup_dir=tmp_path / "backup")
    current = req(project)
    assert current["keys"]["3"]["action"]["keys"] == ["ctrl", "shift", "t"]
    script = root / "aviso.sh"
    script.write_text('#!/usr/bin/env bash\necho ok\n')
    editor.save_key(root, "Desenvolvimento", 4,
                    {"label": "Script", "action": {"type": "script", "path": str(script),
                                                    "interpreter": "bash", "args": ["--verbose"]}},
                    current["sha256"], paths, backup_dir=tmp_path / "backup")
    assert req(project)["keys"]["4"]["action"]["args"] == ["--verbose"]


def test_unsupported_profile_cannot_be_edited(project):
    root, paths = project
    with pytest.raises(ValueError, match="não permitido"):
        editor.inspect_profile(root, "Outro", paths)


def test_image_pixels_preview_matches_custom_image(project, tmp_path, monkeypatch):
    root, paths = project
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    image = root / "amostra.png"
    Image.new("RGB", (200, 200), (15, 60, 90)).save(image)
    info = req(project)
    result = editor.preview_key(root, "Desenvolvimento", 2,
                                {"label": "Imagem", "image": str(image),
                                 "action": {"type": "command", "argv": ["true"]}},
                                info["sha256"], paths)
    with Image.open(result["previews"]["2"]["image"]) as png:
        assert png.getpixel((0, 0)) == (15, 60, 90)


def test_no_hid_import_used_in_backend():
    # Protege o contrato de isolamento do editor; não acessar /dev/hidraw.
    source = (ROOT / "apps/vision02_editor_backend.py").read_text()
    assert "Vision02()" not in source
    assert "os.open('/dev/hidraw" not in source
