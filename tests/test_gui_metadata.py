"""Verificações offline da camada de prévias da GUI; nunca abrem HID."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vision02_gui_data", ROOT / "apps" / "vision02_gui_data.py")
assert SPEC is not None and SPEC.loader is not None
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def test_metadata_has_correct_physical_layout(tmp_path):
    result = MOD.build_metadata(ROOT, cache=tmp_path)
    info = result["profiles"]["Desenvolvimento"]["keys"]
    assert [item["id"] for item in info] == list(range(1, 16))
    assert [item["display_id"] for item in info[:5]] == [11, 12, 13, 14, 15]
    assert [item["display_id"] for item in info[-5:]] == [1, 2, 3, 4, 5]


def test_known_labels_actions_and_profile(tmp_path):
    profiles = MOD.build_metadata(ROOT, cache=tmp_path)["profiles"]
    assert set(profiles) == {"Desenvolvimento", "Observabilidade"}
    assert profiles["Desenvolvimento"]["keys"][0]["label"] == "Terminal"
    assert profiles["Desenvolvimento"]["keys"][14]["action"] == "profile"
    assert profiles["Observabilidade"]["keys"][14]["action"] == "profile"


def test_previews_exist_as_rgb_100x100(tmp_path):
    profiles = MOD.build_metadata(ROOT, cache=tmp_path)["profiles"]
    for profile in profiles.values():
        for key in profile["keys"]:
            with Image.open(key["image"]) as png:
                assert png.size == (100, 100)
                assert png.mode == "RGB"
                assert png.format == "PNG"
    assert len(list(tmp_path.glob("*.png"))) == 30


def test_unconfigured_key_is_not_executable(tmp_path):
    keys = MOD.build_metadata(ROOT, cache=tmp_path)["profiles"]["Desenvolvimento"]["keys"]
    assert keys[4]["id"] == 5
    assert keys[4]["label"] == ""
    assert keys[4]["action"] == ""


def test_duplicate_profile_name_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="duplicados"):
        MOD.build_metadata(
            ROOT,
            ["examples/profiles/desenvolvimento-switch.yaml"] * 2,
            cache=tmp_path,
        )


def test_cli_returns_json_without_hid(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "apps" / "vision02_gui_data.py"),
         "--project", str(ROOT), "--cache", str(tmp_path)],
        text=True, capture_output=True, check=True,
    )
    assert len(json.loads(result.stdout)["profiles"]) == 2
