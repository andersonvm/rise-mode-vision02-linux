"""Testes offline da GUI com perfis isolados, sem acessar USB/HID.

Não dependem dos YAML que o editor modifica no diretório examples/.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "vision02_gui_data", ROOT / "apps" / "vision02_gui_data.py"
)
assert SPEC is not None and SPEC.loader is not None
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


@pytest.fixture
def profile_paths(tmp_path):
    """Dois perfis controlados exclusivamente pelos testes."""
    development = tmp_path / "desenvolvimento.yaml"
    observability = tmp_path / "observabilidade.yaml"

    development.write_text(
        "version: 1\n"
        "name: Desenvolvimento\n"
        "keys:\n"
        "  1:\n"
        "    label: Terminal\n"
        "    action:\n"
        "      type: command\n"
        "      argv: [gnome-terminal]\n"
        "  15:\n"
        "    label: Observar\n"
        "    action:\n"
        "      type: profile\n"
        "      target: Observabilidade\n",
        encoding="utf-8",
    )
    observability.write_text(
        "version: 1\n"
        "name: Observabilidade\n"
        "keys:\n"
        "  1:\n"
        "    label: Grafana\n"
        "    action:\n"
        "      type: url\n"
        "      url: https://example.org/grafana\n"
        "  15:\n"
        "    label: Desenvolv.\n"
        "    action:\n"
        "      type: profile\n"
        "      target: Desenvolvimento\n",
        encoding="utf-8",
    )
    return [development, observability]


def metadata(tmp_path, profile_paths):
    return MOD.build_metadata(
        ROOT, profile_paths, cache=tmp_path / "preview"
    )["profiles"]


def test_metadata_has_correct_physical_layout(tmp_path, profile_paths):
    info = metadata(tmp_path, profile_paths)["Desenvolvimento"]["keys"]
    assert [item["id"] for item in info] == list(range(1, 16))
    assert [item["display_id"] for item in info[:5]] == [11, 12, 13, 14, 15]
    assert [item["display_id"] for item in info[-5:]] == [1, 2, 3, 4, 5]


def test_known_labels_actions_and_profile(tmp_path, profile_paths):
    profiles = metadata(tmp_path, profile_paths)
    assert set(profiles) == {"Desenvolvimento", "Observabilidade"}
    assert profiles["Desenvolvimento"]["keys"][0]["label"] == "Terminal"
    assert profiles["Desenvolvimento"]["keys"][14]["action"] == "profile"
    assert profiles["Observabilidade"]["keys"][14]["action"] == "profile"


def test_previews_exist_as_rgb_100x100(tmp_path, profile_paths):
    profiles = metadata(tmp_path, profile_paths)
    for profile in profiles.values():
        for key in profile["keys"]:
            with Image.open(key["image"]) as png:
                assert png.size == (100, 100)
                assert png.mode == "RGB"
                assert png.format == "PNG"
    assert len(list((tmp_path / "preview").glob("*.png"))) == 30


def test_unconfigured_key_is_not_executable(tmp_path, profile_paths):
    keys = metadata(tmp_path, profile_paths)["Desenvolvimento"]["keys"]
    assert keys[4]["id"] == 5
    assert keys[4]["label"] == ""
    assert keys[4]["action"] == ""


def test_custom_key_five_is_reflected_in_metadata(tmp_path, profile_paths):
    """O editor pode configurar a tecla 05 sem quebrar a GUI."""
    development = profile_paths[0]
    development.write_text(
        development.read_text(encoding="utf-8")
        + "  5:\n"
          "    label: Grafana\n"
          "    action:\n"
          "      type: url\n"
          "      url: https://example.org/grafana\n",
        encoding="utf-8",
    )
    keys = metadata(tmp_path, profile_paths)["Desenvolvimento"]["keys"]
    assert keys[4]["id"] == 5
    assert keys[4]["label"] == "Grafana"
    assert keys[4]["action"] == "url"


def test_duplicate_profile_name_is_rejected(tmp_path, profile_paths):
    with pytest.raises(ValueError, match="duplicados"):
        MOD.build_metadata(
            ROOT, [profile_paths[0], profile_paths[0]], cache=tmp_path / "preview"
        )


def test_cli_returns_json_without_hid(tmp_path, profile_paths):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "apps" / "vision02_gui_data.py"),
            "--project", str(ROOT),
            "--cache", str(tmp_path / "preview"),
            "--profile", str(profile_paths[0]),
            "--profile", str(profile_paths[1]),
        ],
        text=True, capture_output=True, check=True,
    )
    assert len(json.loads(result.stdout)["profiles"]) == 2
