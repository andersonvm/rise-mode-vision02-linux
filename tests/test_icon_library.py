"""Biblioteca de ícones offline: entradas, deduplicação, segurança e editor GTK."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest

from vision02 import icon_library as lib

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vision02_editor_backend_icons", ROOT / "apps/vision02_editor_backend.py")
assert SPEC and SPEC.loader
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)


def make_image(path, size=(400, 200), color=(40, 80, 120)):
    Image.new("RGB", size, color).save(path)
    return path


def test_import_converts_to_rgb_100x100_and_private(tmp_path):
    source = make_image(tmp_path / "Ícone Dev.png")
    library = tmp_path / "data/icons"
    result = lib.import_icon(source, root=library)
    assert result["imported"] is True
    with Image.open(result["path"]) as picture:
        assert picture.size == (100, 100)
        assert picture.mode == "RGB"
        assert picture.format == "PNG"
    assert Path(result["path"]).stat().st_mode & 0o777 == 0o600
    assert library.stat().st_mode & 0o777 == 0o700
    assert len(lib.list_icons(library)) == 1


def test_import_is_idempotent_for_identical_pixels(tmp_path):
    first = make_image(tmp_path / "A.png")
    other = make_image(tmp_path / "B.png")
    root = tmp_path / "icons"
    left = lib.import_icon(first, root=root)
    right = lib.import_icon(other, root=root)
    assert right["imported"] is False
    assert right["path"] == left["path"]
    assert len(lib.list_icons(root)) == 1


def test_independent_images_are_reusable(tmp_path):
    root = tmp_path / "icons"
    first = make_image(tmp_path / "Grafana.png", color=(19, 23, 67))
    second = make_image(tmp_path / "Prometheus.png", color=(125, 33, 3))
    a = lib.import_icon(first, root=root)
    b = lib.import_icon(second, root=root)
    assert a["path"] != b["path"]
    assert len(lib.list_icons(root)) == 2
    assert lib.list_icons(root)[0]["path"].startswith(str(root))


def test_transparent_image_is_composited(tmp_path):
    source = tmp_path / "transparente.png"
    Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(source)
    item = lib.import_icon(source, root=tmp_path / "icons")
    with Image.open(item["path"]) as picture:
        assert picture.getpixel((50, 50)) == (8, 12, 22)


@pytest.mark.parametrize("suffix", [".txt", ".gif", ".svg"])
def test_rejects_unsupported_extension(tmp_path, suffix):
    source = tmp_path / f"entrada{suffix}"
    source.write_bytes(b"not an image")
    with pytest.raises(ValueError, match="Formato aceito"):
        lib.import_icon(source, root=tmp_path / "icons")
    assert not (tmp_path / "icons").exists()


def test_rejects_disguised_non_image(tmp_path):
    source = tmp_path / "foto.jpg"
    source.write_bytes(b"nao e jpg")
    with pytest.raises(ValueError, match="processar"):
        lib.import_icon(source, root=tmp_path / "icons")


def test_rejects_large_file(tmp_path):
    path = tmp_path / "grande.png"
    with path.open("wb") as stream:
        stream.truncate(lib.MAX_SOURCE_BYTES + 1)
    with pytest.raises(ValueError, match="15 MiB"):
        lib.import_icon(path, root=tmp_path / "icons")


def test_rejects_symlinked_source_and_library(tmp_path):
    source = make_image(tmp_path / "source.png")
    link = tmp_path / "alias.png"
    link.symlink_to(source)
    with pytest.raises(ValueError, match="link simbólico"):
        lib.import_icon(link, root=tmp_path / "icons")
    realdir = tmp_path / "real"
    realdir.mkdir()
    alias = tmp_path / "link"
    alias.symlink_to(realdir, target_is_directory=True)
    with pytest.raises(ValueError, match="link simbólico"):
        lib.import_icon(source, root=alias)


def test_fake_icon_symlink_not_listed(tmp_path):
    root = tmp_path / "icons"
    root.mkdir()
    foreign = make_image(tmp_path / "foreign.png", size=(100, 100))
    (root / ("a" * 20 + "-evil.png")).symlink_to(foreign)
    assert lib.list_icons(root) == []


def test_editor_backend_import_list_without_hid(tmp_path, monkeypatch):
    source = make_image(tmp_path / "Teste.png")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    item = lib.import_icon(source)
    assert backend.list_icons() == [
        {"name": "Teste", "path": item["path"], "id": item["id"]}
    ]


def test_backend_cli_import_and_list(tmp_path, monkeypatch):
    image = make_image(tmp_path / "CLI.png")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    def run(command, payload=None):
        result = subprocess.run(
            [sys.executable, str(ROOT / "apps/vision02_editor_backend.py"),
             "--project", str(ROOT), "--command", command],
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True, text=True,
        )
        return result.returncode, json.loads(result.stdout)
    code, data = run("icons-import", {"source": str(image)})
    assert code == 0 and data["icon"]["imported"]
    code, data = run("icons-list")
    assert code == 0 and len(data["icons"]) == 1
    with Image.open(data["icons"][0]["path"]) as picture:
        assert picture.size == (100, 100)


def test_editor_preserves_action_with_library_image(tmp_path):
    image = make_image(tmp_path / "Logo.png")
    icon = lib.import_icon(image, root=tmp_path / "icons")
    original = (b"version: 1\nname: Demo\nkeys:\n  5:\n    label: Browser\n"
                b"    action:\n      type: url\n      url: https://example.org\n")
    updated = backend._new_yaml(
        original, 5, {"label": "Browser", "image": icon["path"],
                     "action": {"type": "url", "url": "https://example.org"}},
        {"Demo"},
    )
    import yaml
    key = yaml.safe_load(updated)["keys"][5]
    assert key["image"] == icon["path"]
    assert key["action"] == {"type": "url", "url": "https://example.org"}


def test_gui_uses_15_physical_keys_with_highlight_and_library():
    source = (ROOT / "apps/vision02_editor.py").read_text(encoding="utf-8")
    assert "for key_id in range(1, 16):" in source
    assert "(key_id - 1) % 5" in source
    assert "(key_id - 1) // 5" in source
    assert 'def _highlight_selected(self):' in source
    assert 'Gtk.Button(label="Biblioteca…")' in source
    compile(source, str(ROOT / "apps/vision02_editor.py"), "exec")
