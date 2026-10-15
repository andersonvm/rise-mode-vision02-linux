"""Personalização visual compartilhada por preview GTK e controlador (offline)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml
from PIL import Image, ImageChops

from vision02.display import encode_image
from vision02.profiles import load_profile
from vision02.profiles.loader import ProfileValidationError, parse_appearance
from vision02.profiles.models import Action, KeyAppearance, KeyConfig
from vision02.rendering import render_appearance, render_key, render_label, render_profile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("editor_visual_backend", ROOT / "apps/vision02_editor_backend.py")
assert SPEC and SPEC.loader
editor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(editor)


def fixture_profile(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text("version: 1\nname: Demo\nkeys:\n  1:\n    label: Grafana\n    action:\n      type: url\n      url: https://example.org\n", encoding="utf8")
    return path


def payload(label="Grafana", **kw):
    return {"label": label, "image": "", "action": {"type": "url", "url": "https://example.org"},
            "appearance": {"background": "#112233", "text_color": "#DDEEFF", "font_size": 18, **kw}}


def test_legacy_profile_has_no_style(tmp_path):
    p = fixture_profile(tmp_path)
    config = load_profile(p).keys[1]
    assert config.appearance is None
    assert ImageChops.difference(render_key(config), render_label("Grafana")).getbbox() is None


def test_style_loads_and_renders_rgb(tmp_path):
    path = fixture_profile(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["keys"][1]["appearance"] = payload()["appearance"]
    path.write_text(yaml.safe_dump(data, allow_unicode=True))
    profile = load_profile(path)
    assert profile.keys[1].appearance.background == "#112233"
    result = render_profile(profile)[1]
    assert result.size == (100, 100) and result.mode == "RGB"
    assert result.getpixel((0, 0)) == (17, 34, 51)
    assert render_profile(profile)[2].mode == "RGB"


@pytest.mark.parametrize("key,wrong", [
    ("background", "blue"), ("text_color", "#XYZXYZ"),
    ("font_family", "comic sans"), ("font_weight", "heavy"),
    ("font_size", 7), ("font_size", 37), ("font_size", True),
    ("horizontal", "diagonal"), ("vertical", "middle"),
    ("offset_x", 41), ("offset_y", -41), ("offset_x", 1.5),
    ("show_text", "false"), ("image_fit", "tile"),
    ("text", "a" * 121),
])
def test_invalid_fields_rejected(key, wrong):
    with pytest.raises(ProfileValidationError, match="appearance"):
        parse_appearance({key: wrong})


def test_unknown_field_rejected():
    with pytest.raises(ProfileValidationError, match="desconhecidos"):
        parse_appearance({"arbitrary_code": "xyz"})


def test_appearance_needs_mapping():
    with pytest.raises(ProfileValidationError):
        parse_appearance(["wrong"])


@pytest.mark.parametrize("family", ["sans", "serif", "mono"])
@pytest.mark.parametrize("weight", ["regular", "bold"])
def test_supported_fonts_render(family, weight):
    style = parse_appearance({"font_family": family, "font_weight": weight})
    result = render_appearance("Estilo de fonte", None, style)
    assert result.size == (100, 100)
    assert ImageChops.difference(result, Image.new("RGB", (100, 100), style.background)).getbbox()


@pytest.mark.parametrize("horizontal", ["left", "center", "right"])
@pytest.mark.parametrize("vertical", ["top", "center", "bottom"])
def test_all_alignments(horizontal, vertical):
    style = parse_appearance({"horizontal": horizontal, "vertical": vertical})
    result = render_appearance("Teste", None, style)
    assert result.size == (100, 100)


def test_text_position_changes_pixels():
    initial = render_appearance("Texto", None, KeyAppearance())
    moved = render_appearance("Texto", None, KeyAppearance(offset_x=17, offset_y=-15))
    assert ImageChops.difference(initial, moved).getbbox()


def test_custom_text_overrides_label():
    text = render_appearance("Perfil", None, KeyAppearance(text="Único"))
    expected = render_appearance("Único", None, KeyAppearance())
    assert ImageChops.difference(text, expected).getbbox() is None


def test_text_can_be_hidden():
    style = KeyAppearance(show_text=False, background="#334455")
    assert set(render_appearance("Grafana", None, style).get_flattened_data()) == {(51, 68, 85)}


@pytest.mark.parametrize("fit", ["cover", "contain", "stretch"])
def test_image_background_rendering_modes(tmp_path, fit):
    source = tmp_path / "wide.png"
    Image.new("RGB", (200, 60), (200, 80, 40)).save(source)
    style = KeyAppearance(show_text=False, image_fit=fit, background="#010203")
    image = render_appearance("Icone", source, style)
    assert image.size == (100, 100) and image.mode == "RGB"
    if fit == "contain":
        assert image.getpixel((0, 0)) == (1, 2, 3)
    else:
        assert image.getpixel((0, 0)) == (200, 80, 40)


def test_appearance_and_legacy_image_are_separate(tmp_path):
    p = tmp_path / "image.png"
    Image.new("RGB", (150, 150), (10, 20, 30)).save(p)
    key = KeyConfig(1, "Exemplo", Action(type="command", argv=("echo",)), image=p)
    assert render_key(key) == p  # contrato legado preservado
    styled = KeyConfig(1, "Exemplo", key.action, image=p, appearance=KeyAppearance(show_text=False))
    assert isinstance(render_key(styled), Image.Image)
    assert render_key(styled).getpixel((0, 0)) == (10, 20, 30)


def test_editor_saves_style_and_preview_matches_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    p = fixture_profile(tmp_path)
    initial = editor.inspect_profile(tmp_path, "Demo", [p])
    edited = payload(horizontal="right", vertical="bottom", offset_x=-2, offset_y=-3)
    original = p.read_bytes()
    local = editor.preview_appearance(tmp_path, "Demo", edited, [p])
    assert p.read_bytes() == original  # visual preview never writes to YAML
    assert editor.inspect_profile(tmp_path, "Demo", [p])["keys"]["1"]["appearance"] is None
    result = editor.preview_key(tmp_path, "Demo", 1, edited, initial["sha256"], [p])
    assert len(result["previews"]) == 15
    with Image.open(local["image"]) as visual, Image.open(result["previews"]["1"]["image"]) as full:
        assert ImageChops.difference(visual, full).getbbox() is None
    saved = editor.save_key(tmp_path, "Demo", 1, edited, initial["sha256"], [p], backup_dir=tmp_path / "backup")
    assert saved["ok"]
    assert editor.inspect_profile(tmp_path, "Demo", [p])["keys"]["1"]["appearance"]["horizontal"] == "right"
    runtime = render_profile(load_profile(p))[1]
    with Image.open(local["image"]) as visual:
        assert ImageChops.difference(visual, runtime).getbbox() is None
    # HID encoder keeps the JPEG protocol path unchanged.
    assert encode_image(runtime).startswith(b"\xff\xd8")


def test_editor_preserves_existing_style_when_omitted(tmp_path):
    p = fixture_profile(tmp_path)
    ini = editor.inspect_profile(tmp_path, "Demo", [p])
    edited = payload(font_size=26)
    editor.save_key(tmp_path, "Demo", 1, edited, ini["sha256"], [p], backup_dir=tmp_path / "backups")
    old = editor.inspect_profile(tmp_path, "Demo", [p])
    old_key = old["keys"]["1"]
    editor.save_key(tmp_path, "Demo", 1, {"label": "Outro", "image": "", "action": old_key["action"]},
                    old["sha256"], [p], backup_dir=tmp_path / "backups")
    assert load_profile(p).keys[1].appearance.font_size == 26


def test_editor_can_clear_existing_style(tmp_path):
    p = fixture_profile(tmp_path)
    ini = editor.inspect_profile(tmp_path, "Demo", [p])
    edited = payload()
    editor.save_key(tmp_path, "Demo", 1, edited, ini["sha256"], [p], backup_dir=tmp_path / "backups")
    current = editor.inspect_profile(tmp_path, "Demo", [p])
    edited["appearance"] = None
    editor.save_key(tmp_path, "Demo", 1, edited, current["sha256"], [p], backup_dir=tmp_path / "backups")
    assert load_profile(p).keys[1].appearance is None


def test_preview_rejects_invalid_appearance_without_writing(tmp_path):
    p = fixture_profile(tmp_path)
    original = p.read_bytes()
    current = editor.inspect_profile(tmp_path, "Demo", [p])
    with pytest.raises(ValueError, match="appearance"):
        editor.preview_key(tmp_path, "Demo", 1, payload(font_size=900), current["sha256"], [p])
    assert p.read_bytes() == original


def test_stale_checksum_blocks_style_save(tmp_path):
    p = fixture_profile(tmp_path)
    current = editor.inspect_profile(tmp_path, "Demo", [p])
    p.write_text(p.read_text() + "\n# changed")
    with pytest.raises(RuntimeError, match="mudou no disco"):
        editor.save_key(tmp_path, "Demo", 1, payload(), current["sha256"], [p], backup_dir=tmp_path / "backup")


def test_style_works_with_non_ascii_multiline():
    style = KeyAppearance(text="Árvore\nMétricas", text_color="#FF00CC")
    result = render_appearance("ignored", None, style)
    assert result.size == (100, 100)


def test_hid_not_used_in_editor_preview():
    script = (ROOT / "apps/vision02_editor_backend.py").read_text()
    assert "Vision02(" not in script and "/dev/hidraw" not in script
