"""Vision 02 Studio — painel central GTK4/libadwaita, sem USB/HID próprio.

Ações operacionais continuam no serviço; edição avançada abre as ferramentas
GTK consolidadas, evitando duplicar lógica crítica de gravação e validação.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv/bin/python'
BACKEND = ROOT / 'apps/vision02_studio_backend.py'

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

from vision02.editor_navigation import editor_args
from vision02.studio_interaction import DoubleClickDetector
from vision02.studio_inline_edit import KINDS, HINTS, key_to_form
from vision02.studio_icon_gallery import filtered_icons, icon_by_path
from vision02.studio_visual_style import CHOICES, INT_RANGES, IMAGE_RANGES, COLORS, ui_appearance, validated_appearance, hex_from_rgb
from vision02.studio_composition import clamp_drag, grid_coordinate
from vision02_studio_layout import (
    MIN_SIDEBAR_WIDTH, load_sidebar_width, save_sidebar_width,
)

TOOLS = {
    'teclas': 'vision02-editor',
    'perfis': 'vision02-profiles',
    'obs': 'vision02-obs-panel',
    'obs_profil': 'vision02-obs-profiles',
    'obs_visual': 'vision02-obs-visual',
    'dashboard': 'vision02-gui',
}


def _label(text: str, *, style: str = '', wrap: bool = False) -> Gtk.Label:
    obj = Gtk.Label(label=text, xalign=0)
    obj.set_wrap(wrap)
    if style:
        obj.add_css_class(style)
    return obj


def _button(parent, title: str, callback, *, sensitive=True):
    button = Gtk.Button(label=title)
    button.set_sensitive(sensitive)
    button.connect('clicked', callback)
    parent.append(button)
    return button


def _box(horizontal=False, spacing=10):
    return Gtk.Box(orientation=(Gtk.Orientation.HORIZONTAL if horizontal
                                else Gtk.Orientation.VERTICAL), spacing=spacing)


class StudioWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='Vision 02 Studio')
        self.set_default_size(1180, 780)
        self.set_resizable(True)
        self.set_size_request(820, 560)
        self._closed = False
        self._busy = set()
        self._profiles = []
        self._current = ''
        self._connected = False
        self._previews = {}
        self._live_images = {}
        self._live_active = ''
        self._live_revision = -1
        self._selected_key = 1
        self._physical_pressed = set()
        self._last_physical = None
        self._click_detector = DoubleClickDetector(interval_seconds=0.60)
        self._key_number_labels = {}
        self._key_status_labels = {}
        self._key_highlight_css = None
        self._quick_loaded = None
        self._quick_dirty = False
        self._quick_updating = False
        self._quick_saved = False
        self._icons = []
        self._quick_icon_buttons = {}
        self._quick_import_target = None
        self._quick_preview_snapshot = None
        self._quick_preview_queued = False
        self._style_preview_timer = 0
        self._style_color_syncing = False
        self._composition_pixbuf = None
        self._composition_drag_start = (0, 0)
        self._syncing = False
        self._sidebar_save_timer = 0

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.top_status = _label('Consultando Vision 02…', style='caption')
        header.pack_start(self.top_status)
        refresh = Gtk.Button(icon_name='view-refresh-symbolic')
        refresh.set_tooltip_text('Atualizar dados da página atual')
        refresh.connect('clicked', self._refresh_current)
        header.pack_end(refresh)
        toolbar.add_top_bar(header)
        self.set_content(toolbar)

        # A divisória é controlada pelo usuário, não por uma largura fixa.
        # O StackSidebar precisa preencher a altura para não ocultar páginas.
        self.navigation = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        self.navigation.set_wide_handle(True)
        self.navigation.set_resize_start_child(False)
        self.navigation.set_shrink_start_child(False)
        self.navigation.set_resize_end_child(True)
        self.navigation.set_shrink_end_child(False)
        toolbar.set_content(self.navigation)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(self.stack)
        sidebar.set_hexpand(True)
        sidebar.set_vexpand(True)
        sidebar.set_valign(Gtk.Align.FILL)
        side_frame = _box(False)
        side_frame.set_size_request(MIN_SIDEBAR_WIDTH, -1)
        side_frame.set_vexpand(True)
        side_frame.set_margin_top(18)
        side_frame.set_margin_start(14)
        side_frame.set_margin_end(12)
        side_frame.append(_label('VISION 02', style='title-3'))
        side_frame.append(sidebar)
        self.navigation.set_start_child(side_frame)
        self.navigation.set_end_child(self.stack)
        self.navigation.set_position(load_sidebar_width())
        self.navigation.connect('notify::position', self._sidebar_position_changed)

        self._build_dashboard()
        self._install_key_highlight_css()
        self._build_keys()
        self._build_profiles()
        self._build_icons()
        self._build_system()
        self._build_obs()
        self._build_settings()
        self.stack.connect('notify::visible-child-name', self._on_page)
        self.stack.set_visible_child_name('dashboard')

        self._call('status')
        self._call('previews')
        self._call('live_preview')
        self._call('icons')
        self._timer = GLib.timeout_add_seconds(4, self._tick)
        self._preview_timer = GLib.timeout_add_seconds(2, self._preview_tick)
        self._activity_timer = GLib.timeout_add(650, self._activity_tick)
        self.connect('close-request', self._on_close)

    def _page(self, key, title, description):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        frame = _box(False, 16)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(frame, 'set_margin_' + side)(22)
        scroll.set_child(frame)
        frame.append(_label(title, style='title-1'))
        frame.append(_label(description, style='dim-label', wrap=True))
        self.stack.add_titled(scroll, key, title)
        return frame

    def _build_dashboard(self):
        page = self._page('dashboard', 'Dashboard',
                          'Visão geral da conexão, do perfil em uso e dos recursos disponíveis.')
        self.dashboard_state = _label('Aguardando resposta do serviço…', style='title-3')
        page.append(self.dashboard_state)
        self.dashboard_profiles = _label('Perfis: —')
        page.append(self.dashboard_profiles)
        shortcuts = _box(True)
        page.append(shortcuts)
        _button(shortcuts, 'Editar teclas', lambda *_: self._launch('teclas'))
        _button(shortcuts, 'Gerenciar perfis', lambda *_: self._launch('perfis'))
        _button(shortcuts, 'Painel OBS', lambda *_: self._launch('obs'))
        _button(shortcuts, 'Editor de cenas e áudio', lambda *_: self._launch('obs_visual'))
        page.append(_label('Ações das teclas são executadas somente pelo serviço Vision 02. '
                           'O Studio consulta o IPC, não abre o dispositivo HID.',
                           style='caption', wrap=True))

    def _install_key_highlight_css(self):
        """Destaque explícito, independente do tema Adwaita/card do botão."""
        display = Gdk.Display.get_default()
        if display is None:
            return
        provider = Gtk.CssProvider()
        provider.load_from_data(b"""
            button.vision02-key-selected {
                border: 2px solid #3584e4;
            }
            button.vision02-key-pressed {
                border: 4px solid #e5a327;
                background-color: rgba(229, 163, 39, 0.25);
            }
            label.vision02-key-status-active {
                color: #e5a327;
                font-weight: bold;
            }
            button.vision02-icon-selected {
                border: 3px solid #3584e4;
                background-color: rgba(53, 132, 228, 0.10);
            }
            frame.vision02-composition-surface {
                background-color: #101723;
                border: 2px solid #3584e4;
                border-radius: 8px;
            }
        """)
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self._key_highlight_css = provider

    def _build_keys(self):
        page = self._page('keys', 'Teclas',
                          'Espelho dos 15 LCDs: imagem enviada pelo serviço, atualizada a cada 2 segundos. '
                          'Clique para selecionar; clique duas vezes para editar. Nenhuma ação física é executada.')
        row = _box(True)
        page.append(row)
        row.append(_label('Perfil:'))
        self.profile_combo = Gtk.DropDown()
        self.profile_combo.set_size_request(245, -1)
        self.profile_combo.connect('notify::selected', self._profile_selected)
        row.append(self.profile_combo)
        _button(row, 'Atualizar prévias', lambda *_: self._call('previews'))
        _button(row, 'Editar tecla selecionada', self._edit_selected_key)
        # A grade pode rolar horizontalmente em janelas pequenas; as propriedades
        # ficam disponíveis numa segunda coluna, sem comprimir os 15 LCDs.
        editor_split = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        editor_split.set_wide_handle(True)
        editor_split.set_position(665)
        editor_split.set_resize_start_child(True)
        editor_split.set_resize_end_child(False)
        editor_split.set_shrink_start_child(False)
        editor_split.set_shrink_end_child(False)
        editor_split.set_vexpand(True)
        page.append(editor_split)
        key_scroll = Gtk.ScrolledWindow()
        key_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        key_scroll.set_min_content_height(510)
        grid_box = _box(False, 12)
        key_scroll.set_child(grid_box)
        editor_split.set_start_child(key_scroll)
        self.key_grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        self.key_grid.set_column_homogeneous(True)
        grid_box.append(self.key_grid)
        self.key_activity_label = _label('Pressione uma tecla física para verificar o destaque.', wrap=True)
        grid_box.append(self.key_activity_label)
        self.key_detail = _label('Selecione uma tecla.', wrap=True)
        grid_box.append(self.key_detail)
        self._build_quick_properties(editor_split)
        self.key_buttons = {}
        for ident in range(1, 16):
            button = Gtk.Button()
            button.add_css_class('card')
            button.set_size_request(117, 142)
            button.connect('clicked', self._key_selected, ident)
            self.key_grid.attach(button, (ident - 1) % 5, (ident - 1) // 5, 1, 1)
            self.key_buttons[ident] = button
        self._render_keys()

    def _build_quick_properties(self, editor_split):
        props_scroll = Gtk.ScrolledWindow()
        props_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        props_scroll.set_min_content_width(295)
        box = _box(False, 9)
        box.set_margin_start(14)
        box.set_margin_end(10)
        box.set_margin_top(6)
        box.set_margin_bottom(16)
        props_scroll.set_child(box)
        editor_split.set_end_child(props_scroll)
        box.append(_label('Propriedades da tecla', style='title-3'))
        self.quick_target = _label('Selecione uma tecla para editar.', wrap=True)
        box.append(self.quick_target)
        box.append(_label('Rótulo'))
        self.quick_label = Gtk.Entry()
        box.append(self.quick_label)
        box.append(_label('Texto visual no LCD (opcional)'))
        self.quick_visual_text = Gtk.Entry()
        self.quick_visual_text.set_placeholder_text('Vazio: usa o rótulo da tecla')
        box.append(self.quick_visual_text)
        box.append(_label('Imagem (caminho local)'))
        self.quick_image = Gtk.Entry()
        box.append(self.quick_image)
        # Galeria embutida: usa os mesmos registros da página Ícones,
        # mas seleciona diretamente o caminho da tecla em edição.
        gallery = Gtk.Expander(label='Galeria visual de ícones')
        gallery.set_expanded(True)
        box.append(gallery)
        gallery_box = _box(False, 7)
        gallery.set_child(gallery_box)
        self.quick_icon_search = Gtk.SearchEntry()
        self.quick_icon_search.set_placeholder_text('Pesquisar por nome (ex.: OBS, Grafana)')
        self.quick_icon_search.connect('search-changed', lambda *_: self._render_quick_icons())
        gallery_box.append(self.quick_icon_search)
        self.quick_icon_count = _label('Aguardando biblioteca…', style='caption')
        gallery_box.append(self.quick_icon_count)
        gallery_scroll = Gtk.ScrolledWindow()
        gallery_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        gallery_scroll.set_min_content_height(200)
        gallery_scroll.set_size_request(-1, 220)
        gallery_box.append(gallery_scroll)
        self.quick_icon_flow = Gtk.FlowBox()
        self.quick_icon_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.quick_icon_flow.set_max_children_per_line(3)
        self.quick_icon_flow.set_row_spacing(5)
        self.quick_icon_flow.set_column_spacing(5)
        gallery_scroll.set_child(self.quick_icon_flow)
        self.quick_import_icon_btn = _button(
            gallery_box, 'Importar imagem para a galeria…',
            lambda *_: self._choose_icon(for_quick=True)
        )
        gallery_box.append(_label('Um clique escolhe o ícone e gera uma prévia local. '
                                  'Para alterar o LCD: Salvar YAML → Aplicar IPC.',
                                  style='caption', wrap=True))
        self._build_visual_style(box)
        box.append(_label('Ação'))
        self.quick_kind = Gtk.DropDown.new_from_strings(
            ['Sem ação (limpar)', 'Comando', 'URL', 'Script', 'Atalho', 'Trocar perfil', 'OBS']
        )
        box.append(self.quick_kind)
        self.quick_hint = _label('', style='caption', wrap=True)
        box.append(self.quick_hint)
        self.quick_fields = []
        for idx in range(4):
            entry = Gtk.Entry()
            entry.set_placeholder_text(f'Campo {idx + 1}')
            self.quick_fields.append(entry)
            box.append(entry)
        self.quick_kind.connect('notify::selected', self._quick_kind_changed)
        for entry in (self.quick_label, self.quick_visual_text, self.quick_image, *self.quick_fields):
            entry.connect('changed', self._quick_changed)
        self.quick_state = _label('Aguardando seleção…', wrap=True)
        box.append(self.quick_state)
        self.quick_picture = Gtk.Picture()
        self.quick_picture.set_size_request(100, 100)
        self.quick_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        box.append(self.quick_picture)
        self._build_composition_canvas(box)

        btns = _box(False, 6)
        box.append(btns)
        self.quick_preview_btn = _button(btns, 'Pré-visualizar (local)', self._quick_preview)
        self.quick_save_btn = _button(btns, 'Salvar YAML com backup', self._quick_save)
        self.quick_apply_btn = _button(btns, 'Aplicar ao dispositivo (IPC)', self._quick_apply)
        _button(btns, 'Descartar edição / recarregar', self._quick_discard)
        _button(box, 'Editor avançado de aparência…', self._edit_selected_key)
        box.append(_label('Salvar não aplica automaticamente. Nenhum clique aqui executa ações. '
                          'Fontes e deslocamentos são renderizados localmente antes de salvar.',
                          style='caption', wrap=True))
        self._quick_kind_changed()
        self._quick_controls()

    def _build_composition_canvas(self, parent):
        group = Gtk.Expander(label='Composição — arrastar texto ou imagem')
        group.set_expanded(True)
        parent.append(group)
        column = _box(False, 6)
        column.set_margin_top(8)
        group.set_child(column)
        column.append(_label('A prévia ampliada é carregada automaticamente ao selecionar a tecla. '
                             'Arraste dentro da borda azul para editar a posição.',
                             wrap=True, style='caption'))
        self.composition_target = Gtk.DropDown.new_from_strings(['Imagem', 'Texto'])
        column.append(self.composition_target)
        self.composition_grid = Gtk.CheckButton(label='Encaixar na grade de 5 pixels')
        column.append(self.composition_grid)

        # O Gtk.Picture é responsável por mostrar o PNG; o DrawingArea só
        # desenha guias transparentes. Isso evita uma tela vazia quando o
        # suporte cairo/GdkPixbuf não está disponível no runtime GTK.
        frame = Gtk.Frame()
        frame.add_css_class('vision02-composition-surface')
        frame.set_halign(Gtk.Align.CENTER)
        frame.set_size_request(256, 256)
        column.append(frame)
        self.composition_surface = Gtk.Overlay()
        self.composition_surface.set_size_request(248, 248)
        frame.set_child(self.composition_surface)
        self.composition_picture = Gtk.Picture()
        self.composition_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.composition_picture.set_size_request(240, 240)
        self.composition_surface.set_child(self.composition_picture)
        self.composition_canvas = Gtk.DrawingArea()
        self.composition_canvas.set_content_width(240)
        self.composition_canvas.set_content_height(240)
        self.composition_canvas.set_can_target(False)
        self.composition_canvas.set_draw_func(self._composition_draw)
        self.composition_surface.add_overlay(self.composition_canvas)
        gesture = Gtk.GestureDrag.new()
        gesture.connect('drag-begin', self._composition_drag_begin)
        gesture.connect('drag-update', self._composition_drag_update)
        self.composition_surface.add_controller(gesture)
        self.composition_status = _label('Aguardando prévia local da tecla selecionada.',
                                         style='caption', wrap=True)
        column.append(self.composition_status)
        column.append(_label('Imagem: posição e escala nos controles Aparência visual. '
                             'Texto: desloque diretamente, com os limites atuais de ±40 px. '
                             'Arrastar ativa a aparência personalizada.', wrap=True,
                             style='caption'))

    def _composition_draw(self, _area, cr, width, height):
        # Camada TRANSPARENTE: Gtk.Picture apresenta a imagem abaixo das guias.
        extent = min(width, height)
        origin_x, origin_y = (width - extent) / 2, (height - extent) / 2
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.32)
        cr.set_line_width(1)
        for point in (25, 50, 75):
            coordinate = point * extent / 100
            cr.move_to(origin_x + coordinate, origin_y)
            cr.line_to(origin_x + coordinate, origin_y + extent)
            cr.move_to(origin_x, origin_y + coordinate)
            cr.line_to(origin_x + extent, origin_y + coordinate)
        cr.stroke()

    def _composition_drag_begin(self, *_):
        if self._quick_loaded is None or 'quick_save' in self._busy:
            self.composition_status.set_text('Selecione uma tecla e aguarde suas propriedades.')
            return
        if not self.style_enabled.get_active():
            # Não descartar um gesto porque a seção Aparência está recolhida.
            # A alteração é apenas local até Salvar YAML / Aplicar IPC.
            self.style_enabled.set_active(True)
        target = ('image_x', 'image_y') if self.composition_target.get_selected() == 0 else ('offset_x', 'offset_y')
        self._composition_drag_start = tuple(int(self.style_numbers[field].get_value()) for field in target)
        self.composition_status.set_text('Arrastando ' + ('imagem' if target[0] == 'image_x' else 'texto') + '…')

    def _composition_drag_update(self, _gesture, offset_x, offset_y):
        if self._quick_loaded is None or 'quick_save' in self._busy or not self.style_enabled.get_active():
            return
        target = ('image_x', 'image_y') if self.composition_target.get_selected() == 0 else ('offset_x', 'offset_y')
        extent = min(self.composition_canvas.get_width(), self.composition_canvas.get_height())
        if extent <= 0:
            self.composition_status.set_text('Área de composição indisponível; amplie a janela.')
            return
        snap = bool(self.composition_grid.get_active())
        result = []
        for index, (field, diff) in enumerate(zip(target, (offset_x, offset_y))):
            lower, upper = ({**INT_RANGES, **IMAGE_RANGES})[field]
            value = clamp_drag(self._composition_drag_start[index], diff, extent / 100, lower, upper)
            if snap:
                value = grid_coordinate(value, lower, upper)
            self.style_numbers[field].set_value(value)
            result.append(value)
        self.composition_status.set_text(
            ('Imagem' if target[0] == 'image_x' else 'Texto') +
            f': X={result[0]} px, Y={result[1]} px — prévia sendo atualizada.'
        )

    def _style_color_field(self, parent, title, name):
        row = _box(True, 6)
        parent.append(row)
        row.append(_label(title))
        entry = Gtk.Entry()
        entry.set_width_chars(9)
        entry.set_max_length(7)
        row.append(entry)
        self.style_colors[name] = entry
        # Gtk.ColorDialogButton is preferred on GTK >= 4.10; older Ubuntu
        # versions use ColorButton, with the same explicit RGB text field.
        if hasattr(Gtk, 'ColorDialogButton') and hasattr(Gtk, 'ColorDialog'):
            picker = Gtk.ColorDialogButton.new(Gtk.ColorDialog.new())
            picker.connect('notify::rgba', self._color_picker_changed, name)
        else:
            picker = Gtk.ColorButton()
            picker.connect('color-set', self._color_picker_changed, name)
        row.append(picker)
        self.style_pickers[name] = picker
        entry.connect('changed', self._color_entry_changed, name)

    def _build_visual_style(self, parent):
        expander = Gtk.Expander(label='Aparência visual — fontes, cores e posição')
        expander.set_expanded(False)
        parent.append(expander)
        controls = _box(False, 8)
        controls.set_margin_top(8)
        controls.set_margin_bottom(10)
        expander.set_child(controls)
        self.style_enabled = Gtk.CheckButton(label='Usar aparência personalizada')
        controls.append(self.style_enabled)
        self.style_options = _box(False, 7)
        controls.append(self.style_options)
        self.style_colors = {}
        self.style_pickers = {}
        for name, title in (('background', 'Fundo'), ('text_color', 'Texto')):
            self._style_color_field(self.style_options, title, name)
        self.style_choices = {}
        labels = {
            'font_family': ('Família da fonte', ('Sans', 'Serif', 'Mono')),
            'font_weight': ('Peso', ('Normal', 'Negrito')),
            'horizontal': ('Texto horizontal', ('Esquerda', 'Centro', 'Direita')),
            'vertical': ('Texto vertical', ('Topo', 'Centro', 'Base')),
            'image_fit': ('Imagem', ('Preencher', 'Conter', 'Esticar')),
        }
        for name, (title, captions) in labels.items():
            self.style_options.append(_label(title))
            widget = Gtk.DropDown.new_from_strings(list(captions))
            self.style_options.append(widget)
            widget.connect('notify::selected', self._visual_style_changed)
            self.style_choices[name] = widget
        self.style_numbers = {}
        names = {'font_size': 'Tamanho da fonte (8–36)',
                 'offset_x': 'Deslocamento X do texto (px)',
                 'offset_y': 'Deslocamento Y do texto (px)',
                 'image_x': 'Imagem: posição X (px)',
                 'image_y': 'Imagem: posição Y (px)',
                 'image_scale': 'Imagem: tamanho (%)'}
        for name, (minimum, maximum) in {**INT_RANGES, **IMAGE_RANGES}.items():
            self.style_options.append(_label(names[name]))
            spin = Gtk.SpinButton.new_with_range(minimum, maximum, 1)
            spin.set_numeric(True)
            spin.connect('value-changed', self._visual_style_changed)
            self.style_options.append(spin)
            self.style_numbers[name] = spin
        self.style_show_text = Gtk.CheckButton(label='Exibir texto sobre imagem/fundo')
        self.style_show_text.connect('toggled', self._visual_style_changed)
        self.style_options.append(self.style_show_text)
        self.style_enabled.connect('toggled', self._visual_style_changed)
        controls.append(_label('Imagem: escala de 25% a 200%, posição X/Y de −100 a +100 px. '
                               'Texto: deslocamento X/Y de −40 a +40 px.',
                               wrap=True, style='caption'))
        controls.append(_label('A prévia é gerada automaticamente após a edição; '
                               'Salvar YAML e Aplicar IPC continuam separados.',
                               wrap=True, style='caption'))

    def _color_picker_changed(self, picker, _param_or_name, maybe_name=None):
        # For notify::rgba the callback has (widget, pspec, name); for
        # color-set it has (widget, name).
        name = maybe_name if maybe_name is not None else _param_or_name
        if self._style_color_syncing or self._quick_updating:
            return
        rgba = picker.get_rgba()
        value = hex_from_rgb(rgba.red, rgba.green, rgba.blue)
        self.style_colors[name].set_text(value)

    def _color_entry_changed(self, entry, name):
        if self._style_color_syncing or self._quick_updating:
            return
        value = entry.get_text()
        if len(value) == 7 and value.startswith('#'):
            rgba = Gdk.RGBA()
            if rgba.parse(value):
                self._style_color_syncing = True
                try:
                    self.style_pickers[name].set_rgba(rgba)
                finally:
                    self._style_color_syncing = False
        self._visual_style_changed()

    def _set_visual_style(self, raw):
        style = ui_appearance(raw)
        self.style_enabled.set_active(raw is not None)
        self._style_color_syncing = True
        try:
            for name, entry in self.style_colors.items():
                value = style[name]
                entry.set_text(value)
                rgba = Gdk.RGBA()
                rgba.parse(value)
                self.style_pickers[name].set_rgba(rgba)
        finally:
            self._style_color_syncing = False
        for name, widget in self.style_choices.items():
            widget.set_selected(CHOICES[name].index(style[name]))
        for name, widget in self.style_numbers.items():
            widget.set_value(style[name])
        self.style_show_text.set_active(style['show_text'])
        self._update_style_sensitivity()

    def _read_visual_style(self):
        fields = {name: entry.get_text() for name, entry in self.style_colors.items()}
        fields.update({name: CHOICES[name][widget.get_selected()]
                       for name, widget in self.style_choices.items()})
        fields.update({name: int(widget.get_value())
                       for name, widget in self.style_numbers.items()})
        fields['show_text'] = self.style_show_text.get_active()
        return validated_appearance(self.style_enabled.get_active(), fields)

    def _update_style_sensitivity(self):
        active = (self._quick_loaded is not None and self.style_enabled.get_active()
                  and 'quick_save' not in self._busy)
        self.style_options.set_sensitive(active)
        self.style_enabled.set_sensitive(self._quick_loaded is not None and 'quick_save' not in self._busy)

    def _visual_style_changed(self, *_):
        self._update_style_sensitivity()
        if self._quick_updating or self._quick_loaded is None:
            return
        self._quick_changed()
        if self._style_preview_timer:
            GLib.source_remove(self._style_preview_timer)
        self._style_preview_timer = GLib.timeout_add(600, self._style_preview_delayed)

    def _style_preview_delayed(self):
        self._style_preview_timer = 0
        if self._quick_loaded and self.stack.get_visible_child_name() == 'keys':
            self._quick_preview()
        return False

    def _quick_controls(self):
        loaded = self._quick_loaded is not None
        for widget in (self.quick_label, self.quick_visual_text, self.quick_image, self.quick_kind, *self.quick_fields):
            widget.set_sensitive(loaded and 'quick_save' not in self._busy)
        busy = 'quick_save' in self._busy or 'quick_preview' in self._busy
        self.quick_preview_btn.set_sensitive(loaded and not busy)
        self.quick_save_btn.set_sensitive(loaded and not busy)
        self.quick_apply_btn.set_sensitive(loaded and self._quick_saved and not self._quick_dirty and not busy)
        self._update_style_sensitivity()
        self.quick_icon_flow.set_sensitive(loaded and 'quick_save' not in self._busy)
        self.quick_import_icon_btn.set_sensitive('import_icon' not in self._busy and 'quick_save' not in self._busy)

    def _quick_kind_changed(self, *_):
        kind = KINDS[self.quick_kind.get_selected()]
        self.quick_hint.set_text(HINTS[kind])
        count = {'none': 0, 'command': 1, 'url': 1, 'hotkey': 1,
                 'profile': 1, 'script': 3, 'obs': 4}[kind]
        for i, field in enumerate(self.quick_fields):
            field.set_visible(i < count)
        self._quick_changed()

    def _quick_changed(self, *_):
        if self._quick_updating or self._quick_loaded is None:
            return
        self._quick_dirty = True
        self._quick_saved = False
        self.quick_state.set_text('Alterações não salvas — use Pré-visualizar e Salvar YAML.')
        self._update_quick_icon_selection()
        self._quick_controls()

    def _quick_form(self):
        return {'label': self.quick_label.get_text(), 'image': self.quick_image.get_text(),
                'visual_text': self.quick_visual_text.get_text(),
                'kind': KINDS[self.quick_kind.get_selected()],
                'fields': [entry.get_text() for entry in self.quick_fields],
                'appearance': self._read_visual_style()}

    def _quick_load(self):
        if not self._current:
            return
        self._quick_preview_snapshot = None
        self._quick_preview_queued = False
        if self._style_preview_timer:
            GLib.source_remove(self._style_preview_timer)
            self._style_preview_timer = 0
        if self._quick_dirty:
            self.quick_state.set_text('Há alterações não salvas. Salve ou descarte antes de trocar de tecla.')
            return
        self._quick_loaded = None
        self._quick_saved = False
        self._composition_pixbuf = None
        self.composition_picture.set_paintable(None)
        self.composition_canvas.queue_draw()
        self.composition_status.set_text('Aguardando prévia da tecla selecionada…')
        if self._live_active == self._current:
            live = self._live_images.get(str(self._selected_key)) or self._live_images.get(self._selected_key)
            if live and Path(live).is_file():
                self.composition_picture.set_file(Gio.File.new_for_path(live))
                self.composition_status.set_text('Espelho do LCD; gerando prévia editável…')
        self.quick_target.set_text(f'{self._current} · tecla física {self._selected_key:02d}')
        self.quick_state.set_text('Carregando propriedades…')
        self._quick_controls()
        self._call('quick_inspect', profile=self._current, key_id=self._selected_key)

    def _quick_discard(self, *_):
        self._quick_dirty = False
        self._quick_loaded = None
        self._quick_load()

    def _update_quick_icon_selection(self):
        """Realça a miniatura vinculada ao caminho atual, sem recriar botões."""
        selected = self.quick_image.get_text()
        for path, button in self._quick_icon_buttons.items():
            if path == selected:
                button.add_css_class('vision02-icon-selected')
            else:
                button.remove_css_class('vision02-icon-selected')

    def _quick_pick_icon(self, _button, path):
        if self._quick_loaded is None:
            self.quick_state.set_text('Primeiro selecione uma tecla para editar.')
            return
        if 'quick_save' in self._busy:
            self.quick_state.set_text('Aguarde o salvamento em andamento.')
            return
        if icon_by_path(self._icons, path) is None:
            self.quick_state.set_text('Ícone indisponível: atualize a biblioteca.')
            return
        self.quick_image.set_text(path)
        # Renderização local: não modifica YAML nem executa ações HID.
        self._quick_preview()

    def _render_quick_icons(self):
        needle = self.quick_icon_search.get_text()
        matching = filtered_icons(self._icons, needle)
        self.quick_icon_count.set_text(
            f'{len(matching)} miniaturas exibidas / {len(self._icons)} na biblioteca'
            + (' (refine a pesquisa)' if len(matching) == 90 else '')
        )
        child = self.quick_icon_flow.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.quick_icon_flow.remove(child)
            child = following
        self._quick_icon_buttons = {}
        for icon in matching:
            path = icon['path']
            if not Path(path).is_file():
                continue
            button = Gtk.Button()
            button.add_css_class('flat')
            button.set_tooltip_text(icon['name'])
            contents = _box(False, 3)
            contents.set_halign(Gtk.Align.CENTER)
            picture = Gtk.Picture.new_for_file(Gio.File.new_for_path(path))
            picture.set_size_request(66, 66)
            picture.set_content_fit(Gtk.ContentFit.CONTAIN)
            contents.append(picture)
            title = _label(icon['name'])
            title.set_max_width_chars(11)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            title.set_halign(Gtk.Align.CENTER)
            contents.append(title)
            button.set_child(contents)
            button.connect('clicked', self._quick_pick_icon, path)
            self.quick_icon_flow.insert(button, -1)
            self._quick_icon_buttons[path] = button
        self._update_quick_icon_selection()

    def _quick_preview(self, *_):
        if self._style_preview_timer:
            GLib.source_remove(self._style_preview_timer)
            self._style_preview_timer = 0
        if not self._quick_loaded:
            return
        try:
            form = self._quick_form()
        except ValueError as exc:
            self.quick_state.set_text(str(exc)); return
        if 'quick_preview' in self._busy:
            # Vários cliques rápidos: descarta resultados antigos e gera
            # a prévia final quando a primeira consulta terminar.
            self._quick_preview_queued = True
            self.quick_state.set_text('Aguardando prévia atualizada…')
            return
        self._quick_preview_snapshot = (
            self._quick_loaded['profile'], self._quick_loaded['key_id'], form,
        )
        self._quick_preview_queued = False
        self._call('quick_preview', profile=self._quick_loaded['profile'],
                   key_id=self._quick_loaded['key_id'], sha256=self._quick_loaded['sha256'],
                   form=form)
        self.quick_state.set_text('Gerando prévia local…')

    def _quick_save(self, *_):
        if not self._quick_loaded:
            return
        try:
            form = self._quick_form()
        except ValueError as exc:
            self.quick_state.set_text(str(exc))
            return
        if self._style_preview_timer:
            GLib.source_remove(self._style_preview_timer)
            self._style_preview_timer = 0
        self._call('quick_save', profile=self._quick_loaded['profile'],
                   key_id=self._quick_loaded['key_id'], sha256=self._quick_loaded['sha256'],
                   form=form)
        self.quick_state.set_text('Validando YAML e salvando com backup…')
        self._quick_controls()

    def _quick_apply(self, *_):
        if self._quick_saved and not self._quick_dirty:
            self._call('reload')
            self.quick_state.set_text('Aplicando configuração ao dispositivo via IPC…')

    def _quick_received(self, command, response):
        if command == 'quick_inspect':
            if response['profile'] != self._current or response['key_id'] != self._selected_key:
                # Usuário trocou tecla durante a consulta anterior.
                self._quick_load()
                return
            self._quick_loaded = response
            self._quick_updating = True
            try:
                data = key_to_form(response['edited'])
                self.quick_label.set_text(data['label'])
                self.quick_visual_text.set_text(data['visual_text'])
                self.quick_image.set_text(data['image'])
                self._set_visual_style(response['edited'].get('appearance'))
                self._update_quick_icon_selection()
                self.quick_kind.set_selected(KINDS.index(data['kind']))
                for entry, value in zip(self.quick_fields, data['fields']):
                    entry.set_text(value)
            finally:
                self._quick_updating = False
            self._quick_dirty = False
            self._quick_saved = False
            self.quick_state.set_text('Pronta para editar. Alterações só são salvas ao clicar em Salvar YAML.')
            # Prévia local automática ao selecionar a tecla, não exige
            # clicar em um botão oculto na parte inferior do painel.
            self._quick_preview()
        elif command == 'quick_preview':
            if not self._quick_loaded:
                return
            try:
                form = self._quick_form()
            except ValueError:
                # Formulário alterado durante a requisição: não exibir prévia antiga.
                return
            latest = (self._quick_loaded['profile'], self._quick_loaded['key_id'], form)
            request_matches = self._quick_preview_snapshot == latest
            response_matches = (response['profile'], response['key_id']) == latest[:2]
            if request_matches and response_matches and not self._quick_preview_queued:
                try:
                    # Validar que o arquivo foi produzido e decodificado,
                    # antes de mostrá-lo em ambas as prévias GTK.
                    self._composition_pixbuf = GdkPixbuf.Pixbuf.new_from_file(response['image'])
                    picture_file = Gio.File.new_for_path(response['image'])
                    self.quick_picture.set_file(picture_file)
                    self.composition_picture.set_file(picture_file)
                    self.composition_canvas.queue_draw()
                    self.composition_status.set_text('Prévia local pronta: arraste dentro da borda azul.')
                    self.quick_state.set_text('Pré-visualização local pronta; não alterou o dispositivo.')
                except (GLib.Error, OSError) as exc:
                    self._composition_pixbuf = None
                    self.composition_picture.set_paintable(None)
                    self.composition_status.set_text('Falha ao carregar imagem ampliada: ' + str(exc))
                    self.quick_state.set_text('Falha na pré-visualização local: ' + str(exc))
            else:
                # Não deixar uma imagem antiga sobrescrever a última escolha.
                self._quick_preview_queued = False
                self._quick_preview()
        elif command == 'quick_save':
            if not self._quick_loaded:
                return
            if (response['profile'], response['key_id']) != (self._quick_loaded['profile'], self._quick_loaded['key_id']):
                return
            self._quick_loaded['sha256'] = response['sha256']
            self._quick_loaded['edited'] = self._quick_form()  # a próxima edição preserva appearance
            self._quick_dirty = False
            self._quick_saved = True
            self.quick_state.set_text('YAML salvo com backup em ' + response['backup'] + '. Clique em Aplicar ao dispositivo.')
        self._quick_controls()

    def _build_profiles(self):
        page = self._page('profiles', 'Perfis',
                          'Alternância pelo IPC; configurações pessoais permanecem no diretório XDG.')
        self.profile_list = _box(False, 7)
        page.append(self.profile_list)
        row = _box(True)
        page.append(row)
        _button(row, 'Gerenciar perfis', lambda *_: self._launch('perfis'))
        _button(row, 'Recarregar catálogo', lambda *_: self._call('reload'))
        page.append(_label('O recarregamento valida os YAML antes de atualizar os LCDs.',
                           style='caption', wrap=True))

    def _build_icons(self):
        page = self._page('icons', 'Ícones',
                          'Biblioteca pessoal PNG 100 × 100. Importe e reutilize os ícones no editor de teclas.')
        row = _box(True)
        page.append(row)
        _button(row, 'Importar imagem…', self._choose_icon)
        _button(row, 'Atualizar biblioteca', lambda *_: self._call('icons'))
        _button(row, 'Editar tecla', lambda *_: self._launch('teclas'))
        self.icon_count = _label('Carregando biblioteca…', style='dim-label')
        page.append(self.icon_count)
        self.search_icons = Gtk.SearchEntry(placeholder_text='Pesquisar ícones')
        self.search_icons.connect('search-changed', lambda *_: self._render_icons())
        page.append(self.search_icons)
        scroller = Gtk.ScrolledWindow()
        scroller.set_min_content_height(300)
        page.append(scroller)
        self.icon_flow = Gtk.FlowBox()
        self.icon_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.icon_flow.set_max_children_per_line(7)
        self.icon_flow.set_row_spacing(12)
        self.icon_flow.set_column_spacing(12)
        scroller.set_child(self.icon_flow)

    def _build_system(self):
        page = self._page('system', 'Sistema',
                          'Métricas locais de leitura. O dashboard nos LCDs continua executando no serviço.')
        self.system_state = _label('Consultando métricas do Linux…', style='dim-label')
        page.append(self.system_state)
        _button(page, 'Atualizar métricas', lambda *_: self._call('system'))
        page.append(_label('CPU e rede exigem duas amostras para calcular a utilização. '
                           'Valores indisponíveis são mostrados como N/D.',
                           style='caption', wrap=True))

    def _build_obs(self):
        page = self._page('obs', 'OBS Studio',
                          'Consulta somente leitura ao OBS WebSocket local; '
                          'nenhuma gravação ou transmissão é iniciada pelo painel.')
        self.obs_state = _label('Clique em Consultar OBS.', wrap=True)
        page.append(self.obs_state)
        row = _box(True)
        page.append(row)
        _button(row, 'Consultar OBS', lambda *_: self._call('obs'))
        _button(row, 'Configurar OBS', lambda *_: self._launch('obs'))
        _button(row, 'Editor visual', lambda *_: self._launch('obs_visual'))
        row2 = _box(True)
        page.append(row2)
        _button(row2, 'Criar perfis OBS', lambda *_: self._launch('obs_profil'))
        page.append(_label('O mixer de áudio e o salvamento de cenas permanecem '
                           'nas janelas especializadas, com confirmação e backup dos YAML.',
                           style='caption', wrap=True))

    def _build_settings(self):
        page = self._page('settings', 'Configurações',
                          'Atalhos e caminhos da instalação. Nenhuma preferência é alterada nesta página.')
        config = Path(os.environ.get('XDG_CONFIG_HOME') or (Path.home() / '.config')) / 'vision02'
        assets = Path(os.environ.get('XDG_DATA_HOME') or (Path.home() / '.local/share')) / 'vision02' / 'assets'
        for label, path in (('Projeto', ROOT), ('Perfis', config / 'profiles'),
                            ('Ícones', assets / 'icons'), ('OBS', config / 'obs.json')):
            page.append(_label(f'{label}: {path}', wrap=True))
        page.append(_label('Credenciais OBS não são lidas nem exibidas pelo Studio.',
                           style='caption', wrap=True))
        row = _box(True)
        page.append(row)
        _button(row, 'Gerenciar perfis', lambda *_: self._launch('perfis'))
        _button(row, 'Painel legado', lambda *_: self._launch('dashboard'))

    def _launch(self, tool, *, profile=None, key_id=None):
        if tool not in TOOLS:
            return
        executable = ROOT / 'scripts' / TOOLS[tool]
        command = [str(executable)]
        if tool == 'teclas' and profile is not None and key_id is not None:
            try:
                command.extend(editor_args(profile, key_id))
            except ValueError as exc:
                self.top_status.set_text(f'Não foi possível selecionar tecla: {exc}')
                return
        try:
            subprocess.Popen(command, cwd=str(ROOT), start_new_session=True)
        except OSError as exc:
            self.top_status.set_text(f'Não foi possível abrir {TOOLS[tool]}: {exc}')

    def _call(self, command, **payload):
        if self._closed or command in self._busy:
            return
        self._busy.add(command)

        def worker():
            try:
                result = subprocess.run(
                    [str(PYTHON), str(BACKEND), '--command', command],
                    input=json.dumps(payload, ensure_ascii=False),
                    capture_output=True, text=True, timeout=(38 if command == 'obs' else 32),
                    check=False,
                )
                response = json.loads(result.stdout)
                if not isinstance(response, dict):
                    raise ValueError('Resposta inválida do backend')
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                response = {'ok': False, 'error': str(exc)}
            if not self._closed:
                GLib.idle_add(self._receive, command, response)

        threading.Thread(target=worker, name=f'vision02-studio-{command}', daemon=True).start()

    def _receive(self, command, response):
        self._busy.discard(command)
        if self._closed:
            return False
        if not response.get('ok'):
            message = response.get('error', 'Erro desconhecido')
            if command == 'status':
                self.top_status.set_text('Serviço indisponível')
                self.dashboard_state.set_text(f'Serviço indisponível: {message}')
            elif command.startswith('quick_'):
                self.quick_state.set_text(f'Falha em {command}: {message}')
                if command == 'quick_preview' and self._quick_preview_queued:
                    self._quick_preview_queued = False
                    self._quick_preview()
                self._quick_controls()
            elif command == 'key_activity':
                self.key_activity_label.set_text(
                    'Sem eventos via IPC: ' + str(message) +
                    '. Confirme o reinício de vision02.service.'
                )
            elif command == 'import_icon':
                self._quick_import_target = None
                self.top_status.set_text(f'Falha na importação da imagem: {message}')
                if self.stack.get_visible_child_name() == 'keys':
                    self.quick_state.set_text(f'Falha ao importar imagem: {message}')
            elif command == 'obs':
                self.obs_state.set_text(f'OBS indisponível: {message}')
            elif command == 'system':
                self.system_state.set_text(f'Métricas indisponíveis: {message}')
            else:
                self.top_status.set_text(f'{command}: {message}')
            return False
        if command in {'quick_inspect', 'quick_preview', 'quick_save'}:
            self._quick_received(command, response)
            return False
        if command in {'status', 'switch', 'reload'}:
            if command == 'reload':
                self._call('previews')
                self._call('live_preview')
            self._call('status') if command in {'switch', 'reload'} else None
            if command != 'status':
                return False
            self._connected = bool(response.get('connected'))
            before_profile = self._current
            self._current = str(response.get('active') or '')
            if self._current and self._current != before_profile and not self._quick_dirty:
                self._quick_load()
            elif self._current != before_profile and self._quick_dirty:
                self.quick_state.set_text('Perfil ativo mudou. Salve ou descarte a edição pendente.')
            profiles = response.get('profiles') or []
            if profiles != self._profiles:
                self._profiles = profiles
                self._render_profiles()
                self._call('previews')
            self._update_combo()
            self._render_profiles()
            self._render_keys()
            state = ('Conectada' if self._connected else 'USB desconectado')
            self.top_status.set_text(f'Vision 02 · {state} · {self._current or "—"}')
            self.dashboard_state.set_text(f'Dispositivo: {state}  |  Perfil ativo: {self._current or "—"}')
            self.dashboard_profiles.set_text(f'{len(self._profiles)} perfis disponíveis')
        elif command == 'previews':
            self._previews = response.get('profiles') or {}
            self._render_keys()
        elif command == 'key_activity':
            pressed = {key for key in response.get('pressed_keys', []) if type(key) is int and 1 <= key <= 15}
            last = response.get('last_key')
            last = last if type(last) is int and 1 <= last <= 15 else None
            if pressed != self._physical_pressed or last != self._last_physical:
                self._physical_pressed = pressed
                self._last_physical = last
                self._update_key_highlight()
        elif command == 'live_preview':
            active = response.get('active') or ''
            revision = response.get('revision', -1)
            images = response.get('images') if response.get('available') else {}
            if (active != self._live_active or revision != self._live_revision
                    or images != self._live_images):
                self._live_active = active
                self._live_revision = revision
                self._live_images = images or {}
                if self.stack.get_visible_child_name() == 'keys':
                    self._render_keys()
        elif command == 'icons':
            self._icons = response.get('icons') or []
            self._render_icons()
            self._render_quick_icons()
        elif command == 'import_icon':
            target = self._quick_import_target
            self._quick_import_target = None
            self._call('icons')
            icon = response.get('icon') or {}
            path = icon.get('path')
            if (target == (self._current, self._selected_key)
                    and self._quick_loaded is not None
                    and isinstance(path, str)):
                # A importação foi explicitamente iniciada neste painel.
                # Se o perfil/tecla mudou durante o processamento, não aplica.
                self.quick_image.set_text(path)
                self._quick_preview()
                self.quick_state.set_text('Imagem importada e selecionada; salve e aplique para atualizar o LCD.')
            self.top_status.set_text('Ícone importado para a biblioteca pessoal')
        elif command == 'system':
            metrics = response.get('metrics') or {}
            pairs = [('CPU', 'cpu', '%'), ('RAM', 'ram', '%'),
                     ('RAM utilizada', 'ram_gib', 'GiB'), ('GPU', 'gpu', '%'),
                     ('Disco', 'disk', '%'), ('Temperatura', 'temp', '°C'),
                     ('Download', 'rx_bps', 'B/s'), ('Upload', 'tx_bps', 'B/s')]
            values = []
            for title, key, unit in pairs:
                value = metrics.get(key)
                values.append(f'{title}: {value:.1f} {unit}' if isinstance(value, (int, float))
                              else f'{title}: N/D')
            self.system_state.set_text('\n'.join(values))
        elif command == 'obs':
            obs = response.get('obs') or {}
            states = obs.get('states') or {}
            def yesno(value):
                return 'SIM' if value is True else 'NÃO' if value is False else 'N/D'
            self.obs_state.set_text(
                f"OBS {obs.get('obs_version', '—')} | WebSocket {obs.get('websocket_version', '—')}\n"
                f"Cena ativa: {obs.get('active_scene') or 'N/D'}\n"
                f"Gravando: {yesno(states.get('recording'))}    "
                f"Transmitindo: {yesno(states.get('streaming'))}    "
                f"Câmera virtual: {yesno(states.get('virtualcam'))}\n"
                f"Cenas: {len(obs.get('scenes') or [])}  |  "
                f"Fontes: {len(obs.get('inputs') or [])}"
            )
        return False

    def _update_combo(self):
        self._syncing = True
        try:
            self.profile_combo.set_model(Gtk.StringList.new(self._profiles))
            self.profile_combo.set_selected(self._profiles.index(self._current)
                                            if self._current in self._profiles
                                            else Gtk.INVALID_LIST_POSITION)
            self.profile_combo.set_sensitive(self._connected)
        finally:
            self._syncing = False

    def _profile_selected(self, widget, _param):
        if self._syncing or not self._connected:
            return
        if self._quick_dirty:
            self.quick_state.set_text('Salve ou descarte a edição antes de trocar o perfil.')
            self._update_combo()
            return
        index = widget.get_selected()
        if index < len(self._profiles):
            target = self._profiles[index]
            if target != self._current:
                self._call('switch', target=target)

    def _render_profiles(self):
        child = self.profile_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.profile_list.remove(child)
            child = nxt
        for name in self._profiles:
            row = _box(True)
            row.append(_label(('● ' if name == self._current else '  ') + name))
            button = Gtk.Button(label='Ativar')
            button.set_sensitive(self._connected and name != self._current)
            button.connect('clicked', lambda _w, target=name: self._call('switch', target=target))
            row.append(button)
            self.profile_list.append(row)

    def _key_selected(self, _button, key_id):
        """Usa o sinal clicked do próprio Gtk.Button para contar os cliques.

        Não recriar filhos do botão durante o primeiro clique: isso pode
        interromper a sequência do gesto duplo em algumas versões de GTK.
        """
        if key_id != self._selected_key and self._quick_dirty:
            self.quick_state.set_text('Salve ou descarte as alterações antes de selecionar outra tecla.')
            return
        double_click = self._click_detector.click(key_id)
        changed = key_id != self._selected_key
        self._selected_key = key_id
        self._update_key_highlight()
        self._update_key_detail()
        if changed:
            self._quick_load()
        if double_click:
            self._edit_selected_key()

    def _edit_selected_key(self, *_):
        if not self._current:
            self.top_status.set_text('Nenhum perfil ativo para edição')
            return
        self._launch('teclas', profile=self._current, key_id=self._selected_key)

    def _update_key_detail(self):
        keys = {item['id']: item for item in self._previews.get(self._current, {}).get('keys', [])}
        key = keys.get(self._selected_key, {})
        self.key_detail.set_text(
            f"Tecla física {self._selected_key:02d}  |  "
            f"LCD {key.get('display_id', '—')}  |  "
            f"{key.get('label') or 'Sem rótulo'}  |  "
            f"Ação: {key.get('action') or 'Nenhuma'}  |  "
            f"Imagem: {'LCD ao vivo' if self._live_active == self._current and self._live_images else 'Prévia YAML'}"
        )

    def _update_key_highlight(self):
        for ident, button in self.key_buttons.items():
            physical_pressed = ident in self._physical_pressed
            recent = ident == self._last_physical
            active = physical_pressed or recent
            if active:
                button.add_css_class('vision02-key-pressed')
            else:
                button.remove_css_class('vision02-key-pressed')
            if ident == self._selected_key:
                button.add_css_class('vision02-key-selected')
            else:
                button.remove_css_class('vision02-key-selected')
            number_label = self._key_number_labels.get(ident)
            if number_label is not None:
                number_label.set_text(f'{ident:02d}' + (' • SELECIONADA' if ident == self._selected_key else ''))
            status_label = self._key_status_labels.get(ident)
            if status_label is not None:
                status_label.set_text('PRESSIONADA' if physical_pressed else 'RECENTE' if recent else '')
                if active:
                    status_label.add_css_class('vision02-key-status-active')
                else:
                    status_label.remove_css_class('vision02-key-status-active')
        if self._physical_pressed:
            keys = ', '.join(f'{key:02d}' for key in sorted(self._physical_pressed))
            self.key_activity_label.set_text(f'Tecla(s) física(s) pressionada(s): {keys}')
        elif self._last_physical is not None:
            self.key_activity_label.set_text(f'Última tecla física: {self._last_physical:02d} (recente)')
        else:
            self.key_activity_label.set_text('Aguardando pressionamento físico…')

    def _render_keys(self):
        keys = {row['id']: row for row in self._previews.get(self._current, {}).get('keys', [])}
        self._key_number_labels = {}
        self._key_status_labels = {}
        for key_id, button in self.key_buttons.items():
            item = keys.get(key_id, {})
            cell = _box(False, 3)
            cell.set_halign(Gtk.Align.CENTER)
            png = item.get('image')
            live_path = self._live_images.get(str(key_id)) if self._live_active == self._current else None
            live_picture = None
            if isinstance(live_path, str):
                try:
                    data = Path(live_path).read_bytes()
                    if 0 < len(data) <= 256 * 1024:
                        texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
                        live_picture = Gtk.Picture.new_for_paintable(texture)
                except (OSError, GLib.Error, ValueError):
                    pass
            if live_picture is not None:
                live_picture.set_size_request(92, 92)
                live_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                cell.append(live_picture)
            elif isinstance(png, str) and Path(png).is_file():
                picture = Gtk.Picture.new_for_file(Gio.File.new_for_path(png))
                picture.set_size_request(92, 92)
                picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                cell.append(picture)
            else:
                blank = _label('—')
                blank.set_size_request(92, 92)
                cell.append(blank)
            title = _label(f'{key_id:02d}')
            title.set_halign(Gtk.Align.CENTER)
            cell.append(title)
            self._key_number_labels[key_id] = title
            status = _label('', style='caption')
            status.set_halign(Gtk.Align.CENTER)
            cell.append(status)
            self._key_status_labels[key_id] = status
            button.set_child(cell)
        self._update_key_highlight()
        self._update_key_detail()

    def _render_icons(self):
        search = self.search_icons.get_text().casefold().strip()
        matching = [icon for icon in self._icons if search in icon.get('name', '').casefold()]
        self.icon_count.set_text(f'{len(matching)} exibidos / {len(self._icons)} ícones disponíveis')
        child = self.icon_flow.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.icon_flow.remove(child)
            child = nxt
        for icon in matching[:120]:
            item = _box(False, 3)
            item.set_halign(Gtk.Align.CENTER)
            filename = icon.get('path', '')
            if filename and Path(filename).is_file():
                pic = Gtk.Picture.new_for_file(Gio.File.new_for_path(filename))
                pic.set_size_request(75, 75)
                pic.set_content_fit(Gtk.ContentFit.CONTAIN)
                item.append(pic)
            cap = _label(icon.get('name', 'Ícone'))
            cap.set_max_width_chars(15)
            cap.set_ellipsize(Pango.EllipsizeMode.END)
            item.append(cap)
            self.icon_flow.insert(item, -1)

    def _choose_icon(self, *_, for_quick=False):
        dialog = Gtk.FileChooserNative.new('Importar ícone', self,
                                           Gtk.FileChooserAction.OPEN,
                                           'Importar', 'Cancelar')
        def done(chooser, response):
            if response == Gtk.ResponseType.ACCEPT:
                selected = chooser.get_file()
                if selected and selected.get_path():
                    if 'import_icon' in self._busy:
                        self.top_status.set_text('Uma importação já está em andamento.')
                    else:
                        self._quick_import_target = ((self._current, self._selected_key)
                                                      if for_quick and self._quick_loaded is not None else None)
                        self._call('import_icon', path=selected.get_path())
            chooser.destroy()
        dialog.connect('response', done)
        dialog.show()

    def _refresh_current(self, *_):
        key = self.stack.get_visible_child_name()
        if key in {'dashboard', 'profiles', 'keys'}:
            self._call('status')
        if key == 'keys':
            self._call('previews')
            self._call('live_preview')
        elif key == 'icons':
            self._call('icons')
        elif key == 'system':
            self._call('system')
        elif key == 'obs':
            self._call('obs')

    def _on_page(self, *_):
        self._refresh_current()

    def _activity_tick(self):
        if self._closed:
            return False
        if self.stack.get_visible_child_name() == 'keys':
            self._call('key_activity')
        return True

    def _preview_tick(self):
        if self._closed:
            return False
        if self.stack.get_visible_child_name() == 'keys':
            self._call('live_preview')
        return True

    def _tick(self):
        if self._closed:
            return False
        self._call('status')
        key = self.stack.get_visible_child_name()
        if key == 'system':
            self._call('system')
        if key == 'obs':
            self._call('obs')
        return True

    def _sidebar_position_changed(self, paned, *_):
        # Evita gravar o arquivo repetidamente durante o arraste.
        if self._closed or paned.get_position() < MIN_SIDEBAR_WIDTH:
            return
        if self._sidebar_save_timer:
            GLib.source_remove(self._sidebar_save_timer)
        self._sidebar_save_timer = GLib.timeout_add(600, self._persist_sidebar_width)

    def _persist_sidebar_width(self):
        self._sidebar_save_timer = 0
        try:
            save_sidebar_width(self.navigation.get_position())
        except (OSError, ValueError) as exc:
            # Preferência visual: nunca interromper a interface por erro de I/O.
            print(f'Vision 02 Studio: não foi possível salvar largura: {exc}', file=sys.stderr)
        return False

    def _on_close(self, *_):
        if self._quick_dirty:
            self.quick_state.set_text('Há alterações não salvas. Salve ou descarte antes de fechar.')
            self.stack.set_visible_child_name('keys')
            return True
        if self._sidebar_save_timer:
            GLib.source_remove(self._sidebar_save_timer)
            self._persist_sidebar_width()
        self._closed = True
        if self._preview_timer:
            GLib.source_remove(self._preview_timer)
            self._preview_timer = 0
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        if self._activity_timer:
            GLib.source_remove(self._activity_timer)
            self._activity_timer = 0
        return False


class StudioApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='io.github.vision02.Studio')
        self.connect('activate', self._activate)

    def _activate(self, app):
        window = self.props.active_window
        if window is None:
            window = StudioWindow(self)
        window.present()


def main():
    Adw.init()
    return StudioApp().run(sys.argv)


if __name__ == '__main__':
    raise SystemExit(main())
