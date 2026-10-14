"""Painel GTK4/libadwaita para Vision 02; jamais abre USB/HID."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from vision02.control_ipc import request as ipc_request


class Vision02Window(Adw.ApplicationWindow):
    """Cliente IPC assíncrono. Selecionar uma tecla NÃO executa sua ação."""

    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="Rise Mode Vision 02")
        self.set_default_size(960, 730)
        self.set_size_request(700, 540)
        self._closed = False
        self._pending = False
        self._syncing_combo = False
        self._connected = False
        self._profile_names: list[str] = []
        self._current = ""
        self._selected_key = 1
        self._preview_data: dict = {}

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self._refresh_button = Gtk.Button(icon_name="view-refresh-symbolic")
        self._refresh_button.set_tooltip_text("Atualizar estado")
        self._refresh_button.connect("clicked", lambda *_: self.refresh())
        header.pack_end(self._refresh_button)
        toolbar.add_top_bar(header)
        self.set_content(toolbar)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        toolbar.set_content(scroll)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        for prop in ("margin_top", "margin_bottom", "margin_start", "margin_end"):
            setattr(content.props, prop, 24)
        scroll.set_child(content)

        title = Gtk.Label(label="Controlador de perfis")
        title.add_css_class("title-1")
        title.set_xalign(0)
        content.append(title)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        content.append(row)
        self.status_label = Gtk.Label(label="Consultando serviço…")
        self.status_label.set_xalign(0)
        self.status_label.set_hexpand(True)
        row.append(self.status_label)
        row.append(Gtk.Label(label="Perfil ativo:"))
        self.dropdown = Gtk.DropDown()
        self.dropdown.set_size_request(210, -1)
        self.dropdown.set_sensitive(False)
        self.dropdown.connect("notify::selected", self._on_selection)
        row.append(self.dropdown)

        subtitle = Gtk.Label(label="Teclas físicas (5 colunas × 3 linhas) — clique para inspecionar")
        subtitle.set_xalign(0)
        subtitle.add_css_class("dim-label")
        content.append(subtitle)

        self.grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        self.grid.set_column_homogeneous(True)
        self.grid.set_row_homogeneous(True)
        content.append(self.grid)
        self.buttons: dict[int, Gtk.Button] = {}
        for key_id in range(1, 16):
            button = Gtk.Button()
            button.set_size_request(125, 154)
            button.add_css_class("card")
            button.set_tooltip_text(f"Tecla física {key_id:02d}")
            button.connect("clicked", self._on_key, key_id)
            self.grid.attach(button, (key_id - 1) % 5, (key_id - 1) // 5, 1, 1)
            self.buttons[key_id] = button

        self.detail_label = Gtk.Label(label="Selecione uma tecla para inspecionar sua ação.")
        self.detail_label.set_xalign(0)
        self.detail_label.set_wrap(True)
        self.detail_label.add_css_class("dim-label")
        content.append(self.detail_label)

        self.warning = Gtk.Label(label="A interface apenas consulta e alterna perfis; não executa ações das teclas.")
        self.warning.set_xalign(0)
        self.warning.set_wrap(True)
        self.warning.add_css_class("caption")
        content.append(self.warning)

        self._load_previews()
        self._show_board("")
        self.refresh()
        self._poll_source = GLib.timeout_add_seconds(3, self._on_poll)
        self.connect("close-request", self._on_close)

    def _load_previews(self):
        helper = ROOT / "apps" / "vision02_gui_data.py"
        python = ROOT / ".venv" / "bin" / "python"
        try:
            result = subprocess.run(
                [str(python), str(helper), "--project", str(ROOT)],
                capture_output=True, text=True, check=True, timeout=25,
            )
            self._preview_data = json.loads(result.stdout)["profiles"]
        except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
            self._preview_data = {}
            self.warning.set_text(f"Não foi possível gerar prévias locais: {exc}")

    def _on_close(self, *_):
        self._closed = True
        if self._poll_source:
            GLib.source_remove(self._poll_source)
            self._poll_source = 0
        return False

    def _on_poll(self):
        if self._closed:
            return False
        if not self._pending:
            self.refresh()
        return True

    def refresh(self):
        self._send("status")

    def _send(self, command: str, target: str | None = None):
        if self._pending or self._closed:
            return
        self._pending = True
        self.dropdown.set_sensitive(False)
        self._refresh_button.set_sensitive(False)

        def worker():
            try:
                response = ipc_request(command, target, timeout=12)
                problem = None
            except (ConnectionError, OSError, RuntimeError, ValueError, TimeoutError) as exc:
                response = None
                problem = str(exc)
            if not self._closed:
                GLib.idle_add(self._finished, command, response, problem)

        threading.Thread(target=worker, daemon=True, name="vision02-gui-ipc").start()

    def _finished(self, command, response, problem):
        if self._closed:
            return False
        self._pending = False
        self._refresh_button.set_sensitive(True)
        if problem or not response or not response.get("ok"):
            self._connected = False
            self.dropdown.set_sensitive(False)
            self.status_label.set_text(f"Serviço indisponível: {problem or (response or {}).get('error', 'sem resposta')}")
            return False

        self._connected = bool(response.get("connected", True))
        if command == "status":
            self._profile_names = list(response.get("profiles", []))
            active = response.get("active", "")
        elif command == "switch":
            active = response.get("active", "")
        else:
            active = self._current
        self._current = active
        self._update_dropdown(active)
        self._show_board(active)
        self.status_label.set_text("● Conectada" if self._connected else "Aguardando USB…")
        self.dropdown.set_sensitive(self._connected and bool(self._profile_names))
        return False

    def _update_dropdown(self, active):
        self._syncing_combo = True
        try:
            existing = self.dropdown.get_model()
            current_names = [] if existing is None else [
                existing.get_item(i).get_string() for i in range(existing.get_n_items())
            ]
            if current_names != self._profile_names:
                self.dropdown.set_model(Gtk.StringList.new(self._profile_names))
            if active in self._profile_names:
                self.dropdown.set_selected(self._profile_names.index(active))
            else:
                self.dropdown.set_selected(Gtk.INVALID_LIST_POSITION)
        finally:
            self._syncing_combo = False

    def _on_selection(self, dropdown, _param):
        if self._syncing_combo or not self._connected or self._pending:
            return
        index = dropdown.get_selected()
        if index >= len(self._profile_names):
            return
        requested = self._profile_names[index]
        if requested != self._current:
            self.status_label.set_text(f"Ativando {requested}…")
            self._send("switch", requested)

    def _on_key(self, _button, key_id):
        self._selected_key = key_id
        self._show_details()

    def _show_board(self, active):
        keys = {
            int(item["id"]): item
            for item in self._preview_data.get(active, {}).get("keys", [])
        }
        for key_id, button in self.buttons.items():
            info = keys.get(key_id, {})
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            box.set_halign(Gtk.Align.CENTER)
            picture_path = info.get("image", "")
            if picture_path and Path(picture_path).is_file():
                picture = Gtk.Picture.new_for_file(Gio.File.new_for_path(picture_path))
                picture.set_size_request(100, 100)
                picture.set_can_shrink(True)
                picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                box.append(picture)
            else:
                placeholder = Gtk.Label(label="—")
                placeholder.set_size_request(100, 100)
                box.append(placeholder)
            caption = Gtk.Label(label=f"Tecla {key_id:02d}")
            caption.add_css_class("caption")
            box.append(caption)
            button.set_child(box)
        self._show_details()

    def _show_details(self):
        keys = self._preview_data.get(self._current, {}).get("keys", [])
        info = next((entry for entry in keys if entry["id"] == self._selected_key), None)
        if info and info["label"]:
            self.detail_label.set_text(
                f"Tecla física {self._selected_key:02d} · LCD BAT {info['display_id']:02d}"
                f"    |    {info['label']}    |    Ação: {info['action']}"
            )
        else:
            self.detail_label.set_text(f"Tecla física {self._selected_key:02d} — sem ação configurada")


class Vision02App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.vision02.Manager")
        self.connect("activate", self._activate)

    def _activate(self, app):
        win = self.props.active_window
        if win is None:
            win = Vision02Window(self)
        win.present()


def main() -> int:
    Adw.init()
    return Vision02App().run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
