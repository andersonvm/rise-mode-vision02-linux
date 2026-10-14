"""Editor GTK4/libadwaita dos perfis Vision 02, sem acesso USB/HID.

Usa Python do sistema para gi; delega PyYAML/Pillow ao Python da .venv.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv/bin/python"
BACKEND = ROOT / "apps/vision02_editor_backend.py"
METADATA = ROOT / "apps/vision02_gui_data.py"

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

KINDS = ("none", "command", "url", "script", "hotkey", "profile")
KIND_LABELS = ("Sem ação", "Comando", "URL", "Script", "Atalho", "Trocar perfil")


def backend(command, profile=None, payload=None, timeout=20):
    cmd = [str(PYTHON), str(BACKEND), "--project", str(ROOT), "--command", command]
    if profile:
        cmd += ["--profile", profile]
    result = subprocess.run(
        cmd,
        input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
        text=True, capture_output=True, check=False, timeout=timeout,
    )
    try:
        response = json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError((result.stderr or result.stdout or str(exc)).strip()) from exc
    if not response.get("ok"):
        raise RuntimeError(response.get("error", "Falha desconhecida"))
    return response


class EditorWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Editor de teclas — Vision 02")
        self.set_default_size(1100, 780)
        self.set_size_request(780, 600)
        self.profile_names = backend("list")["profiles"]
        self.profile_name = self.profile_names[0]
        self.profile = None
        self.selected_key = 1
        self.dirty = False
        self.busy = False
        self._syncing = True
        self.image_paths = {}
        self.key_buttons = {}

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)
        self.set_content(toolbar)

        container = Gtk.ScrolledWindow()
        container.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        toolbar.set_content(container)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        for field in ("margin_start", "margin_end", "margin_top", "margin_bottom"):
            setattr(root.props, field, 22)
        container.set_child(root)

        title = Gtk.Label(label="Editar teclas e ações")
        title.add_css_class("title-1")
        title.set_xalign(0)
        root.append(title)

        subtitle = Gtk.Label(label="A prévia é local. Salve o YAML e clique em Aplicar ao dispositivo.")
        subtitle.set_xalign(0)
        subtitle.set_wrap(True)
        subtitle.add_css_class("dim-label")
        root.append(subtitle)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        top.append(Gtk.Label(label="Perfil a editar:"))
        self.profile_combo = Gtk.DropDown.new_from_strings(self.profile_names)
        self.profile_combo.connect("notify::selected", self._on_profile_changed)
        top.append(self.profile_combo)
        root.append(top)

        columns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        root.append(columns)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        columns.append(left)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        right.set_hexpand(True)
        columns.append(right)

        left.append(Gtk.Label(label="Teclas físicas (5 × 3)"))
        self.grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        self.grid.set_column_homogeneous(True)
        left.append(self.grid)
        for key_id in range(1, 16):
            btn = Gtk.Button()
            btn.set_size_request(106, 130)
            btn.connect("clicked", self._on_key_selected, key_id)
            self.grid.attach(btn, (key_id - 1) % 5, (key_id - 1) // 5, 1, 1)
            self.key_buttons[key_id] = btn

        self.key_title = Gtk.Label(label="Tecla física 01")
        self.key_title.set_xalign(0)
        self.key_title.add_css_class("title-3")
        right.append(self.key_title)

        self.entries = {}
        self.entries["label"] = self._entry(right, "Rótulo")

        image_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        self.entries["image"] = self._entry(image_row, "Imagem (caminho absoluto ou relativo ao YAML)")
        image_row_child = Gtk.Button(label="Escolher…")
        image_row_child.connect("clicked", self._choose_image)
        image_row.append(image_row_child)
        right.append(image_row)

        right.append(Gtk.Label(label="Tipo de ação"))
        self.kind_combo = Gtk.DropDown.new_from_strings(KIND_LABELS)
        self.kind_combo.connect("notify::selected", self._change_kind)
        right.append(self.kind_combo)

        spec = [
            ("argv", "Comando e argumentos (ex.: gnome-terminal)"),
            ("url", "Endereço HTTP/HTTPS"),
            ("path", "Caminho do script"),
            ("args", "Argumentos do script"),
            ("keys", "Atalho (ex.: ctrl, shift, t)"),
            ("target", "Nome do perfil de destino"),
        ]
        self.action_rows = {}
        for key, label in spec:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            self.entries[key] = self._entry(row, label)
            right.append(row)
            self.action_rows[key] = row

        self.interpreter_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.interpreter_box.append(Gtk.Label(label="Interpretador"))
        self.interpreter = Gtk.DropDown.new_from_strings(["bash", "python3"])
        self.interpreter.connect("notify::selected", self._on_changed)
        self.interpreter_box.append(self.interpreter)
        right.append(self.interpreter_box)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.preview_btn = Gtk.Button(label="Pré-visualizar")
        self.preview_btn.connect("clicked", lambda *_: self._work("preview"))
        buttons.append(self.preview_btn)
        self.save_btn = Gtk.Button(label="Salvar YAML")
        self.save_btn.add_css_class("suggested-action")
        self.save_btn.connect("clicked", lambda *_: self._work("save"))
        buttons.append(self.save_btn)
        self.discard_btn = Gtk.Button(label="Descartar edição")
        self.discard_btn.connect("clicked", self._discard)
        buttons.append(self.discard_btn)
        right.append(buttons)

        self.apply_btn = Gtk.Button(label="Aplicar ao dispositivo")
        self.apply_btn.set_tooltip_text("Recarrega os YAML por IPC sem reiniciar o serviço nem a conexão USB")
        self.apply_btn.set_sensitive(False)
        self.apply_btn.connect("clicked", self._confirm_apply)
        right.append(self.apply_btn)

        self.status = Gtk.Label(label="")
        self.status.set_xalign(0)
        self.status.set_wrap(True)
        self.status.add_css_class("dim-label")
        root.append(self.status)

        self._load_profile()
        self._syncing = False

    def _entry(self, parent, label):
        group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        caption = Gtk.Label(label=label)
        caption.set_xalign(0)
        caption.add_css_class("caption")
        group.append(caption)
        text = Gtk.Entry()
        text.connect("changed", self._on_changed)
        text.set_hexpand(True)
        group.append(text)
        parent.append(group)
        return text

    def _on_changed(self, *_):
        if not self._syncing:
            self.dirty = True
            self.status.set_text("Alterações locais não salvas.")

    def _change_kind(self, *_):
        kind = KINDS[self.kind_combo.get_selected()]
        showing = {
            "command": {"argv"},
            "url": {"url"},
            "script": {"path", "args"},
            "hotkey": {"keys"},
            "profile": {"target"},
        }.get(kind, set())
        for field, row in self.action_rows.items():
            row.set_visible(field in showing)
        self.interpreter_box.set_visible(kind == "script")
        self._on_changed()

    def _choose_image(self, *_):
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Escolher imagem da tecla")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        image_filter = Gtk.FileFilter()
        image_filter.set_name("Imagens PNG, JPEG e WEBP")
        for mime in ("image/png", "image/jpeg", "image/webp"):
            image_filter.add_mime_type(mime)
        filters.append(image_filter)
        dialog.set_filters(filters)
        dialog.open(self, None, self._image_chosen)

    def _image_chosen(self, dialog, result):
        try:
            item = dialog.open_finish(result)
            if item:
                self.entries["image"].set_text(item.get_path() or "")
        except GLib.Error as exc:
            # Fechar o seletor sem arquivo não é erro.
            if not exc.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                self.status.set_text(f"Falha ao selecionar imagem: {exc}")

    def _on_key_selected(self, _, key_id):
        if self.busy or key_id == self.selected_key:
            return
        if self.dirty:
            self.status.set_text("Salve ou descarte a edição antes de trocar de tecla.")
            return
        self.selected_key = key_id
        self._populate_form()

    def _on_profile_changed(self, combo, _):
        if self._syncing or self.busy:
            return
        index = combo.get_selected()
        if index >= len(self.profile_names):
            return
        requested = self.profile_names[index]
        if requested == self.profile_name:
            return
        if self.dirty:
            self.status.set_text("Salve ou descarte a edição antes de trocar de perfil.")
            self._syncing = True
            combo.set_selected(self.profile_names.index(self.profile_name))
            self._syncing = False
            return
        self.profile_name = requested
        self.selected_key = 1
        self._load_profile()

    def _load_profile(self):
        try:
            self.profile = backend("inspect", self.profile_name)["profile"]
            response = subprocess.run(
                [str(PYTHON), str(METADATA), "--project", str(ROOT),
                 "--profile", self.profile["path"]],
                text=True, capture_output=True, check=True, timeout=25,
            )
            info = json.loads(response.stdout)["profiles"][self.profile_name]
            self.image_paths = {x["id"]: x["image"] for x in info["keys"]}
            self._draw_board()
            self._populate_form()
            self.status.set_text(f"Editando: {self.profile['path']}")
        except (RuntimeError, OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
            self.status.set_text(f"Falha ao carregar perfil: {exc}")
            self.save_btn.set_sensitive(False)

    def _draw_board(self):
        for physical, btn in self.key_buttons.items():
            path = self.image_paths.get(physical)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.set_halign(Gtk.Align.CENTER)
            if path and Path(path).is_file():
                picture = Gtk.Picture.new_for_file(Gio.File.new_for_path(path))
                picture.set_size_request(96, 96)
                picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                box.append(picture)
            label = Gtk.Label(label=f"Tecla {physical:02d}")
            label.add_css_class("caption")
            box.append(label)
            btn.set_child(box)

    def _populate_form(self):
        if not self.profile:
            return
        self._syncing = True
        try:
            cfg = self.profile["keys"][str(self.selected_key)]
            action = cfg["action"]
            kind = action["type"]
            self.key_title.set_text(f"Tecla física {self.selected_key:02d}")
            self.entries["label"].set_text(cfg.get("label", ""))
            self.entries["image"].set_text(cfg.get("image", ""))
            self.entries["argv"].set_text(shlex.join(action.get("argv", [])))
            self.entries["url"].set_text(action.get("url", "") or "")
            self.entries["path"].set_text(action.get("path", "") or "")
            self.entries["args"].set_text(shlex.join(action.get("args", [])))
            self.entries["keys"].set_text(", ".join(action.get("keys", [])))
            self.entries["target"].set_text(action.get("target", "") or "")
            self.interpreter.set_selected(0 if action.get("interpreter", "bash") == "bash" else 1)
            self.kind_combo.set_selected(KINDS.index(kind))
            self._change_kind()
            self.dirty = False
        finally:
            self._syncing = False

    def _serialize(self):
        kind = KINDS[self.kind_combo.get_selected()]
        action = {"type": kind}
        if kind == "command":
            action["argv"] = shlex.split(self.entries["argv"].get_text())
        elif kind == "url":
            action["url"] = self.entries["url"].get_text().strip()
        elif kind == "script":
            action.update(path=self.entries["path"].get_text().strip(),
                          interpreter=["bash", "python3"][self.interpreter.get_selected()],
                          args=shlex.split(self.entries["args"].get_text()))
        elif kind == "hotkey":
            action["keys"] = [x for x in re.split(r"[\s,;+]+", self.entries["keys"].get_text()) if x]
        elif kind == "profile":
            action["target"] = self.entries["target"].get_text().strip()
        return {"label": self.entries["label"].get_text(),
                "image": self.entries["image"].get_text(), "action": action}

    def _work(self, operation):
        if self.busy or not self.profile:
            return
        try:
            edited = self._serialize()
        except ValueError as exc:
            self.status.set_text(f"Argumentos inválidos: {exc}")
            return
        payload = {"key_id": self.selected_key, "edited": edited, "sha256": self.profile["sha256"]}
        self.busy = True
        self.preview_btn.set_sensitive(False)
        self.save_btn.set_sensitive(False)
        self.status.set_text("Validando…" if operation == "preview" else "Validando e salvando YAML…")
        profile = self.profile_name
        def run():
            try:
                result = backend(operation, profile, payload, timeout=40)
                error = None
            except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
                result = None
                error = str(exc)
            GLib.idle_add(self._complete, operation, result, error)
        threading.Thread(target=run, name="vision02-editor-backend", daemon=True).start()

    def _complete(self, operation, result, error):
        self.busy = False
        self.preview_btn.set_sensitive(True)
        self.save_btn.set_sensitive(True)
        if error:
            self.status.set_text(f"Não foi possível {operation}: {error}")
            return False
        if operation == "preview":
            self.image_paths = {int(key): info["image"] for key, info in result["previews"].items()}
            self._draw_board()
            self.status.set_text("Prévia local atualizada. Nenhum YAML ou LCD foi alterado.")
        elif operation == "save":
            self.dirty = False
            self.apply_btn.set_sensitive(True)
            self._load_profile()
            self.status.set_text(f"YAML salvo. Backup: {result['backup']}. Clique em Aplicar ao dispositivo.")
        return False

    def _discard(self, *_):
        if self.busy:
            return
        self.dirty = False
        self._load_profile()
        self.status.set_text("Alterações locais descartadas. Perfil recarregado do disco.")

    def _confirm_apply(self, *_):
        if self.dirty:
            self.status.set_text("Há alterações não salvas. Salve o YAML antes de aplicar.")
            return
        dialog = Adw.AlertDialog(
            heading="Aplicar perfis ao dispositivo?",
            body="Os YAML serão validados e recarregados por IPC. "
                 "O perfil ativo será preservado e a conexão USB não será reiniciada.",
        )
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("apply", "Aplicar")
        dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._apply_response)
        dialog.present(self)

    def _apply_response(self, _dialog, response):
        if response != "apply" or self.busy or self.dirty:
            return
        self.busy = True
        self.apply_btn.set_sensitive(False)
        self.status.set_text("Recarregando perfis no controlador via IPC…")

        def run():
            try:
                result = subprocess.run(
                    [str(PYTHON), "-m", "vision02.cli", "control", "reload"],
                    text=True, capture_output=True, timeout=55, check=False,
                )
                if result.returncode:
                    try:
                        payload = json.loads(result.stdout)
                        error = payload.get("error") or result.stderr.strip()
                    except ValueError:
                        error = result.stderr.strip() or result.stdout.strip()
                    error = error or f"status {result.returncode}"
                else:
                    payload = json.loads(result.stdout)
                    error = None if payload.get("ok") else payload.get("error", "Falha de reload")
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                error = str(exc)
            GLib.idle_add(self._applied, error)

        threading.Thread(target=run, name="vision02-editor-apply", daemon=True).start()

    def _applied(self, error):
        self.busy = False
        if error:
            self.apply_btn.set_sensitive(True)
            self.status.set_text(f"Não foi possível aplicar os perfis: {error}")
        else:
            self.status.set_text("Perfis recarregados sem reiniciar o USB/HID.")
        return False

class EditorApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.vision02.Editor")
        self.connect("activate", self._activate)

    def _activate(self, app):
        win = self.props.active_window
        if win is None:
            try:
                win = EditorWindow(self)
            except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
                print(f"Não foi possível abrir o editor: {exc}", file=sys.stderr)
                self.quit()
                return
        win.present()


def main():
    Adw.init()
    return EditorApp().run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
