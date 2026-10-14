"""Regressões para seleção XDG; testes não acessam USB/HID."""
from pathlib import Path

import pytest

from vision02.user_profiles import config_profile_dir, default_profile_paths


def test_prefers_user_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "conf"))
    folder = config_profile_dir()
    folder.mkdir(parents=True)
    first = folder / "desenvolvimento.yaml"
    second = folder / "observabilidade.yaml"
    first.write_text("um")
    second.write_text("dois")
    assert default_profile_paths(tmp_path) == (first, second)


def test_falls_back_to_examples_without_personal_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "conf"))
    paths = default_profile_paths(tmp_path)
    assert paths == (
        tmp_path / "examples/profiles/desenvolvimento-switch.yaml",
        tmp_path / "examples/profiles/observabilidade.yaml",
    )


def test_incomplete_personal_configuration_fails_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "conf"))
    folder = config_profile_dir()
    folder.mkdir(parents=True)
    (folder / "desenvolvimento.yaml").write_text("existe")
    with pytest.raises(ValueError, match="incompleta"):
        default_profile_paths(tmp_path)


def test_editor_and_preview_use_shared_user_profile_resolver():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    backend = (root / "apps/vision02_editor_backend.py").read_text()
    preview = (root / "apps/vision02_gui_data.py").read_text()
    assert "default_profile_paths(project)" in backend
    assert "default_profile_paths(args.project)" in preview
