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
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

KINDS = ("none", "command", "url", "script", "hotkey", "profile", "obs")
KIND_LABELS = ("Sem ação", "Comando", "URL", "Script", "Atalho", "Trocar perfil", "OBS WebSocket")


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

class IconLibraryWindow(Gtk.Window):
    """Seletor e importador de ícones; não escreve diretamente em YAML."""

    def __init__(self, parent, on_select):
        super().__init__(title="Biblioteca de ícones — Vision 02", transient_for=parent, modal=True)
        self.set_default_size(610, 520)
        self.set_destroy_with_parent(True)
        self.on_select = on_select
        self.importing = False
        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for margin in ("margin_top", "margin_bottom", "margin_start", "margin_end"):
            setattr(layout.props, margin, 16)
        self.set_child(layout)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="Ícones pessoais (100 × 100)")
        title.add_css_class("title-3")
        title.set_hexpand(True)
        title.set_xalign(0)
        header.append(title)
        self.import_btn = Gtk.Button(label="Importar imagem…")
        self.import_btn.connect("clicked", self._open_import)
        header.append(self.import_btn)
        layout.append(header)
        message = Gtk.Label(label="Clique em um ícone para usá-lo na tecla selecionada. "
                                   "A imagem só será aplicada ao dispositivo após salvar e recarregar.")
        message.set_wrap(True)
        message.set_xalign(0)
        message.add_css_class("dim-label")
        layout.append(message)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        layout.append(scroller)
        self.flow = Gtk.FlowBox()
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_max_children_per_line(4)
        self.flow.set_min_children_per_line(2)
        self.flow.set_column_spacing(12)
        self.flow.set_row_spacing(12)
        scroller.set_child(self.flow)
        self.status = Gtk.Label(label="")
        self.status.set_wrap(True)
        self.status.set_xalign(0)
        layout.append(self.status)
        self._refresh()

    def _refresh(self):
        try:
            icons = backend("icons-list")["icons"]
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            self.status.set_text(f"Falha ao consultar a biblioteca: {exc}")
            return
        while child := self.flow.get_first_child():
            self.flow.remove(child)
        for info in icons:
            tile = Gtk.Button()
            tile.set_size_request(128, 138)
            contents = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            contents.set_halign(Gtk.Align.CENTER)
            picture = Gtk.Picture.new_for_file(Gio.File.new_for_path(info["path"]))
            picture.set_size_request(96, 96)
            picture.set_content_fit(Gtk.ContentFit.CONTAIN)
            contents.append(picture)
            name = Gtk.Label(label=info["name"][:30])
            name.set_max_width_chars(14)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            contents.append(name)
            tile.set_child(contents)
            tile.set_tooltip_text(info["path"])
            tile.connect("clicked", self._select_icon, info["path"])
            self.flow.append(tile)
        self.status.set_text(f"{len(icons)} ícone(s) disponíveis. "
                             + ("Use Importar imagem para adicionar o primeiro." if not icons else ""))

    def _select_icon(self, _button, path):
        self.on_select(path)
        self.close()

    def _open_import(self, *_):
        if self.importing:
            return
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Importar imagem para a biblioteca")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        fmt = Gtk.FileFilter()
        fmt.set_name("Imagens PNG, JPEG e WEBP")
        for mime in ("image/png", "image/jpeg", "image/webp"):
            fmt.add_mime_type(mime)
        filters.append(fmt)
        dialog.set_filters(filters)
        dialog.open(self, None, self._import_chosen)

    def _import_chosen(self, dialog, result):
        try:
            chosen = dialog.open_finish(result)
        except GLib.Error as exc:
            if not exc.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                self.status.set_text(f"Erro ao escolher imagem: {exc}")
            return
        if not chosen or not chosen.get_path():
            self.status.set_text("A imagem deve ser um arquivo local.")
            return
        self.importing = True
        self.import_btn.set_sensitive(False)
        self.status.set_text("Importando e ajustando a imagem para 100 × 100…")
        def worker():
            try:
                icon = backend("icons-import", payload={"source": chosen.get_path()}, timeout=40)["icon"]
                error = None
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                icon, error = None, str(exc)
            GLib.idle_add(self._import_complete, icon, error)
        threading.Thread(target=worker, daemon=True, name="vision02-icon-import").start()

    def _import_complete(self, icon, error):
        self.importing = False
        self.import_btn.set_sensitive(True)
        if error:
            self.status.set_text(f"Erro ao importar imagem: {error}")
        else:
            self._refresh()
            self.status.set_text(f"Ícone disponível: {icon['name']}. Clique nele para selecionar.")
        return False


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
        self._live_generation = 0
        self._live_timer = None

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
        obs_btn = Gtk.Button(label="Configurar OBS")
        obs_btn.connect("clicked", self._open_obs_panel)
        top.append(obs_btn)
        profiles_btn = Gtk.Button(label="Gerenciar perfis")
        profiles_btn.connect("clicked", self._open_profiles)
        top.append(profiles_btn)
        reload_list = Gtk.Button(icon_name="view-refresh-symbolic")
        reload_list.set_tooltip_text("Atualizar lista de perfis")
        reload_list.connect("clicked", self._refresh_profiles)
        top.append(reload_list)
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
        library_btn = Gtk.Button(label="Biblioteca…")
        library_btn.set_tooltip_text("Escolher um ícone reutilizável ou importar nova imagem")
        library_btn.connect("clicked", self._open_icon_library)
        image_row.append(library_btn)
        right.append(image_row)

        self.style_frame = Gtk.Expander(label="Aparência avançada (texto, cores e posição)")
        self.style_frame.set_expanded(False)
        style_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        style_content.set_margin_top(8)
        style_content.set_margin_bottom(8)
        self.style_enabled = Gtk.CheckButton(label="Usar aparência personalizada nesta tecla")
        self.style_enabled.connect("toggled", self._style_toggled)
        style_content.append(self.style_enabled)
        self.style_fields = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        style_content.append(self.style_fields)
        self.style_text = self._entry(self.style_fields, "Texto visual (vazio usa o rótulo)")
        self.style_show_text = Gtk.CheckButton(label="Exibir texto sobre o fundo/imagem")
        self.style_show_text.connect("toggled", self._on_changed)
        self.style_fields.append(self.style_show_text)
        self.style_background = self._color_field("Cor do fundo (#RRGGBB)", "#080C16")
        self.style_text_color = self._color_field("Cor do texto (#RRGGBB)", "#F5F7FA")
        self.style_family = self._style_choice("Família da fonte", ("Sans", "Serif", "Mono"))
        self.style_weight = self._style_choice("Estilo da fonte", ("Negrito", "Normal"))
        self.style_size = self._style_spin("Tamanho da fonte", 8, 36, 18)
        self.style_horizontal = self._style_choice("Alinhamento horizontal", ("Centro", "Esquerda", "Direita"))
        self.style_vertical = self._style_choice("Alinhamento vertical", ("Centro", "Topo", "Base"))
        self.style_offset_x = self._style_spin("Deslocamento X (pixels)", -40, 40, 0)
        self.style_offset_y = self._style_spin("Deslocamento Y (pixels)", -40, 40, 0)
        self.style_fit = self._style_choice("Ajuste da imagem", ("Preencher", "Conter", "Esticar"))
        self.style_frame.set_child(style_content)
        right.append(self.style_frame)

        live_header = Gtk.Label(label="Prévia visual da tecla (100 × 100)")
        live_header.set_xalign(0)
        live_header.add_css_class("caption")
        right.append(live_header)
        self.live_picture = Gtk.Picture()
        self.live_picture.set_size_request(180, 180)
        self.live_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.live_picture.set_halign(Gtk.Align.START)
        right.append(self.live_picture)
        self.live_hint = Gtk.Label(label="A prévia não altera o YAML nem o dispositivo.")
        self.live_hint.set_xalign(0)
        self.live_hint.set_wrap(True)
        self.live_hint.add_css_class("dim-label")
        right.append(self.live_hint)

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
            ("operation", "OBS: operação (ex.: toggle_record, scene_slot)"),
            ("slot", "OBS: número da cena, de 1 a 3"),
            ("input", "OBS: nome da entrada de áudio (opcional)"),
            ("scene", "OBS: nome exato da cena (para scene_name)"),
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

    def _open_obs_panel(self, *_):
        if self.dirty:
            self.status.set_text("Salve ou descarte suas alterações antes de abrir o painel OBS.")
            return
        try:
            subprocess.Popen([str(ROOT / "scripts/vision02-obs-panel")],
                             cwd=str(ROOT), start_new_session=True)
        except OSError as exc:
            self.status.set_text(f"Falha ao abrir painel OBS: {exc}")

    def _open_profiles(self, *_):
        try:
            subprocess.Popen([str(ROOT / "scripts/vision02-profiles")], cwd=str(ROOT), start_new_session=True)
        except OSError as exc:
            self.status.set_text(f"Falha ao abrir gerenciador: {exc}")

    def _refresh_profiles(self, *_):
        if self.busy or self.dirty:
            self.status.set_text("Salve ou descarte a edição antes de atualizar a lista.")
            return
        try:
            names = backend("list")["profiles"]
            if not names:
                raise ValueError("Nenhum perfil disponível")
            self._syncing = True
            self.profile_names = names
            if self.profile_name not in names:
                self.profile_name = names[0]
            self.profile_combo.set_model(Gtk.StringList.new(names))
            self.profile_combo.set_selected(names.index(self.profile_name))
            self._syncing = False
            self._load_profile()
        except (OSError, RuntimeError, ValueError) as exc:
            self._syncing = False
            self.status.set_text(f"Falha ao atualizar perfis: {exc}")

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

    def _style_choice(self, title, labels):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        caption = Gtk.Label(label=title)
        caption.set_hexpand(True)
        caption.set_xalign(0)
        row.append(caption)
        selection = Gtk.DropDown.new_from_strings(labels)
        selection.connect("notify::selected", self._on_changed)
        row.append(selection)
        self.style_fields.append(row)
        return selection

    def _style_spin(self, title, minimum, maximum, default):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        caption = Gtk.Label(label=title)
        caption.set_xalign(0)
        caption.set_hexpand(True)
        row.append(caption)
        spinner = Gtk.SpinButton.new_with_range(minimum, maximum, 1)
        spinner.set_value(default)
        spinner.connect("value-changed", self._on_changed)
        row.append(spinner)
        self.style_fields.append(row)
        return spinner

    def _color_field(self, title, initial):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        color = self._entry(row, title)
        color.set_text(initial)
        color.set_max_length(7)
        picker = Gtk.ColorButton()
        picker.set_tooltip_text("Selecionar cor")
        picker.connect("color-set", self._color_selected, color)
        row.append(picker)
        rgba = Gdk.RGBA()
        if rgba.parse(initial):
            picker.set_rgba(rgba)
        color.connect("changed", self._update_color_button, picker)
        self.style_fields.append(row)
        return color

    def _color_selected(self, button, entry):
        color = button.get_rgba()
        entry.set_text("#{:02X}{:02X}{:02X}".format(
            round(color.red * 255), round(color.green * 255), round(color.blue * 255)))

    def _update_color_button(self, entry, picker):
        rgba = Gdk.RGBA()
        if rgba.parse(entry.get_text()) and re.fullmatch(r"#[0-9A-Fa-f]{6}", entry.get_text()):
            picker.set_rgba(rgba)

    def _style_toggled(self, *_):
        self.style_fields.set_sensitive(self.style_enabled.get_active())
        self._on_changed()

    def _style_payload(self):
        if not self.style_enabled.get_active():
            return None
        text = self.style_text.get_text()
        return {
            "background": self.style_background.get_text().strip(),
            "text_color": self.style_text_color.get_text().strip(),
            "text": text if text else None,
            "show_text": self.style_show_text.get_active(),
            "font_family": ("sans", "serif", "mono")[self.style_family.get_selected()],
            "font_weight": ("bold", "regular")[self.style_weight.get_selected()],
            "font_size": self.style_size.get_value_as_int(),
            "horizontal": ("center", "left", "right")[self.style_horizontal.get_selected()],
            "vertical": ("center", "top", "bottom")[self.style_vertical.get_selected()],
            "offset_x": self.style_offset_x.get_value_as_int(),
            "offset_y": self.style_offset_y.get_value_as_int(),
            "image_fit": ("cover", "contain", "stretch")[self.style_fit.get_selected()],
        }

    def _populate_style(self, config):
        data = config or {}
        self.style_enabled.set_active(config is not None)
        self.style_background.set_text(data.get("background", "#080C16"))
        self.style_text_color.set_text(data.get("text_color", "#F5F7FA"))
        self.style_text.set_text(data.get("text") or "")
        self.style_show_text.set_active(data.get("show_text", True))
        self.style_family.set_selected(("sans", "serif", "mono").index(data.get("font_family", "sans")))
        self.style_weight.set_selected(("bold", "regular").index(data.get("font_weight", "bold")))
        self.style_size.set_value(data.get("font_size", 18))
        self.style_horizontal.set_selected(("center", "left", "right").index(data.get("horizontal", "center")))
        self.style_vertical.set_selected(("center", "top", "bottom").index(data.get("vertical", "center")))
        self.style_offset_x.set_value(data.get("offset_x", 0))
        self.style_offset_y.set_value(data.get("offset_y", 0))
        self.style_fit.set_selected(("cover", "contain", "stretch").index(data.get("image_fit", "cover")))
        self.style_fields.set_sensitive(config is not None)
        if config is not None:
            self.style_frame.set_expanded(True)

    def _schedule_live_preview(self):
        if not self.profile or self.busy:
            return
        self._live_generation += 1
        generation = self._live_generation
        if self._live_timer is not None:
            GLib.source_remove(self._live_timer)
        self._live_timer = GLib.timeout_add(450, self._start_live_preview, generation)

    def _start_live_preview(self, generation):
        self._live_timer = None
        if generation != self._live_generation or not self.profile:
            return False
        edited = {"label": self.entries["label"].get_text(),
                  "image": self.entries["image"].get_text(),
                  "appearance": self._style_payload()}
        profile = self.profile_name
        key = self.selected_key
        def worker():
            try:
                path = backend("style-preview", profile, edited, timeout=20)["image"]
                error = None
            except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
                path, error = None, str(exc)
            GLib.idle_add(self._live_complete, generation, key, path, error)
        threading.Thread(target=worker, daemon=True, name="vision02-style-preview").start()
        return False

    def _live_complete(self, generation, key, path, error):
        if generation != self._live_generation or key != self.selected_key:
            return False
        if error:
            self.live_hint.set_text(f"Prévia indisponível: {error}")
        else:
            self.live_picture.set_file(Gio.File.new_for_path(path))
            self.live_hint.set_text("Prévia atualizada. Salve e aplique para enviar ao LCD.")
        return False

    def _on_changed(self, *_):
        if not self._syncing:
            self.dirty = True
            self.status.set_text("Alterações locais não salvas.")
            self._schedule_live_preview()

    def _change_kind(self, *_):
        kind = KINDS[self.kind_combo.get_selected()]
        showing = {
            "command": {"argv"},
            "url": {"url"},
            "script": {"path", "args"},
            "hotkey": {"keys"},
            "profile": {"target"},
            "obs": {"operation", "slot", "input", "scene"},
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

    def _open_icon_library(self, *_):
        if self.busy or not self.profile:
            return
        chooser = IconLibraryWindow(self, self._choose_library_icon)
        chooser.present()

    def _choose_library_icon(self, path):
        self.entries["image"].set_text(path)
        self.image_paths[self.selected_key] = path
        self._draw_board()
        self.status.set_text("Ícone selecionado. Configure rótulo e ação, pré-visualize e salve o YAML.")

    def _highlight_selected(self):
        for number, button in self.key_buttons.items():
            if number == self.selected_key:
                button.add_css_class("suggested-action")
            else:
                button.remove_css_class("suggested-action")

    def _on_key_selected(self, _, key_id):
        if self.busy or key_id == self.selected_key:
            return
        if self.dirty:
            self.status.set_text("Salve ou descarte a edição antes de trocar de tecla.")
            return
        self.selected_key = key_id
        self._populate_form()
        self._highlight_selected()
        self._schedule_live_preview()

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
            self._schedule_live_preview()
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
            current_label = self.profile["keys"].get(str(physical), {}).get("label", "") if self.profile else ""
            label = Gtk.Label(label=f"{physical:02d} · {current_label}" if current_label else f"Tecla {physical:02d}")
            label.add_css_class("caption")
            label.set_max_width_chars(13)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            box.append(label)
            btn.set_child(box)
            btn.set_tooltip_text(f"Tecla física {physical:02d}: {current_label or 'sem ação'}")
        self._highlight_selected()

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
            self.entries["operation"].set_text(action.get("operation", "") or "")
            self.entries["slot"].set_text(str(action.get("slot") or ""))
            self.entries["input"].set_text(action.get("input", "") or "")
            self.entries["scene"].set_text(action.get("scene", "") or "")
            self.interpreter.set_selected(0 if action.get("interpreter", "bash") == "bash" else 1)
            self.kind_combo.set_selected(KINDS.index(kind))
            self._change_kind()
            self._populate_style(cfg.get("appearance"))
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
        elif kind == "obs":
            action["operation"] = self.entries["operation"].get_text().strip()
            raw_slot = self.entries["slot"].get_text().strip()
            if raw_slot:
                action["slot"] = int(raw_slot)
            raw_input = self.entries["input"].get_text().strip()
            if raw_input:
                action["input"] = raw_input
            raw_scene = self.entries["scene"].get_text().strip()
            if raw_scene:
                action["scene"] = raw_scene
        return {"label": self.entries["label"].get_text(),
                "image": self.entries["image"].get_text(), "action": action,
                "appearance": self._style_payload()}

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
