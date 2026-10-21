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
from vision02.studio_tabs_layout import load_panel_width, save_panel_width
from vision02.studio_visual_selection import hit_visual_element, visual_element_regions
from vision02.studio_alpha_hit_v8 import (
    extract_alpha, mask_candidates, choose_mask_layer, next_mask_layer, mask_regions,
)
from vision02.studio_composition_v4 import nudge_state, guides_at_position, coordinate_caption
from vision02.studio_deck_layout_v14 import (
    DECK_KEY_WIDTH, DECK_KEY_HEIGHT, DECK_ICON_SIZE,
    DECK_COLUMN_SPACING, DECK_ROW_SPACING, recommended_window_size,
    load_window_size, save_window_size, deck_key_position,
)
from vision02.studio_preset_canvas_v13 import (
    canvas_regions, select_at, resize_hit, transform,
)
from vision02.studio_layers_v5 import (
    available_layers, hit_layer_candidates, next_overlapping_layer,
)
from vision02.studio_layers_v6 import center_layer_axis, is_layer_locked
from vision02.studio_composition_v2 import (
    CompositionHistory, FIELDS, ZOOMS, state_from_fields, apply_state,
    default_target, smart_snap, anchors_for_target, display_geometry,
    hit_image_handle, visible_handle_position, resize_image_scale,
)
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
        display = Gdk.Display.get_default()
        monitors = display.get_monitors() if display else None
        primary = monitors.get_item(0) if monitors and monitors.get_n_items() else None
        geometry = primary.get_geometry() if primary else None
        width, height = recommended_window_size(
            geometry.width if geometry else None,
            geometry.height if geometry else None,
        )
        width, height = load_window_size(width, height)
        self.set_default_size(width, height)
        self.set_resizable(True)
        self.set_size_request(900, 600)
        # Abrir maximizado (com barra de titulo GNOME) evita exigir que o
        # usuario redimensione a janela a cada inicializacao. Pode ser
        # restaurada normalmente pelo botao de janela do compositor.
        self.maximize()
        self._closed = False
        self._busy = set()
        self._profiles = []
        self._current = ''
        self._connected = False
        self._brightness_dirty = False
        self._brightness_syncing = False
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
        self._quick_batch_clipboard = None  # origem persistida, perfil e SHA
        self._quick_batch_configured = set()
        self._quick_batch_pending_apply = False
        self._preset_items = []
        self._gallery_items = []
        self._preset_editor_draft = None
        self._preset_editor_history = []
        self._preset_editor_cursor = -1
        self._preset_editor_sync = False
        self._preset_editor_timer = 0
        self._preset_editor_preview_pending = False
        self._preset_canvas_zoom = 1.0
        self._preset_canvas_target = 'image'
        self._preset_canvas_before_drag = None
        self._preset_canvas_drag_kind = 'move'
        self._preset_canvas_drag_updating = False
        self._preset_canvas_guides = (None, None)
        self._preset_canvas_preview_path = None
        self._preset_pending_apply = False
        self._icons = []
        self._quick_icon_buttons = {}
        self._quick_import_target = None
        self._quick_preview_snapshot = None
        self._quick_preview_queued = False
        self._style_preview_timer = 0
        self._style_color_syncing = False
        self._composition_pixbuf = None
        self._composition_drag_start = (0, 0)
        self._composition_history = CompositionHistory()
        self._composition_before_drag = None
        self._composition_drag_kind = 'move'
        self._composition_drag_did_move = False
        self._composition_guide = (None, None)
        self._composition_zoom = 1.0
        self._composition_preview_path = None
        self._composition_last_overlap = None
        self._composition_v6_locked = {'image': False, 'text': False}
        self._composition_v6_outlines = {'image': True, 'text': True}
        self._composition_v7_paths = {}  # quatro variantes locais RGB
        self._composition_v8_masks = {}  # canais alfa 100x100, somente RAM
        self._composition_v7_visible = {'image': True, 'text': True}
        self._syncing = False
        self._sidebar_save_timer = 0
        self._panel_save_timer = 0
        self._menu_busy = False
        self._menu_plan = None

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
        self._build_profile_menu()
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
        keyboard = Gtk.EventControllerKey.new()
        keyboard.connect('key-pressed', self._composition_key_pressed)
        self.add_controller(keyboard)
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
            /* Corpo do equipamento, com acabamento de painel metalico. */
            frame.vision02-deck-body {
                background: linear-gradient(155deg, #31343b, #171a20 40%, #0b0d12);
                border: 2px solid #545b68;
                border-radius: 26px;
                box-shadow: inset 0 2px 2px rgba(255,255,255,0.18),
                            inset 0 -8px 15px rgba(0,0,0,0.43),
                            0 13px 24px rgba(0,0,0,0.48);
            }
            button.vision02-deck-key {
                background: linear-gradient(165deg, #454a53, #22262d 48%, #101318);
                border: 2px solid #5a616e;
                border-radius: 14px;
                padding: 3px;
                margin: 0;
                box-shadow: inset 0 2px 2px rgba(255,255,255,0.15),
                            0 5px 1px rgba(0,0,0,0.7),
                            0 7px 7px rgba(0,0,0,0.4);
            }
            button.vision02-deck-key:hover {
                border-color: #87b9e1;
                background: linear-gradient(155deg, #505c6e, #232e3c);
            }
            button.vision02-deck-key:active {
                box-shadow: inset 0 3px 8px rgba(0,0,0,0.70);
                background: #131822;
            }
            button.vision02-deck-key.vision02-key-selected {
                border: 2px solid #5dacee;
                box-shadow: 0 0 0 2px rgba(72,160,231,0.28),
                            0 5px 1px rgba(0,0,0,0.7);
            }
            button.vision02-deck-key.vision02-key-pressed {
                border: 3px solid #e5a327;
                box-shadow: 0 0 0 3px rgba(229,163,39,0.30),
                            inset 0 2px 4px rgba(0,0,0,0.6);
            }
            label.vision02-deck-brand {
                color: #aab5c3;
                font-size: 11px;
                font-weight: 800;
            }
            label.vision02-key-number {
                color: #b2b9c6;
                font-size: 10px;
            }
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
            frame.vision02-resize-handle {
                background-color: #1566bc;
                border: 3px solid #ffffff;
                border-radius: 7px;
                box-shadow: 0 0 0 2px #101723;
            }
            frame.vision02-resize-handle:hover {
                background-color: #3584e4;
            }
            frame.vision02-resize-handle label {
                color: white;
                font-weight: 900;
                font-size: 20px;
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
        # As teclas mantêm dimensões físicas estáveis. O espaço restante é
        # ocupado pelas margens, não por células esticadas na grade GTK.
        editor_split = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        editor_split.set_wide_handle(True)
        # Migrar larguras salvas pela grade antiga: 300 px deixavam apenas
        # duas das cinco colunas visiveis, mesmo em monitores largos.
        editor_split.set_position(max(load_panel_width(), 660))
        editor_split.connect('notify::position', self._panel_position_changed)
        self.editor_split = editor_split
        editor_split.set_resize_start_child(True)
        editor_split.set_resize_end_child(False)
        editor_split.set_shrink_start_child(False)
        editor_split.set_shrink_end_child(False)
        editor_split.set_vexpand(True)
        page.append(editor_split)

        key_scroll = Gtk.ScrolledWindow()
        key_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        key_scroll.set_min_content_height(470)
        # Largura minima do conjunto + margens do chassi. Mantemos scroll
        # automatico para monitores estreitos e o Paned ajustavel.
        key_scroll.set_min_content_width(634)
        grid_box = _box(False, 10)
        grid_box.set_hexpand(True)
        grid_box.set_vexpand(True)
        key_scroll.set_child(grid_box)
        editor_split.set_start_child(key_scroll)

        # Gtk.CenterBox posiciona o chassi exatamente no centro da área
        # disponível. Em janelas pequenas, o ScrolledWindow permite rolar.
        deck_center = Gtk.CenterBox(orientation=Gtk.Orientation.VERTICAL)
        deck_center.set_hexpand(True)
        deck_center.set_vexpand(True)
        grid_box.append(deck_center)
        deck_frame = Gtk.Frame()
        deck_frame.add_css_class('vision02-deck-body')
        deck_frame.set_halign(Gtk.Align.CENTER)
        deck_frame.set_valign(Gtk.Align.CENTER)
        deck_frame.set_hexpand(False)
        deck_frame.set_vexpand(False)
        deck_center.set_center_widget(deck_frame)
        deck_box = _box(False, 10)
        deck_box.set_halign(Gtk.Align.CENTER)
        deck_box.set_valign(Gtk.Align.CENTER)
        deck_box.set_margin_top(19)
        deck_box.set_margin_bottom(15)
        deck_box.set_margin_start(22)
        deck_box.set_margin_end(22)
        deck_frame.set_child(deck_box)
        # Gtk.Grid / set_size_request() so define minimo: recebendo o espaco
        # do Paned, cada coluna podia crescer ate ~200 px. Gtk.Fixed dispoe
        # as teclas por coordenadas, sem distribuir espaco livre aos botoes.
        self.key_grid = Gtk.Fixed()
        self.key_grid.set_size_request(5 * DECK_KEY_WIDTH + 4 * DECK_COLUMN_SPACING,
                                       3 * DECK_KEY_HEIGHT + 2 * DECK_ROW_SPACING)
        self.key_grid.set_hexpand(False)
        self.key_grid.set_vexpand(False)
        self.key_grid.set_halign(Gtk.Align.CENTER)
        self.key_grid.set_valign(Gtk.Align.CENTER)
        deck_box.append(self.key_grid)
        brand = _label('VISION 02', style='vision02-deck-brand')
        brand.set_halign(Gtk.Align.CENTER)
        deck_box.append(brand)

        self.key_activity_label = _label('Pressione uma tecla física para verificar o destaque.', wrap=True)
        self.key_activity_label.set_halign(Gtk.Align.CENTER)
        grid_box.append(self.key_activity_label)
        self.key_detail = _label('Selecione uma tecla.', wrap=True)
        self.key_detail.set_halign(Gtk.Align.CENTER)
        grid_box.append(self.key_detail)
        self._build_quick_properties(editor_split)
        self.key_buttons = {}
        for ident in range(1, 16):
            button = Gtk.Button()
            button.add_css_class('vision02-deck-key')
            button.set_size_request(DECK_KEY_WIDTH, DECK_KEY_HEIGHT)
            button.set_hexpand(False)
            button.set_vexpand(False)
            button.set_halign(Gtk.Align.START)
            button.set_valign(Gtk.Align.START)
            button.set_overflow(Gtk.Overflow.HIDDEN)
            button.connect('clicked', self._key_selected, ident)
            col_x, row_y = deck_key_position(ident)
            self.key_grid.put(button, col_x, row_y)
            self.key_buttons[ident] = button
        self._render_keys()

    def _build_quick_properties(self, editor_split):
        # Raiz fixa: cabeçalho e comandos sempre visíveis, mesmo quando o
        # formulário de uma aba necessita de rolagem vertical.
        # Nome props_scroll preservado por compatibilidade com testes antigos.
        props_scroll = _box(False, 8)
        props_scroll.set_size_request(300, -1)
        props_scroll.set_margin_start(12)
        props_scroll.set_margin_end(8)
        props_scroll.set_margin_top(6)
        props_scroll.set_margin_bottom(12)
        editor_split.set_end_child(props_scroll)
        props_scroll.append(_label('Propriedades da tecla', style='title-3'))
        self.quick_target = _label('Selecione uma tecla para editar.', wrap=True)
        props_scroll.append(self.quick_target)

        # A opção de aparência é comum às abas Texto e Composição; deixá-la
        # acima das abas evita controles inacessíveis quando o usuário arrasta.
        self.style_enabled = Gtk.CheckButton(label='Usar aparência personalizada')
        props_scroll.append(self.style_enabled)

        self.quick_tabs = Gtk.Notebook()
        self.quick_tabs.set_scrollable(True)
        self.quick_tabs.set_show_border(False)
        self.quick_tabs.set_vexpand(True)
        props_scroll.append(self.quick_tabs)

        def make_tab(title):
            scroller = Gtk.ScrolledWindow()
            scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroller.set_vexpand(True)
            contents = _box(False, 8)
            contents.set_margin_start(4)
            contents.set_margin_end(6)
            contents.set_margin_top(10)
            contents.set_margin_bottom(12)
            scroller.set_child(contents)
            self.quick_tabs.append_page(scroller, Gtk.Label(label=title))
            return contents

        action_box = make_tab('Ação')
        image_box = make_tab('Imagem')
        text_box = make_tab('Texto')
        composition_box = make_tab('Composição')

        # Aba Ação: campos mudam conforme o tipo, mantendo o formulário
        # validado do editor anterior.
        action_box.append(_label('Tipo de ação'))
        self.quick_kind = Gtk.DropDown.new_from_strings(
            ['Sem ação (limpar)', 'Comando', 'URL', 'Script', 'Atalho', 'Trocar perfil', 'OBS']
        )
        action_box.append(self.quick_kind)
        self.quick_hint = _label('', style='caption', wrap=True)
        action_box.append(self.quick_hint)
        self.quick_fields = []
        for idx in range(4):
            entry = Gtk.Entry()
            entry.set_placeholder_text(f'Campo {idx + 1}')
            self.quick_fields.append(entry)
            action_box.append(entry)

        # Aba Imagem: galeria e importação continuam ligadas ao mesmo
        # campo quick_image, sem efeitos no YAML até Salvar.
        image_box.append(_label('Imagem (caminho local)'))
        self.quick_image = Gtk.Entry()
        image_box.append(self.quick_image)
        gallery = Gtk.Expander(label='Galeria visual de ícones')
        gallery.set_expanded(True)
        image_box.append(gallery)
        gallery_box = _box(False, 7)
        gallery.set_child(gallery_box)
        self.quick_icon_search = Gtk.SearchEntry()
        self.quick_icon_search.set_placeholder_text('Pesquisar por nome (ex.: OBS, Grafana)')
        self.quick_icon_search.connect('search-changed', lambda *_: self._render_quick_icons())
        gallery_box.append(self.quick_icon_search)
        self.quick_icon_count = _label('Aguardando biblioteca…', style='caption')
        gallery_box.append(self.quick_icon_count)
        # v14.2: o catálogo tem até 90 miniaturas. A rolagem interna recebe
        # altura útil; a galeria também pode ser aberta em janela ampliada.
        _button(gallery_box, 'Abrir galeria ampliada (90 miniaturas)…',
                self._open_quick_icon_gallery)
        gallery_scroll = Gtk.ScrolledWindow()
        gallery_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        gallery_scroll.set_min_content_height(270)
        gallery_scroll.set_size_request(-1, 300)
        gallery_scroll.set_vexpand(True)
        gallery_scroll.set_propagate_natural_height(False)
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
        gallery_box.append(_label('Escolha o ícone para prévia local; a aplicação ao LCD exige salvar e aplicar.',
                                  style='caption', wrap=True))
        self.quick_picture = Gtk.Picture()
        self.quick_picture.set_size_request(100, 100)
        self.quick_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        image_box.append(self.quick_picture)
        batch_expander = Gtk.Expander(label='Copiar aparência para outras teclas (lote)')
        image_box.append(batch_expander)
        batch_box = _box(False, 7)
        batch_box.set_margin_top(10)
        batch_expander.set_child(batch_box)
        self._build_batch_appearance_v9(batch_box)
        preset_expander = Gtk.Expander(label='Biblioteca de presets visuais (v10) · galeria v11')
        image_box.append(preset_expander)
        preset_box = _box(False, 7)
        preset_box.set_margin_top(10)
        preset_expander.set_child(preset_box)
        self._build_presets_v10(preset_box)

        # Aba Texto: rótulo, texto no LCD, tipografia, cores e alinhamento.
        text_box.append(_label('Rótulo'))
        self.quick_label = Gtk.Entry()
        text_box.append(self.quick_label)
        text_box.append(_label('Texto visual no LCD (opcional)'))
        self.quick_visual_text = Gtk.Entry()
        self.quick_visual_text.set_placeholder_text('Vazio: usa o rótulo da tecla')
        text_box.append(self.quick_visual_text)
        # Enquadramento e dimensões da imagem são movidos para Composição.
        composition_box.append(_label('Posição, escala e enquadramento da imagem',
                                      style='title-4'))
        self._build_visual_style(text_box, composition_box)
        self._build_composition_canvas(composition_box)

        self.quick_kind.connect('notify::selected', self._quick_kind_changed)
        for entry in (self.quick_label, self.quick_visual_text, self.quick_image, *self.quick_fields):
            entry.connect('changed', self._quick_changed)

        # Barra fixa de estado e comandos, fora dos ScrolledWindow das abas.
        footer = _box(False, 6)
        footer.add_css_class('toolbar')
        props_scroll.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        props_scroll.append(footer)
        self.quick_state = _label('Aguardando seleção…', wrap=True)
        footer.append(self.quick_state)
        self.quick_preview_btn = _button(footer, 'Pré-visualizar (local)', self._quick_preview)
        self.quick_save_btn = _button(footer, 'Salvar YAML com backup', self._quick_save)
        self.quick_apply_btn = _button(footer, 'Aplicar ao dispositivo (IPC)', self._quick_apply)
        discard_btn = _button(footer, 'Descartar edição / recarregar', self._quick_discard)
        advanced_btn = _button(footer, 'Editor avançado de aparência…', self._edit_selected_key)
        # v14.2: o rodapé com cinco botões empilhados consumia ~250px,
        # deixando uma única fileira de ícones visível. Em duas colunas,
        # todos os comandos permanecem acessíveis e liberam ~100px para abas.
        footer_buttons = Gtk.Grid(column_spacing=6, row_spacing=6)
        controls = (self.quick_preview_btn, self.quick_save_btn,
                    self.quick_apply_btn, discard_btn, advanced_btn)
        for index, control in enumerate(controls):
            footer.remove(control)
            control.set_hexpand(True)
            footer_buttons.attach(control, index % 2, index // 2, 1, 1)
        footer.insert_child_after(footer_buttons, self.quick_state)
        footer.append(_label('Salvar não aplica automaticamente. Alterar aba não descarta edições.',
                             style='caption', wrap=True))
        self._quick_kind_changed()
        self._quick_controls()

    def _build_batch_appearance_v9(self, parent):
        parent.append(_label('Copiar aparência para outras teclas', style='title-4'))
        parent.append(_label('Copia imagem, texto visual e estilo salvos no YAML. '
                             'Não copia rótulo, ação, atalhos, comandos ou OBS. '
                             'Somente teclas já configuradas no perfil atual.', wrap=True))
        self.quick_batch_source = _label('Nenhuma origem copiada.', wrap=True)
        parent.append(self.quick_batch_source)
        self.quick_batch_copy_btn = _button(
            parent, 'Copiar aparência salva da tecla atual', self._quick_batch_copy)
        parent.append(_label('Destinos (marque uma ou várias teclas):'))
        grid = Gtk.Grid(column_spacing=6, row_spacing=4)
        parent.append(grid)
        self.quick_batch_targets = {}
        for ident in range(1, 16):
            check = Gtk.CheckButton(label=f'{ident:02d}')
            check.connect('toggled', self._quick_batch_target_toggled)
            grid.attach(check, (ident - 1) % 5, (ident - 1) // 5, 1, 1)
            self.quick_batch_targets[ident] = check
        self.quick_batch_confirm = Gtk.CheckButton(
            label='Confirmo a substituição da aparência dos destinos marcados')
        self.quick_batch_confirm.connect('toggled', self._quick_batch_controls)
        parent.append(self.quick_batch_confirm)
        self.quick_batch_apply_btn = _button(
            parent, 'Aplicar em lote e salvar YAML com backup', self._quick_batch_apply,
            sensitive=False)
        self.quick_batch_status = _label('Nenhum YAML é alterado ao copiar ou marcar.', wrap=True)
        parent.append(self.quick_batch_status)
        parent.append(_label('Depois de salvar, clique em Aplicar ao dispositivo (IPC) '
                             'se desejar atualizar os LCDs físicos.', style='caption', wrap=True))
        self._quick_batch_controls()

    def _build_presets_v10(self, parent):
        parent.append(_label('Presets guardam somente imagem e estilo; ações e rótulos permanecem.',
                             wrap=True, style='caption'))
        self.preset_name = Gtk.Entry()
        self.preset_name.set_placeholder_text('Nome do preset (ex.: OBS Azul)')
        self.preset_name.connect('changed', self._preset_controls)
        parent.append(self.preset_name)
        self.preset_combo = Gtk.DropDown.new_from_strings(['Nenhum preset salvo'])
        self.preset_combo.connect('notify::selected', self._preset_selected)
        parent.append(self.preset_combo)
        self.preset_create_btn = _button(parent, 'Salvar aparência da tecla como preset', self._preset_create)
        row = _box(True, 5)
        parent.append(row)
        self.preset_rename_btn = _button(row, 'Renomear', self._preset_rename)
        self.preset_delete_btn = _button(row, 'Excluir', self._preset_delete)
        self.preset_preview_btn = _button(parent, 'Pré-visualizar preset (local)', self._preset_preview)
        self.preset_picture = Gtk.Picture()
        self.preset_picture.set_size_request(100, 100)
        self.preset_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        parent.append(self.preset_picture)
        parent.append(_label('Destinos configurados no perfil atual:', style='caption'))
        grid = Gtk.Grid(column_spacing=8, row_spacing=5)
        parent.append(grid)
        self.preset_targets = {}
        for key_id in range(1, 16):
            check = Gtk.CheckButton(label=f'{key_id:02d}')
            check.connect('toggled', self._preset_target_toggled)
            grid.attach(check, (key_id - 1) % 5, (key_id - 1) // 5, 1, 1)
            self.preset_targets[key_id] = check
        self.preset_confirm = Gtk.CheckButton(label='Confirmo substituir a aparência dos destinos marcados')
        self.preset_confirm.connect('toggled', self._preset_controls)
        parent.append(self.preset_confirm)
        self.preset_apply_btn = _button(parent, 'Aplicar preset e salvar YAML com backup', self._preset_apply)
        row = _box(True, 5)
        parent.append(row)
        self.preset_import_btn = _button(row, 'Importar ZIP…', self._preset_import)
        self.preset_export_btn = _button(row, 'Exportar ZIP…', self._preset_export)
        self.preset_status = _label('Nenhum preset modifica o dispositivo automaticamente.', wrap=True)
        parent.append(self.preset_status)
        self._preset_controls()
        self._build_presets_v11(parent)
        self._build_presets_v12(parent)
        self._call('preset_list')

    def _build_presets_v11(self, parent):
        parent.append(_label('Galeria v11 — escolha um cartão; favoritos e categorias ficam '
                             'somente na biblioteca local.', wrap=True, style='caption'))
        search_row = _box(True, 6)
        parent.append(search_row)
        self.gallery_search = Gtk.SearchEntry()
        self.gallery_search.set_placeholder_text('Pesquisar nome ou categoria')
        self.gallery_search.set_hexpand(True)
        self.gallery_search.connect('search-changed', self._gallery_render)
        search_row.append(self.gallery_search)
        self.gallery_favorites_only = Gtk.CheckButton(label='Só favoritos')
        self.gallery_favorites_only.connect('toggled', self._gallery_render)
        search_row.append(self.gallery_favorites_only)
        category_row = _box(True, 6)
        parent.append(category_row)
        category_row.append(_label('Filtrar categoria:', style='caption'))
        self.gallery_category_filter = Gtk.DropDown.new_from_strings(['Todas as categorias'])
        self.gallery_category_filter.connect('notify::selected', self._gallery_render)
        category_row.append(self.gallery_category_filter)
        gallery_scroll = Gtk.ScrolledWindow()
        gallery_scroll.set_min_content_height(230)
        gallery_scroll.set_max_content_height(360)
        gallery_scroll.set_propagate_natural_height(False)
        parent.append(gallery_scroll)
        self.gallery_flow = Gtk.FlowBox()
        self.gallery_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.gallery_flow.set_max_children_per_line(4)
        self.gallery_flow.set_row_spacing(8)
        self.gallery_flow.set_column_spacing(8)
        gallery_scroll.set_child(self.gallery_flow)
        self.gallery_count = _label('Carregando miniaturas…', style='caption')
        parent.append(self.gallery_count)
        favorite_row = _box(True, 6)
        parent.append(favorite_row)
        self.gallery_favorite_btn = _button(favorite_row, 'Marcar como favorito', self._gallery_favorite)
        self.gallery_category_entry = Gtk.Entry()
        self.gallery_category_entry.set_placeholder_text('Categoria (até 32 caracteres)')
        self.gallery_category_entry.set_max_length(32)
        self.gallery_category_entry.set_hexpand(True)
        favorite_row.append(self.gallery_category_entry)
        self.gallery_category_btn = _button(favorite_row, 'Salvar categoria', self._gallery_category)
        duplicate_row = _box(True, 6)
        parent.append(duplicate_row)
        self.gallery_duplicate_name = Gtk.Entry()
        self.gallery_duplicate_name.set_placeholder_text('Nome da cópia do preset')
        self.gallery_duplicate_name.set_max_length(60)
        self.gallery_duplicate_name.set_hexpand(True)
        duplicate_row.append(self.gallery_duplicate_name)
        self.gallery_duplicate_btn = _button(duplicate_row, 'Duplicar preset', self._gallery_duplicate)
        self._gallery_update_selected()

    # v12: o formulário altera somente um rascunho; o backend é responsável
    # por validar caminhos, imagens, concorrência e persistência em disco.
    def _build_presets_v12(self, parent):
        expander = Gtk.Expander(label='Editor visual de presets (v12)')
        parent.append(expander)
        box = _box(False, 6)
        expander.set_child(box)
        box.append(_label('Carregue um preset para criar um rascunho. Nem YAML nem LCD '
                          'são modificados ao pré-visualizar.', style='caption', wrap=True))
        self.preset_editor_load_btn = _button(
            box, 'Carregar preset selecionado para edição', self._preset_editor_load)
        self.preset_editor_title = _label('Nenhum rascunho carregado.', wrap=True)
        box.append(self.preset_editor_title)
        self.preset_editor_widgets = {}
        self.preset_editor_enums = {}
        self.preset_editor_fields = (
            ('background', 'Fundo #RRGGBB'), ('text', 'Texto visual (vazio = rótulo da tecla)'),
            ('text_color', 'Cor do texto #RRGGBB'),
        )
        for key, caption in self.preset_editor_fields:
            box.append(_label(caption, style='caption'))
            entry = Gtk.Entry()
            entry.connect('changed', self._preset_editor_changed)
            box.append(entry)
            self.preset_editor_widgets[key] = entry
        for key, title, options in (
            ('font_family', 'Fonte', ['sans', 'serif', 'mono']),
            ('font_weight', 'Peso da fonte', ['regular', 'bold']),
            ('horizontal', 'Alinhamento horizontal', ['left', 'center', 'right']),
            ('vertical', 'Alinhamento vertical', ['top', 'center', 'bottom']),
            ('image_fit', 'Enquadramento da imagem', ['cover', 'contain', 'stretch']),
        ):
            box.append(_label(title, style='caption'))
            combo = Gtk.DropDown.new_from_strings(options)
            combo.connect('notify::selected', self._preset_editor_changed)
            box.append(combo)
            self.preset_editor_widgets[key] = combo
            self.preset_editor_enums[key] = options
        for key, title, lower, upper in (
            ('font_size', 'Tamanho da fonte', 8, 36),
            ('offset_x', 'Texto X', -40, 40), ('offset_y', 'Texto Y', -40, 40),
            ('image_x', 'Imagem X', -100, 100), ('image_y', 'Imagem Y', -100, 100),
            ('image_scale', 'Escala da imagem (%)', 25, 200),
        ):
            row = _box(True, 7)
            box.append(row)
            row.append(_label(title))
            spin = Gtk.SpinButton.new_with_range(lower, upper, 1)
            spin.connect('value-changed', self._preset_editor_changed)
            row.append(spin)
            self.preset_editor_widgets[key] = spin
        self.preset_editor_show_text = Gtk.CheckButton(label='Exibir texto')
        self.preset_editor_show_text.connect('toggled', self._preset_editor_changed)
        box.append(self.preset_editor_show_text)
        box.append(_label('Imagem do preset (PNG/JPG/WebP local)', style='caption'))
        self.preset_editor_image = Gtk.Entry()
        self.preset_editor_image.connect('changed', self._preset_editor_changed)
        box.append(self.preset_editor_image)
        row = _box(True, 6)
        box.append(row)
        _button(row, 'Escolher imagem…', self._preset_editor_choose_image)
        _button(row, 'Remover imagem do rascunho', lambda *_: self.preset_editor_image.set_text(''))
        row = _box(True, 6)
        box.append(row)
        self.preset_editor_undo_btn = _button(row, 'Desfazer', self._preset_editor_undo)
        self.preset_editor_redo_btn = _button(row, 'Refazer', self._preset_editor_redo)
        self.preset_editor_picture = Gtk.Picture()
        self.preset_editor_picture.set_size_request(200, 200)
        self.preset_editor_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        box.append(self.preset_editor_picture)
        self._build_preset_canvas_v13(box)
        row = _box(True, 6)
        box.append(row)
        self.preset_editor_save_btn = _button(row, 'Salvar alterações no preset', self._preset_editor_save)
        self.preset_editor_as_name = Gtk.Entry()
        self.preset_editor_as_name.set_placeholder_text('Novo nome para Salvar como…')
        self.preset_editor_as_name.connect('changed', self._preset_editor_controls)
        box.append(self.preset_editor_as_name)
        self.preset_editor_save_as_btn = _button(box, 'Salvar como novo preset', self._preset_editor_save_as)
        self.preset_editor_status = _label('Carregue um preset antes de editar.', wrap=True)
        box.append(self.preset_editor_status)
        self._preset_editor_controls()

    # v13: canvas estritamente local; opera sobre widgets do rascunho v12.
    def _build_preset_canvas_v13(self, parent):
        expander = Gtk.Expander(label='Área de trabalho interativa (v13)')
        expander.set_expanded(True)
        parent.append(expander)
        box = _box(False, 8)
        expander.set_child(box)
        box.append(_label('Clique na imagem ou no texto para selecionar; arraste para mover. '
                          'A alça ↘ redimensiona a imagem. Nenhum movimento salva o preset.',
                          wrap=True, style='caption'))
        row = _box(True, 8)
        box.append(row)
        row.append(_label('Elemento:'))
        self.preset_canvas_target = Gtk.DropDown.new_from_strings(['Imagem', 'Texto'])
        self.preset_canvas_target.connect('notify::selected', self._preset_canvas_target_changed)
        row.append(self.preset_canvas_target)
        row.append(_label('Zoom:'))
        self.preset_canvas_zoom = Gtk.DropDown.new_from_strings(['100%', '150%', '200%'])
        self.preset_canvas_zoom.connect('notify::selected', self._preset_canvas_zoom_changed)
        row.append(self.preset_canvas_zoom)
        self.preset_canvas_snap = Gtk.CheckButton(label='Encaixe inteligente')
        self.preset_canvas_snap.set_active(True)
        box.append(self.preset_canvas_snap)
        self.preset_canvas_surface = Gtk.Overlay()
        self.preset_canvas_surface.set_size_request(320, 320)
        self.preset_canvas_surface.set_hexpand(False)
        self.preset_canvas_surface.set_halign(Gtk.Align.CENTER)
        box.append(self.preset_canvas_surface)
        self.preset_canvas_picture = Gtk.Picture()
        self.preset_canvas_picture.set_size_request(320, 320)
        self.preset_canvas_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.preset_canvas_picture.set_can_target(False)
        self.preset_canvas_surface.set_child(self.preset_canvas_picture)
        self.preset_canvas_overlay = Gtk.DrawingArea()
        self.preset_canvas_overlay.set_content_width(320)
        self.preset_canvas_overlay.set_content_height(320)
        self.preset_canvas_overlay.set_can_target(False)
        self.preset_canvas_overlay.set_draw_func(self._preset_canvas_draw)
        self.preset_canvas_surface.add_overlay(self.preset_canvas_overlay)
        drag = Gtk.GestureDrag.new()
        drag.set_button(1)
        drag.connect('drag-begin', self._preset_canvas_drag_begin)
        drag.connect('drag-update', self._preset_canvas_drag_update)
        drag.connect('drag-end', self._preset_canvas_drag_end)
        self.preset_canvas_surface.add_controller(drag)
        self.preset_canvas_status = _label('Carregue um preset para editar visualmente.', wrap=True, style='caption')
        box.append(self.preset_canvas_status)

    def _preset_canvas_size(self):
        return (self.preset_canvas_overlay.get_width(), self.preset_canvas_overlay.get_height())

    def _preset_canvas_style(self):
        return self._preset_editor_collect()['appearance']

    def _preset_canvas_target_changed(self, *_):
        self._preset_canvas_target = ('image' if self.preset_canvas_target.get_selected() == 0 else 'text')
        self.preset_canvas_overlay.queue_draw()

    def _preset_canvas_zoom_changed(self, *_):
        self._preset_canvas_zoom = ZOOMS[self.preset_canvas_zoom.get_selected()]
        self._preset_canvas_render_image()
        self.preset_canvas_overlay.queue_draw()

    def _preset_canvas_render_image(self):
        path = self._preset_canvas_preview_path
        if not path:
            self.preset_canvas_picture.set_paintable(None)
            return
        try:
            image = GdkPixbuf.Pixbuf.new_from_file(path)
            if self._preset_canvas_zoom != 1.0:
                width, height = image.get_width(), image.get_height()
                zoom = self._preset_canvas_zoom
                scaled = image.scale_simple(round(width * zoom), round(height * zoom),
                                            GdkPixbuf.InterpType.BILINEAR)
                if scaled is None:
                    raise ValueError('Não foi possível aplicar zoom na prévia')
                image = GdkPixbuf.Pixbuf.new_subpixbuf(
                    scaled, (scaled.get_width() - width) // 2,
                    (scaled.get_height() - height) // 2, width, height)
            self.preset_canvas_picture.set_paintable(Gdk.Texture.new_for_pixbuf(image))
        except (GLib.Error, OSError, ValueError):
            self.preset_canvas_picture.set_paintable(None)
            self.preset_canvas_status.set_text('Não foi possível carregar a prévia; confira o caminho da imagem.')

    def _preset_canvas_draw(self, _area, cr, width, height):
        if not self._preset_editor_active() or width <= 0 or height <= 0:
            return
        cx, cy, unit = display_geometry(width, height, self._preset_canvas_zoom)
        cr.set_line_width(1.0)
        cr.set_source_rgba(0.45, 0.78, 0.98, .55)
        cr.move_to(cx, 0)
        cr.line_to(cx, height)
        cr.move_to(0, cy)
        cr.line_to(width, cy)
        cr.stroke()
        gx, gy = self._preset_canvas_guides
        cr.set_source_rgba(1.0, .76, .2, .95)
        cr.set_line_width(2.0)
        for value, vertical in ((gx, True), (gy, False)):
            if value is None:
                continue
            if vertical:
                cr.move_to(cx + value * unit, 0)
                cr.line_to(cx + value * unit, height)
            else:
                cr.move_to(0, cy + value * unit)
                cr.line_to(width, cy + value * unit)
        cr.stroke()
        try:
            regions = canvas_regions(self._preset_canvas_style(),
                                     image_present=bool(self.preset_editor_image.get_text()),
                                     width=width, height=height, zoom=self._preset_canvas_zoom)
        except (ValueError, KeyError, TypeError):
            return  # Campos ainda em edição podem estar temporariamente inválidos.
        for name, region in regions.items():
            selected = name == self._preset_canvas_target
            cr.set_line_width(2.5 if selected else 1.0)
            if name == 'image':
                cr.set_source_rgba(.2, .85, 1., .96)
            else:
                cr.set_source_rgba(1., .72, .23, .96)
            cr.rectangle(region.x, region.y, region.width, region.height)
            cr.stroke()
        if self._preset_canvas_target == 'image' and 'image' in regions:
            from vision02.studio_composition_v2 import visible_handle_position
            style = self._preset_canvas_style()
            hx, hy = visible_handle_position(width, height, style['image_x'], style['image_y'],
                                              style['image_scale'], self._preset_canvas_zoom)
            cr.set_source_rgba(.14, .73, .93, .9)
            cr.rectangle(hx - 7, hy - 7, 14, 14)
            cr.fill()

    def _preset_canvas_drag_begin(self, _gesture, x, y):
        self._preset_canvas_before_drag = None
        self._preset_canvas_guides = (None, None)
        if not self._preset_editor_active() or self._preset_editor_sync or self._preset_busy():
            return
        width, height = self._preset_canvas_size()
        if width <= 0 or height <= 0:
            return
        try:
            style = self._preset_canvas_style()
            image = bool(self.preset_editor_image.get_text())
            handle = (self._preset_canvas_target == 'image' and resize_hit(
                style, image_present=image, width=width, height=height,
                zoom=self._preset_canvas_zoom, x=x, y=y))
            hit = ('image' if handle else select_at(
                style, image_present=image, width=width, height=height,
                zoom=self._preset_canvas_zoom, x=x, y=y, preferred=self._preset_canvas_target))
        except (ValueError, KeyError, TypeError):
            return
        if not hit:
            return
        self.preset_canvas_target.set_selected(0 if hit == 'image' else 1)
        self._preset_canvas_before_drag = dict(style)
        self._preset_canvas_drag_kind = 'resize' if handle else 'move'
        self.preset_canvas_status.set_text('Redimensionando imagem…' if handle else 'Movendo ' + ('imagem…' if hit == 'image' else 'texto…'))

    def _preset_canvas_drag_update(self, _gesture, dx, dy):
        before = self._preset_canvas_before_drag
        if before is None or not self._preset_editor_active() or self._preset_busy():
            return
        width, height = self._preset_canvas_size()
        try:
            style, guides = transform(before, self._preset_canvas_target,
                 self._preset_canvas_drag_kind, dx, dy, width, height,
                 self._preset_canvas_zoom, snap=self.preset_canvas_snap.get_active())
        except (ValueError, KeyError, TypeError):
            return
        self._preset_canvas_drag_updating = True
        try:
            for key in ('image_x', 'image_y', 'image_scale', 'offset_x', 'offset_y'):
                if key in style and style[key] != int(self.preset_editor_widgets[key].get_value()):
                    self.preset_editor_widgets[key].set_value(style[key])
        finally:
            self._preset_canvas_drag_updating = False
        self._preset_canvas_guides = guides
        self.preset_canvas_overlay.queue_draw()

    def _preset_canvas_drag_end(self, *_):
        before = self._preset_canvas_before_drag
        self._preset_canvas_before_drag = None
        self._preset_canvas_guides = (None, None)
        self.preset_canvas_overlay.queue_draw()
        if before is None:
            return
        if self._preset_editor_active():
            try:
                if before != self._preset_canvas_style():
                    self._preset_editor_changed()  # uma só entrada de histórico por gesto
            except (ValueError, KeyError, TypeError):
                pass
        self.preset_canvas_status.set_text('Rascunho local atualizado; use Salvar ou Salvar como para persistir.')

    def _preset_editor_active(self):
        return (self._preset_editor_draft is not None
                and self._preset_active() == self._preset_editor_draft['id'])

    def _preset_editor_collect(self):
        style = {}
        for key, _ in self.preset_editor_fields:
            value = self.preset_editor_widgets[key].get_text()
            style[key] = None if key == 'text' and value == '' else value
        for key, options in self.preset_editor_enums.items():
            index = self.preset_editor_widgets[key].get_selected()
            style[key] = options[index] if index < len(options) else options[0]
        for key in ('font_size', 'offset_x', 'offset_y', 'image_x', 'image_y', 'image_scale'):
            style[key] = int(self.preset_editor_widgets[key].get_value())
        style['show_text'] = self.preset_editor_show_text.get_active()
        return {'appearance': style, 'image': self.preset_editor_image.get_text()}

    def _preset_editor_fill(self, snapshot):
        self._preset_editor_sync = True
        try:
            style = snapshot['appearance']
            for key, _ in self.preset_editor_fields:
                self.preset_editor_widgets[key].set_text(style.get(key) or '')
            for key, options in self.preset_editor_enums.items():
                self.preset_editor_widgets[key].set_selected(options.index(style[key]))
            for key in ('font_size', 'offset_x', 'offset_y', 'image_x', 'image_y', 'image_scale'):
                self.preset_editor_widgets[key].set_value(style[key])
            self.preset_editor_show_text.set_active(style['show_text'])
            self.preset_editor_image.set_text(snapshot['image'])
        finally:
            self._preset_editor_sync = False
        self._preset_editor_controls()
        self._preset_editor_schedule()
        self._preset_canvas_guides = (None, None)
        self.preset_canvas_overlay.queue_draw()

    def _preset_editor_changed(self, *_):
        if self._preset_editor_sync or self._preset_canvas_drag_updating or not self._preset_editor_draft:
            return
        snapshot = json.dumps(self._preset_editor_collect(), ensure_ascii=False, sort_keys=True)
        if not self._preset_editor_history or snapshot != self._preset_editor_history[self._preset_editor_cursor]:
            self._preset_editor_history = self._preset_editor_history[:self._preset_editor_cursor + 1]
            self._preset_editor_history.append(snapshot)
            self._preset_editor_cursor += 1
            if len(self._preset_editor_history) > 101:
                # Preservar primeiro estado e até 100 revisões recentes.
                self._preset_editor_history.pop(1)
                self._preset_editor_cursor -= 1
        self._preset_editor_controls()
        self._preset_editor_schedule()
        self.preset_canvas_overlay.queue_draw()

    def _preset_editor_controls(self, *_):
        if not hasattr(self, 'preset_editor_save_btn'):
            return
        busy = any(command in self._busy for command in (
            'preset_editor_load', 'preset_editor_save', 'preset_editor_save_as'))
        active = self._preset_editor_active() and not busy
        dirty = bool(self._preset_editor_history and self._preset_editor_cursor >= 0
                     and self._preset_editor_history[self._preset_editor_cursor] != self._preset_editor_history[0])
        self.preset_editor_save_btn.set_sensitive(active and dirty)
        self.preset_editor_save_as_btn.set_sensitive(active and bool(self.preset_editor_as_name.get_text().strip()))
        self.preset_editor_undo_btn.set_sensitive(active and self._preset_editor_cursor > 0)
        self.preset_editor_redo_btn.set_sensitive(active and self._preset_editor_cursor + 1 < len(self._preset_editor_history))
        self.preset_editor_load_btn.set_sensitive(bool(self._preset_active()) and not busy)
        self.preset_editor_title.set_text(
            ('Rascunho: ' + self._preset_editor_draft['name'] + (' *' if dirty else ''))
            if self._preset_editor_draft else 'Nenhum rascunho carregado.')

    def _preset_editor_load(self, *_):
        ident = self._preset_active()
        if not ident:
            return
        dirty = (self._preset_editor_draft and self._preset_editor_history
                 and self._preset_editor_history[self._preset_editor_cursor] != self._preset_editor_history[0])
        if dirty:
            dialog = Gtk.MessageDialog(transient_for=self, modal=True,
                message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE,
                text='Descartar alterações não salvas do preset?')
            dialog.format_secondary_text('O rascunho atual será substituído. Os arquivos salvos permanecerão intactos.')
            dialog.add_button('Cancelar', Gtk.ResponseType.CANCEL)
            dialog.add_button('Descartar rascunho', Gtk.ResponseType.ACCEPT)
            def done(widget, response):
                widget.destroy()
                if response == Gtk.ResponseType.ACCEPT:
                    self._call('preset_editor_load', id=ident)
            dialog.connect('response', done)
            dialog.present()
        else:
            self._call('preset_editor_load', id=ident)
            self.preset_editor_status.set_text('Carregando preset do disco…')

    def _preset_editor_undo(self, *_):
        if self._preset_editor_cursor > 0 and self._preset_editor_active():
            self._preset_editor_cursor -= 1
            self._preset_editor_fill(json.loads(self._preset_editor_history[self._preset_editor_cursor]))

    def _preset_editor_redo(self, *_):
        if self._preset_editor_active() and self._preset_editor_cursor + 1 < len(self._preset_editor_history):
            self._preset_editor_cursor += 1
            self._preset_editor_fill(json.loads(self._preset_editor_history[self._preset_editor_cursor]))

    def _preset_editor_choose_image(self, *_):
        if not self._preset_editor_active():
            return
        chooser = Gtk.FileChooserNative.new('Selecionar imagem do preset', self, Gtk.FileChooserAction.OPEN,
                                           'Selecionar', 'Cancelar')
        def selected(dialog, result):
            if result == Gtk.ResponseType.ACCEPT and dialog.get_file():
                path = dialog.get_file().get_path()
                if path:
                    self.preset_editor_image.set_text(path)
        chooser.connect('response', selected)
        chooser.show()

    def _preset_editor_schedule(self):
        if self._preset_editor_timer:
            GLib.source_remove(self._preset_editor_timer)
        if self._preset_editor_active():
            self._preset_editor_timer = GLib.timeout_add(350, self._preset_editor_preview)

    def _preset_editor_preview(self):
        self._preset_editor_timer = 0
        if not self._preset_editor_active():
            return False
        if 'preset_editor_preview' in self._busy:
            self._preset_editor_preview_pending = True
        else:
            self._call('preset_editor_preview', id=self._preset_editor_draft['id'],
                       revision=self._preset_editor_draft['revision'], **self._preset_editor_collect())
        return False

    def _preset_editor_save(self, *_):
        if self._preset_editor_active():
            self._call('preset_editor_save', id=self._preset_editor_draft['id'],
                       revision=self._preset_editor_draft['revision'], **self._preset_editor_collect())

    def _preset_editor_save_as(self, *_):
        if self._preset_editor_active():
            self._call('preset_editor_save_as', id=self._preset_editor_draft['id'],
                       revision=self._preset_editor_draft['revision'], name=self.preset_editor_as_name.get_text(),
                       **self._preset_editor_collect())

    def _preset_editor_received(self, command, response):
        if command == 'preset_editor_load':
            self._preset_editor_draft = {key: response[key] for key in ('id', 'name', 'revision')}
            self._preset_canvas_preview_path = None
            self._preset_canvas_render_image()
            style = response['appearance']
            if style is None:
                from vision02.profiles.models import KeyAppearance
                style = vars(KeyAppearance())
            snapshot = {'appearance': style, 'image': response['image']}
            self._preset_editor_history = [json.dumps(snapshot, ensure_ascii=False, sort_keys=True)]
            self._preset_editor_cursor = 0
            self._preset_editor_fill(snapshot)
            self.preset_editor_status.set_text('Rascunho carregado. Edite e revise a prévia antes de salvar.')
        elif command == 'preset_editor_preview':
            if self._preset_editor_active() and response['id'] == self._preset_editor_draft['id']:
                self.preset_editor_picture.set_file(Gio.File.new_for_path(response['image']))
                self._preset_canvas_preview_path = response['image']
                self._preset_canvas_render_image()
                self.preset_canvas_overlay.queue_draw()
                self.preset_editor_status.set_text('Prévia local atualizada. Nenhum YAML ou LCD foi alterado.')
            if self._preset_editor_preview_pending:
                self._preset_editor_preview_pending = False
                self._preset_editor_schedule()
        elif command in ('preset_editor_save', 'preset_editor_save_as'):
            if command == 'preset_editor_save':
                self._preset_editor_draft['revision'] = response['revision']
                snapshot = self._preset_editor_collect()
                snapshot['image'] = response['image']
                self._preset_editor_fill(snapshot)
                self._preset_editor_history = [json.dumps(snapshot, ensure_ascii=False, sort_keys=True)]
                self._preset_editor_cursor = 0
                self.preset_editor_status.set_text('Preset salvo. Backup: ' + response['backup'])
            else:
                self.preset_editor_status.set_text('Nova variação criada. Selecione-a e carregue no editor.')
                self.preset_editor_as_name.set_text('')
            self._call('preset_list')
        self._preset_editor_controls()

    def _gallery_item(self):
        ident = self._preset_active()
        return next((item for item in self._gallery_items if item['id'] == ident), None)

    def _gallery_update_selected(self):
        if not hasattr(self, 'gallery_favorite_btn'):
            return
        item = self._gallery_item()
        busy = self._preset_busy()
        selected = item is not None and not busy
        self.gallery_favorite_btn.set_sensitive(selected)
        self.gallery_category_btn.set_sensitive(selected)
        self.gallery_duplicate_btn.set_sensitive(selected)
        if item:
            self.gallery_favorite_btn.set_label('Remover dos favoritos' if item['favorite'] else 'Marcar como favorito')
            self.gallery_category_entry.set_text(item['category'])
        else:
            self.gallery_favorite_btn.set_label('Marcar como favorito')
            self.gallery_category_entry.set_text('')

    def _gallery_choose(self, _button, ident):
        ids = [p['id'] for p in self._preset_items]
        if ident not in ids:
            return
        # A seleção do cartão utiliza o DropDown v10; confirmação antiga é zerada.
        self.preset_confirm.set_active(False)
        self.preset_combo.set_selected(ids.index(ident))
        item = self._gallery_item()
        if item:
            try:
                self.preset_picture.set_file(Gio.File.new_for_path(item['thumbnail']))
            except (GLib.Error, OSError):
                self.preset_picture.set_paintable(None)
        self._gallery_update_selected()

    def _gallery_render(self, *_):
        if not hasattr(self, 'gallery_flow'):
            return
        while (child := self.gallery_flow.get_first_child()) is not None:
            self.gallery_flow.remove(child)
        categories = getattr(self, '_gallery_categories', ['Todas as categorias'])
        idx = self.gallery_category_filter.get_selected()
        category = categories[idx] if 0 <= idx < len(categories) else 'Todas as categorias'
        query = self.gallery_search.get_text().casefold().strip()
        favorite_only = self.gallery_favorites_only.get_active()
        visible = [item for item in self._gallery_items
                   if (not query or query in item['name'].casefold()
                       or query in item['category'].casefold())
                   and (not favorite_only or item['favorite'])
                   and (idx == 0 or item['category'] == category)]
        for item in visible:
            card = Gtk.Button()
            card.set_tooltip_text(item['name'] + (' · ' + item['category'] if item['category'] else ''))
            box = _box(False, 4)
            pic = Gtk.Picture()
            pic.set_size_request(100, 100)
            pic.set_content_fit(Gtk.ContentFit.CONTAIN)
            pic.set_file(Gio.File.new_for_path(item['thumbnail']))
            box.append(pic)
            title = Gtk.Label(label=('★ ' if item['favorite'] else '') + item['name'])
            title.set_max_width_chars(17)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            box.append(title)
            if item['category']:
                cat = Gtk.Label(label=item['category'])
                cat.add_css_class('caption')
                box.append(cat)
            card.set_child(box)
            card.connect('clicked', self._gallery_choose, item['id'])
            self.gallery_flow.insert(card, -1)
        self.gallery_count.set_text(f'{len(visible)} de {len(self._gallery_items)} presets exibidos.')

    def _gallery_refresh(self, items):
        self._gallery_items = items
        previous = 'Todas as categorias'
        selected = self.gallery_category_filter.get_selected()
        if hasattr(self, '_gallery_categories') and 0 <= selected < len(self._gallery_categories):
            previous = self._gallery_categories[selected]
        categories = ['Todas as categorias'] + sorted({p['category'] for p in items if p['category']}, key=str.casefold)
        self._gallery_categories = categories
        self.gallery_category_filter.set_model(Gtk.StringList.new(categories))
        self.gallery_category_filter.set_selected(categories.index(previous) if previous in categories else 0)
        self._gallery_render()
        self._gallery_update_selected()

    def _gallery_favorite(self, *_):
        item = self._gallery_item()
        if item and not self._preset_busy():
            self._call('preset_gallery_favorite', id=item['id'], favorite=not item['favorite'])

    def _gallery_category(self, *_):
        item = self._gallery_item()
        if item and not self._preset_busy():
            self._call('preset_gallery_category', id=item['id'], category=self.gallery_category_entry.get_text())

    def _gallery_duplicate(self, *_):
        item = self._gallery_item()
        if item and not self._preset_busy():
            name = self.gallery_duplicate_name.get_text().strip()
            if not name:
                self.preset_status.set_text('Informe um nome novo para duplicar o preset.')
                return
            self._call('preset_gallery_duplicate', id=item['id'], name=name)

    def _preset_active(self):
        index = self.preset_combo.get_selected()
        return (self._preset_items[index]['id']
                if 0 <= index < len(self._preset_items) else None)

    def _preset_selected(self, *_):
        if hasattr(self, 'preset_editor_save_btn'):
            self._preset_editor_controls()
        self.preset_confirm.set_active(False)
        self.preset_picture.set_paintable(None)
        self._preset_controls()
        self._gallery_update_selected()

    def _preset_target_toggled(self, *_):
        self.preset_confirm.set_active(False)
        self._preset_controls()

    def _preset_busy(self):
        return any(cmd in self._busy for cmd in ('quick_save', 'quick_batch_appearance',
                   'quick_inspect', 'preset_apply', 'preset_create', 'preset_delete',
                   'preset_rename', 'preset_import', 'preset_export', 'preset_gallery',
                   'preset_gallery_favorite', 'preset_gallery_category',
                   'preset_gallery_duplicate', 'preset_editor_load', 'preset_editor_preview',
                   'preset_editor_save', 'preset_editor_save_as'))

    def _preset_controls(self, *_):
        if not hasattr(self, 'preset_apply_btn'):
            return
        busy = self._preset_busy()
        loaded = self._quick_loaded is not None and not self._quick_dirty and not busy
        configured = self._selected_key in self._quick_batch_configured
        name = bool(self.preset_name.get_text().strip())
        selected = self._preset_active() is not None
        self.preset_create_btn.set_sensitive(loaded and configured and name)
        self.preset_rename_btn.set_sensitive(selected and name and not busy)
        self.preset_delete_btn.set_sensitive(selected and not busy)
        self.preset_preview_btn.set_sensitive(selected and loaded)
        self.preset_import_btn.set_sensitive(not busy)
        self.preset_export_btn.set_sensitive(selected and not busy)
        for key_id, check in self.preset_targets.items():
            enabled = loaded and selected and key_id in self._quick_batch_configured
            check.set_sensitive(enabled)
            if not enabled and check.get_active():
                check.set_active(False)
        targets = any(check.get_active() for check in self.preset_targets.values())
        self.preset_confirm.set_sensitive(loaded and selected and targets)
        self.preset_apply_btn.set_sensitive(loaded and selected and targets
                                             and self.preset_confirm.get_active())
        if hasattr(self, 'gallery_favorite_btn'):
            self._gallery_update_selected()

    def _preset_create(self, *_):
        if not self._quick_loaded or self._quick_dirty or self._preset_busy():
            self.preset_status.set_text('Salve ou descarte a edição antes de criar um preset.')
            return
        self._call('preset_create', name=self.preset_name.get_text(), profile=self._current,
                   key_id=self._selected_key, sha256=self._quick_loaded['sha256'])
        self.preset_status.set_text('Salvando preset da aparência já gravada…')

    def _preset_rename(self, *_):
        if self._preset_active() and not self._preset_busy():
            self._call('preset_rename', id=self._preset_active(), name=self.preset_name.get_text())

    def _preset_delete(self, *_):
        ident = self._preset_active()
        if not ident or self._preset_busy():
            return
        dialog = Gtk.MessageDialog(transient_for=self, modal=True,
             message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE,
             text='Excluir preset da biblioteca?')
        dialog.format_secondary_text('Teclas já configuradas manterão a aparência aplicada.')
        dialog.add_button('Cancelar', Gtk.ResponseType.CANCEL)
        dialog.add_button('Excluir', Gtk.ResponseType.ACCEPT)
        def done(widget, response):
            widget.destroy()
            if response == Gtk.ResponseType.ACCEPT:
                self._call('preset_delete', id=ident)
        dialog.connect('response', done)
        dialog.present()

    def _preset_preview(self, *_):
        if self._preset_active() and self._quick_loaded and not self._quick_dirty:
            self._call('preset_preview', id=self._preset_active(), profile=self._current,
                       key_id=self._selected_key)
            self.preset_status.set_text('Gerando prévia local do preset…')

    def _preset_apply(self, *_):
        ident = self._preset_active()
        loaded = self._quick_loaded
        targets = [key for key, check in self.preset_targets.items() if check.get_active()]
        if not (ident and loaded and not self._quick_dirty and not self._preset_busy()
                and targets and self.preset_confirm.get_active()
                and all(key in self._quick_batch_configured for key in targets)):
            self.preset_status.set_text('Seleção inválida; confira os destinos e a confirmação.')
            return
        self._call('preset_apply', id=ident, profile=self._current,
                   targets=targets, sha256=loaded['sha256'])
        self.preset_status.set_text('Validando aparência e salvando YAML com backup…')
        self._preset_controls()

    def _preset_file(self, action, callback, title, accept):
        chooser = Gtk.FileChooserNative.new(title, self, action, accept, 'Cancelar')
        if action == Gtk.FileChooserAction.SAVE:
            chooser.set_current_name((self._preset_active() or 'preset') + '.zip')
        def done(dialog, response):
            selected = dialog.get_file()
            path = selected.get_path() if selected is not None else None
            dialog.destroy()
            if response == Gtk.ResponseType.ACCEPT and path:
                callback(path)
        chooser.connect('response', done)
        chooser.show()

    def _preset_import(self, *_):
        if not self._preset_busy():
            self._preset_file(Gtk.FileChooserAction.OPEN,
                              lambda path: self._call('preset_import', path=path),
                              'Importar preset ZIP', 'Importar')

    def _preset_export(self, *_):
        ident = self._preset_active()
        if ident and not self._preset_busy():
            self._preset_file(Gtk.FileChooserAction.SAVE,
                              lambda path: self._call('preset_export', id=ident, path=path),
                              'Exportar preset ZIP', 'Exportar')

    def _preset_received(self, command, response):
        if command.startswith('preset_editor_'):
            self._preset_editor_received(command, response)
            return
        if command == 'preset_gallery':
            self._gallery_refresh(response['items'])
            return
        if command in ('preset_gallery_favorite', 'preset_gallery_category'):
            self.preset_status.set_text('Metadados da galeria atualizados.')
            self._call('preset_gallery')
            return
        if command == 'preset_gallery_duplicate':
            self.preset_status.set_text('Preset duplicado na biblioteca.')
            self.gallery_duplicate_name.set_text('')
            self._call('preset_list')
            return
        if command == 'preset_list':
            old = self._preset_active()
            self._preset_items = response['presets']
            self.preset_combo.set_model(Gtk.StringList.new(
                [p['name'] for p in self._preset_items] or ['Nenhum preset salvo']))
            ids = [p['id'] for p in self._preset_items]
            self.preset_combo.set_selected(ids.index(old) if old in ids else
                                            (0 if ids else Gtk.INVALID_LIST_POSITION))
            self.preset_status.set_text(f'{len(ids)} preset(s) na biblioteca.')
            self._call('preset_gallery')
        elif command == 'preset_preview':
            if response['id'] == self._preset_active():
                self.preset_picture.set_file(Gio.File.new_for_path(response['image']))
                self.preset_status.set_text('Prévia gerada localmente; YAML e LCD não alterados.')
        elif command == 'preset_apply':
            self.preset_status.set_text(
                f"{len(response['targets'])} tecla(s) com preset salvo. Backup: {response['backup']}")
            self.preset_confirm.set_active(False)
            self._quick_batch_clipboard = None
            self._quick_batch_pending_apply = True
            self._quick_dirty = False
            self._quick_loaded = None
            self._quick_load()
            self._call('previews')
        else:
            self.preset_status.set_text(f'{command}: operação concluída.')
            if command != 'preset_export':
                self._call('preset_list')
        self._preset_controls()

    def _quick_batch_target_toggled(self, *_):
        # Destinos diferentes exigem nova confirmação antes de gravar.
        self.quick_batch_confirm.set_active(False)
        self._quick_batch_controls()

    def _quick_batch_controls(self, *_):
        if not hasattr(self, 'quick_batch_apply_btn'):
            return
        loaded = self._quick_loaded
        busy = any(cmd in self._busy for cmd in (
            'quick_batch_appearance', 'quick_save', 'quick_preview', 'quick_inspect'))
        valid_source = bool(loaded and not self._quick_dirty and not busy
                            and self._selected_key in self._quick_batch_configured)
        self.quick_batch_copy_btn.set_sensitive(valid_source)
        clip = self._quick_batch_clipboard
        valid_clip = bool(clip and loaded and clip['profile'] == self._current
                          and clip['sha256'] == loaded['sha256'])
        selected = []
        for ident, check in self.quick_batch_targets.items():
            available = (valid_clip and not self._quick_dirty and not busy
                         and ident in self._quick_batch_configured
                         and ident != clip['source_key'])
            check.set_sensitive(bool(available))
            if not available and check.get_active():
                check.set_active(False)
            if available and check.get_active():
                selected.append(ident)
        self.quick_batch_confirm.set_sensitive(bool(valid_clip and not busy and selected
                                                       and not self._quick_dirty))
        self.quick_batch_apply_btn.set_sensitive(bool(valid_clip and selected and not busy
                             and not self._quick_dirty and self.quick_batch_confirm.get_active()))

    def _quick_batch_copy(self, *_):
        if (not self._quick_loaded or self._quick_dirty
                or self._selected_key not in self._quick_batch_configured
                or any(x in self._busy for x in ('quick_save', 'quick_batch_appearance'))):
            self.quick_batch_status.set_text('Salve ou descarte alterações antes de copiar.')
            return
        self._quick_batch_clipboard = {
            'profile': self._current, 'source_key': self._selected_key,
            'sha256': self._quick_loaded['sha256'],
        }
        for check in self.quick_batch_targets.values():
            check.set_active(False)
        self.quick_batch_confirm.set_active(False)
        self.quick_batch_source.set_text(
            f"Origem: tecla {self._selected_key:02d} · perfil {self._current} · versão salva")
        self.quick_batch_status.set_text('Selecione os destinos e confirme a gravação.')
        self._quick_batch_controls()

    def _quick_batch_apply(self, *_):
        clip = self._quick_batch_clipboard
        loaded = self._quick_loaded
        if (not clip or not loaded or self._quick_dirty or
                clip['profile'] != self._current or clip['sha256'] != loaded['sha256'] or
                not self.quick_batch_confirm.get_active() or 'quick_batch_appearance' in self._busy):
            self.quick_batch_status.set_text('Cópia inválida ou edição pendente; copie novamente.')
            return
        targets = [ident for ident, check in self.quick_batch_targets.items()
                   if check.get_active() and check.get_sensitive()
                   and ident in self._quick_batch_configured and ident != clip['source_key']]
        if not targets:
            self.quick_batch_status.set_text('Selecione pelo menos uma tecla configurada.')
            return
        self._call('quick_batch_appearance', profile=clip['profile'],
                   source_key=clip['source_key'], targets=targets, sha256=clip['sha256'])
        self.quick_batch_status.set_text('Salvando aparências em lote com backup…')
        if hasattr(self, '_quick_controls'):
            self._quick_controls()
        if hasattr(self, '_update_style_sensitivity'):
            self._update_style_sensitivity()
        self._quick_batch_controls()

    def _build_composition_canvas(self, parent):
        group = Gtk.Expander(label='Composição — arrastar texto ou imagem')
        group.set_expanded(True)
        parent.append(group)
        column = _box(False, 6)
        column.set_margin_top(8)
        group.set_child(column)
        column.append(_label('Clique em um elemento para abrir suas propriedades; '
                             'arraste para ajustar sua posição. A moldura mostra '
                             'a área aproximada selecionável (não os pixels exatos).',
                             wrap=True, style='caption'))
        self.composition_target = Gtk.DropDown.new_from_strings(['Imagem', 'Texto'])
        column.append(self.composition_target)
        self.composition_selected_label = _label('Seleção atual: Imagem', style='caption')
        column.append(self.composition_selected_label)
        layers = Gtk.Expander(label='Camadas — seleção local')
        layers.set_expanded(True)
        column.append(layers)
        layers_box = _box(False, 6)
        layers_box.set_margin_top(6)
        layers.set_child(layers_box)
        layers_box.append(_label(
            'Selecione uma camada sem alterar o YAML. A ordem de desenho no LCD '
            'é fixa: Imagem atrás do Texto.', style='caption', wrap=True
        ))
        layer_row = _box(True, 6)
        layers_box.append(layer_row)
        self.composition_layer_buttons = {}
        for layer, title in (('image', 'Imagem'), ('text', 'Texto')):
            button = _button(layer_row, title,
                             lambda _button, layer=layer: self._composition_select_layer(layer))
            button.set_tooltip_text('Selecionar camada ' + title + ' para editar na Composição')
            self.composition_layer_buttons[layer] = button
        # Controles v6: estado SOMENTE da sessão GTK; não faz parte do YAML.
        layer_controls = _box(False, 4)
        layers_box.append(layer_controls)
        self.composition_v6_lock_checks = {}
        self.composition_v6_outline_checks = {}
        for layer, title in (('image', 'Imagem'), ('text', 'Texto')):
            row = _box(True, 8)
            layer_controls.append(row)
            lock = Gtk.CheckButton(label='Bloquear ' + title)
            lock.connect('toggled', self._composition_v6_lock_changed, layer)
            row.append(lock)
            self.composition_v6_lock_checks[layer] = lock
            outline = Gtk.CheckButton(label='Mostrar moldura ' + title)
            outline.set_active(True)
            outline.connect('toggled', self._composition_v6_outline_changed, layer)
            row.append(outline)
            self.composition_v6_outline_checks[layer] = outline
        layers_box.append(_label(
            'Mostrar moldura controla apenas os contornos do editor.',
            style='caption', wrap=True,
        ))
        # v7: visibilidade REAL dos pixels do preview, sem alterar o YAML.
        self.composition_v7_visibility_checks = {}
        for layer, title in (('image', 'Imagem'), ('text', 'Texto')):
            check = Gtk.CheckButton(label='Exibir pixels da ' + title + ' (prévia)')
            check.set_active(True)
            check.set_sensitive(False)
            check.connect('toggled', self._composition_v7_visibility_changed, layer)
            layers_box.append(check)
            self.composition_v7_visibility_checks[layer] = check
        self.composition_v8_status = _label(
            'Seleção: aguardando máscaras RGBA da prévia local.',
            style='caption', wrap=True,
        )
        layers_box.append(self.composition_v8_status)
        layers_box.append(_label(
            'Os controles v7 mostram/ocultam pixels apenas na Composição. '
            'A prévia da aba Imagem, o YAML e o LCD continuam inalterados. '
            'Para teclas legadas sem aparência personalizada, use a prévia original.',
            style='caption', wrap=True,
        ))
        center_row = _box(True, 6)
        layers_box.append(center_row)
        self.composition_v6_center_buttons = {}
        for axis, title in (('x', 'Centralizar X'), ('y', 'Centralizar Y')):
            self.composition_v6_center_buttons[axis] = _button(
                center_row, title,
                lambda _button, axis=axis: self._composition_v6_center(axis),
            )
        layers_box.append(_label(
            'Centralização usa caixa geométrica aproximada. Restaurar posição/tamanho '
            'usa o histórico existente. Bloqueio impede novos arrastes, ajustes finos '
            'e restaurações, mas permite desfazer/refazer operações anteriores.',
            style='caption', wrap=True,
        ))
        self.composition_layers_status = _label('Nenhuma tecla carregada.', style='caption')
        layers_box.append(self.composition_layers_status)
        self.composition_cycle_overlap = _button(
            layers_box, 'Alternar camada no último ponto sobreposto',
            self._composition_cycle_overlap_action, sensitive=False
        )
        layers_box.append(_label(
            'Clique em uma sobreposição no preview, volte à Composição e use '
            'Alternar; ou escolha Imagem/Texto acima. A seleção não reordena '
            'os elementos nem modifica o dispositivo.', style='caption', wrap=True
        ))
        self.composition_prefer_image = Gtk.CheckButton(
            label='Priorizar imagem quando imagem e texto se sobrepõem'
        )
        self.composition_prefer_image.connect('toggled', self._composition_selection_priority_changed)
        column.append(self.composition_prefer_image)
        self.composition_grid = Gtk.CheckButton(label='Encaixar na grade de 5 pixels')
        column.append(self.composition_grid)
        self.composition_align = Gtk.CheckButton(
            label='Encaixe inteligente no centro e nas bordas (sem grade)'
        )
        self.composition_align.set_active(True)
        self.composition_align.connect('toggled', self._composition_alignment_changed)
        column.append(self.composition_align)
        self.composition_coordinates = _label('Posição do elemento selecionado', style='caption')
        column.append(self.composition_coordinates)
        nudge_row = _box(True, 6)
        column.append(nudge_row)
        nudge_row.append(_label('Ajuste fino:'))
        self.composition_nudge_step = Gtk.DropDown.new_from_strings(['1 px', '5 px'])
        nudge_row.append(self.composition_nudge_step)
        self.composition_nudge_buttons = []
        for direction, title in (('left', '←'), ('up', '↑'),
                                 ('down', '↓'), ('right', '→')):
            button = _button(nudge_row, title,
                             lambda _button, direction=direction: self._composition_nudge(direction))
            button.set_tooltip_text('Mover elemento para ' + {
                'left': 'esquerda', 'up': 'cima',
                'down': 'baixo', 'right': 'direita',
            }[direction])
            self.composition_nudge_buttons.append(button)
        zoom_row = _box(True, 8)
        column.append(zoom_row)
        zoom_row.append(_label('Zoom da edição:'))
        self.composition_zoom = Gtk.DropDown.new_from_strings(['100%', '150%', '200%'])
        self.composition_zoom.connect('notify::selected', self._composition_zoom_changed)
        zoom_row.append(self.composition_zoom)
        tools = _box(True, 6)
        column.append(tools)
        self.composition_undo = _button(tools, 'Desfazer', self._composition_undo_action)
        self.composition_redo = _button(tools, 'Refazer', self._composition_redo_action)
        self.composition_reset = _button(column, 'Restaurar posição/tamanho do elemento', self._composition_reset_action)
        column.append(_label('Ctrl+Setas: mover 1 px; Ctrl+Shift+Setas: mover 5 px '
                             '(somente na aba Composição, fora de campos editáveis). '
                             'Ctrl+Z / Ctrl+Shift+Z: desfazer/refazer. '
                             'Arraste a alça ↘ para redimensionar.',
                             style='caption', wrap=True))
        self._composition_update_coordinates()

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
        # Alça REAL de GTK, independente do DrawingArea. Em algumas sessões
        # GTK/Wayland a camada Cairo das guias pode não ser mostrada; o frame
        # interativo continua visível e recebe seu próprio evento de arrasto.
        self.composition_resize_handle = Gtk.Frame()
        self.composition_resize_handle.add_css_class('vision02-resize-handle')
        self.composition_resize_handle.set_size_request(40, 40)
        self.composition_resize_handle.set_halign(Gtk.Align.END)
        self.composition_resize_handle.set_valign(Gtk.Align.END)
        self.composition_resize_handle.set_margin_end(7)
        self.composition_resize_handle.set_margin_bottom(7)
        self.composition_resize_handle.set_tooltip_text('Arraste esta alça para redimensionar a imagem')
        resize_label = Gtk.Label(label='↘')
        resize_label.set_halign(Gtk.Align.CENTER)
        resize_label.set_valign(Gtk.Align.CENTER)
        self.composition_resize_handle.set_child(resize_label)
        self.composition_surface.add_overlay(self.composition_resize_handle)
        resize_drag = Gtk.GestureDrag.new()
        resize_drag.connect('drag-begin', self._composition_resize_drag_begin)
        resize_drag.connect('drag-update', self._composition_drag_update)
        resize_drag.connect('drag-end', self._composition_drag_end)
        self.composition_resize_handle.add_controller(resize_drag)
        self.composition_target.connect('notify::selected', self._composition_target_changed)
        self.composition_resize_handle.set_visible(False)
        gesture = Gtk.GestureDrag.new()
        gesture.connect('drag-begin', self._composition_drag_begin)
        gesture.connect('drag-update', self._composition_drag_update)
        gesture.connect('drag-end', self._composition_drag_end)
        self.composition_surface.add_controller(gesture)
        # Clique simples seleciona e abre a aba; arrastar permanece em Composição.
        click = Gtk.GestureClick.new()
        click.set_button(1)
        click.connect('pressed', self._composition_click_pressed)
        click.connect('released', self._composition_click_released)
        self.composition_surface.add_controller(click)
        self.composition_status = _label('Aguardando prévia local da tecla selecionada.',
                                         style='caption', wrap=True)
        column.append(self.composition_status)
        self._composition_update_layer_panel()
        column.append(_label('Imagem: posição e escala nos controles Aparência visual. '
                             'Texto: desloque diretamente, com os limites atuais de ±40 px. '
                             'Arrastar ativa a aparência personalizada.', wrap=True,
                             style='caption'))

    def _composition_draw(self, _area, cr, width, height):
        # Guias são uma camada transparente; nunca integram o JPEG/HID.
        extent = min(width, height)
        if extent <= 0:
            return
        cx, cy, unit = display_geometry(width, height, self._composition_zoom)
        cr.set_line_width(1)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.30)
        for value in (-50, -25, 25, 50):
            pos = value * unit
            cr.move_to(cx + pos, 0)
            cr.line_to(cx + pos, height)
            cr.move_to(0, cy + pos)
            cr.line_to(width, cy + pos)
        cr.stroke()
        cr.set_source_rgba(0.20, 0.70, 1.0, 0.85)
        cr.set_line_width(1.4)
        cr.move_to(cx, 0)
        cr.line_to(cx, height)
        cr.move_to(0, cy)
        cr.line_to(width, cy)
        cr.stroke()
        # Guias inteligentes, realçadas apenas durante a operação ativa.
        gx, gy = self._composition_guide
        cr.set_source_rgba(0.95, 0.73, 0.25, 0.96)
        cr.set_line_width(2.0)
        if gx is not None:
            cr.move_to(cx + gx*unit, 0)
            cr.line_to(cx + gx*unit, height)
        if gy is not None:
            cr.move_to(0, cy + gy*unit)
            cr.line_to(width, cy + gy*unit)
        cr.stroke()
        # Moldura da seleção: mesma geometria (com recorte e zoom) usada
        # pelo hit-test. Não muda o PNG, nem salva ou aplica configurações.
        if self._quick_loaded is not None:
            regions = visual_element_regions(
                width, height, self._composition_zoom,
                image_present=bool(self.quick_image.get_text().strip()),
                image_x=int(self.style_numbers['image_x'].get_value()),
                image_y=int(self.style_numbers['image_y'].get_value()),
                image_scale=int(self.style_numbers['image_scale'].get_value()),
                text=self.quick_visual_text.get_text() or self.quick_label.get_text(),
                show_text=self.style_show_text.get_active(),
                offset_x=int(self.style_numbers['offset_x'].get_value()),
                offset_y=int(self.style_numbers['offset_y'].get_value()),
                font_size=int(self.style_numbers['font_size'].get_value()),
                horizontal=CHOICES['horizontal'][self.style_choices['horizontal'].get_selected()],
                vertical=CHOICES['vertical'][self.style_choices['vertical'].get_selected()],
            )
            # v8: moldura pelo conteúdo alfa real quando a prévia já foi gerada.
            # Sem máscaras (perfil legado/erro): usa regiões aproximadas da v3.
            if getattr(self, '_composition_v8_masks', None):
                regions = mask_regions(
                    self._composition_v8_masks, width, height,
                    self._composition_zoom, visible=self._composition_v7_visible,
                )
            target = 'image' if self.composition_target.get_selected() == 0 else 'text'
            outlines = getattr(self, '_composition_v6_outlines', {'image': True, 'text': True})
            region = regions.get(target) if outlines.get(target, True) else None
            # Pistas discretas das camadas não selecionadas. São apenas linhas
            # no overlay local; as duas chamadas rectangle() do alvo ativo
            # permanecem idênticas para preservar a renderização legada.
            for other, other_region in regions.items():
                if other == target or not outlines.get(other, True):
                    continue
                left, top = other_region.x, other_region.y
                right, bottom = left + other_region.width, top + other_region.height
                length = min(9, other_region.width / 3, other_region.height / 3)
                cr.set_line_width(1.5)
                cr.set_source_rgba(0.70, 0.75, 0.80, 0.70)
                for px, py, sx, sy in ((left, top, 1, 1), (right, top, -1, 1),
                                       (left, bottom, 1, -1), (right, bottom, -1, -1)):
                    cr.move_to(px + sx*length, py)
                    cr.line_to(px, py)
                    cr.line_to(px, py + sy*length)
                cr.stroke()
            if region is not None:
                # Traço duplicado melhora o contraste em imagens claras e escuras.
                cr.set_line_width(3.5)
                cr.set_source_rgba(0.04, 0.08, 0.14, 0.95)
                cr.rectangle(region.x, region.y, region.width, region.height)
                cr.stroke()
                cr.set_line_width(2.0)
                cr.set_source_rgba(*( (0.22, 0.85, 1.0, 1.0) if target == 'image'
                                     else (1.0, 0.78, 0.25, 1.0)))
                cr.rectangle(region.x, region.y, region.width, region.height)
                cr.stroke()
        # A alça real é um Gtk.Frame separado e continua recebendo o gesto.

    def _composition_target_changed(self, *_):
        if hasattr(self, 'composition_selected_label'):
            self.composition_selected_label.set_text(
                'Seleção atual: Imagem' if self.composition_target.get_selected() == 0
                else 'Seleção atual: Texto'
            )
        self._composition_update_buttons()
        if hasattr(self, '_composition_update_coordinates'):
            self._composition_update_coordinates()
        self.composition_canvas.queue_draw()

    def _composition_available_layers(self):
        if self._quick_loaded is None:
            return ()
        return available_layers(
            image_path=self.quick_image.get_text(),
            text=self.quick_visual_text.get_text() or self.quick_label.get_text(),
            show_text=self.style_show_text.get_active(),
        )

    def _composition_layer_regions(self):
        area = self.composition_canvas
        return visual_element_regions(
            area.get_width(), area.get_height(), self._composition_zoom,
            image_present=bool(self.quick_image.get_text().strip()),
            image_x=int(self.style_numbers['image_x'].get_value()),
            image_y=int(self.style_numbers['image_y'].get_value()),
            image_scale=int(self.style_numbers['image_scale'].get_value()),
            text=self.quick_visual_text.get_text() or self.quick_label.get_text(),
            show_text=self.style_show_text.get_active(),
            offset_x=int(self.style_numbers['offset_x'].get_value()),
            offset_y=int(self.style_numbers['offset_y'].get_value()),
            font_size=int(self.style_numbers['font_size'].get_value()),
            horizontal=CHOICES['horizontal'][self.style_choices['horizontal'].get_selected()],
            vertical=CHOICES['vertical'][self.style_choices['vertical'].get_selected()],
        )

    def _composition_update_layer_panel(self):
        if not hasattr(self, 'composition_layer_buttons'):
            return
        active = self._quick_loaded is not None and 'quick_save' not in self._busy
        layers = self._composition_available_layers()
        target = 'image' if self.composition_target.get_selected() == 0 else 'text'
        for key, button in self.composition_layer_buttons.items():
            button.set_sensitive(active and key in layers)
            if key == target and key in layers:
                button.add_css_class('suggested-action')
            else:
                button.remove_css_class('suggested-action')
        title = {'image': 'Imagem', 'text': 'Texto'}
        text = ', '.join(title[key] for key in layers) if layers else 'nenhuma'
        summary = 'Camadas disponíveis: ' + text
        if hasattr(self, '_composition_v6_locked'):
            indicators = []
            for key in layers:
                if self._composition_v6_locked.get(key, False):
                    indicators.append(title[key] + ': bloqueada')
                if not self._composition_v6_outlines.get(key, True):
                    indicators.append(title[key] + ': moldura oculta')
            if indicators:
                summary += ' | ' + ', '.join(indicators)
        self.composition_layers_status.set_text(summary)
        can_cycle = False
        if active and self._composition_last_overlap is not None:
            x, y = self._composition_last_overlap
            if getattr(self, '_composition_v8_masks', None):
                can_cycle = len(self._composition_v8_candidates(x, y)) == 2
            else:
                can_cycle = len(hit_layer_candidates(self._composition_layer_regions(), x, y)) == 2
        self.composition_cycle_overlap.set_sensitive(can_cycle)
        if hasattr(self, 'composition_v6_lock_checks'):
            for layer in ('image', 'text'):
                self.composition_v6_lock_checks[layer].set_sensitive(active and layer in layers)
                self.composition_v6_outline_checks[layer].set_sensitive(active and layer in layers)
            locked = getattr(self, '_composition_v6_locked', {})
            blocked = is_layer_locked(locked, target)
            for button in self.composition_v6_center_buttons.values():
                button.set_sensitive(active and target in layers and not blocked)

    def _composition_select_layer(self, layer):
        # A camada é somente um alvo de edição: NÃO modifica o formulário,
        # a ordem de renderização, o histórico, o YAML ou o serviço.
        if (self._quick_loaded is None or 'quick_save' in self._busy
                or layer not in self._composition_available_layers()):
            return False
        self.composition_target.set_selected(0 if layer == 'image' else 1)
        # V3: a prioridade só influencia o hit-test nas regiões sobrepostas.
        self.composition_prefer_image.set_active(layer == 'image')
        self.composition_status.set_text(
            ('Imagem' if layer == 'image' else 'Texto') +
            ': camada selecionada para edição local (ordem de desenho preservada).'
        )
        self._composition_update_layer_panel()
        self.composition_canvas.queue_draw()
        return True

    def _composition_capture_overlap(self, x, y):
        if self._quick_loaded is None or 'quick_save' in self._busy:
            self._composition_last_overlap = None
        else:
            regions = self._composition_layer_regions()
            candidates = (self._composition_v8_candidates(x, y)
                          if getattr(self, '_composition_v8_masks', None) else
                          hit_layer_candidates(regions, x, y))
            self._composition_last_overlap = ((x, y) if len(candidates) == 2 else None)
        self._composition_update_layer_panel()

    def _composition_cycle_overlap_action(self, *_):
        if (self._quick_loaded is None or 'quick_save' in self._busy
                or self._composition_last_overlap is None):
            return False
        x, y = self._composition_last_overlap
        current = 'image' if self.composition_target.get_selected() == 0 else 'text'
        if getattr(self, '_composition_v8_masks', None):
            next_layer = next_mask_layer(self._composition_v8_candidates(x, y), current)
        else:
            next_layer = next_overlapping_layer(self._composition_layer_regions(), x, y, current)
        if next_layer is None:
            self._composition_last_overlap = None
            self._composition_update_layer_panel()
            return False
        return self._composition_select_layer(next_layer)

    def _composition_v7_visibility_changed(self, check, layer):
        # Estado exclusivo do preview. Não marca edição pendente.
        self._composition_v7_visible[layer] = bool(check.get_active())
        self._composition_v7_update_picture()
        self._composition_last_overlap = None
        self._composition_update_layer_panel()
        self.composition_canvas.queue_draw()

    def _composition_v7_update_picture(self):
        if not getattr(self, '_composition_v7_paths', None):
            return False
        show_image = self._composition_v7_visible['image']
        show_text = self._composition_v7_visible['text']
        mode = ('both' if show_image and show_text else
                'image' if show_image else 'text' if show_text else 'none')
        path = self._composition_v7_paths.get(mode)
        if not path:
            return False
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        except (GLib.Error, OSError) as exc:
            self.composition_status.set_text('Não foi possível abrir prévia de camada: ' + str(exc))
            return False
        self._composition_pixbuf = pixbuf
        self._composition_preview_path = path
        self._composition_update_zoom()
        self.composition_canvas.queue_draw()
        return True

    def _composition_v7_set_paths(self, paths):
        self._composition_v7_paths = (
            dict(paths) if isinstance(paths, dict) and
            all(isinstance(paths.get(mode), str)
                for mode in ('both', 'image', 'text', 'none')) else {}
        )
        enabled = bool(self._composition_v7_paths)
        for layer in ('image', 'text'):
            self.composition_v7_visibility_checks[layer].set_sensitive(enabled)
        if enabled:
            self._composition_v7_update_picture()

    def _composition_v8_set_components(self, paths):
        """Carrega somente alfa no GTK; nenhum arquivo é modificado.

        Caso faltem os dois RGBA válidos, retorna à seleção geométrica.
        Esta chamada ocorre apenas depois da validação de revisão da prévia.
        """
        self._composition_v8_masks = {}
        if isinstance(paths, dict):
            try:
                result = {}
                for layer in ('image', 'text'):
                    path = paths[layer]
                    if not isinstance(path, str) or not path:
                        raise ValueError('Canal ausente')
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
                    result[layer] = extract_alpha(
                        pixbuf.get_pixels(), pixbuf.get_width(), pixbuf.get_height(),
                        pixbuf.get_rowstride(), pixbuf.get_n_channels(),
                        has_alpha=pixbuf.get_has_alpha(),
                    )
                self._composition_v8_masks = result
            except (KeyError, ValueError, TypeError, GLib.Error, OSError):
                self._composition_v8_masks = {}
        self.composition_v8_status.set_text(
            'Seleção v8: pixels RGBA visíveis; molduras ajustadas ao conteúdo.'
            if self._composition_v8_masks else
            'Seleção por geometria aproximada (sem máscaras RGBA válidas).'
        )
        self._composition_last_overlap = None
        self.composition_canvas.queue_draw()
        self._composition_update_layer_panel()

    def _composition_v8_candidates(self, x, y):
        area = self.composition_canvas
        return mask_candidates(
            self._composition_v8_masks, x, y,
            area.get_width(), area.get_height(), self._composition_zoom,
            visible=self._composition_v7_visible,
        )

    def _composition_v6_is_locked(self, layer):
        return is_layer_locked(self._composition_v6_locked, layer)

    def _composition_v6_lock_changed(self, check, layer):
        self._composition_v6_locked[layer] = bool(check.get_active())
        if self._composition_v6_locked[layer] and self._composition_before_drag is not None:
            # Proteção adicional: interrompe operações em andamento.
            self._composition_drag_end()
        self._composition_update_buttons()
        self.composition_canvas.queue_draw()

    def _composition_v6_outline_changed(self, check, layer):
        self._composition_v6_outlines[layer] = bool(check.get_active())
        self.composition_canvas.queue_draw()

    def _composition_v6_reset_local(self):
        # Chamada quando outra tecla começa a ser carregada. Bloqueios não
        # devem sobreviver à troca de tecla/perfil.
        self._composition_v6_locked = {'image': False, 'text': False}
        self._composition_v6_outlines = {'image': True, 'text': True}
        for layer in ('image', 'text'):
            self.composition_v6_lock_checks[layer].set_active(False)
            self.composition_v6_outline_checks[layer].set_active(True)
        self._composition_update_buttons()

    def _composition_v6_center(self, axis):
        if self._quick_loaded is None or 'quick_save' in self._busy:
            return False
        layer = 'image' if self.composition_target.get_selected() == 0 else 'text'
        if layer not in self._composition_available_layers() or self._composition_v6_is_locked(layer):
            return False
        field = ('image_' if layer == 'image' else 'offset_') + axis
        bounds = ({**INT_RANGES, **IMAGE_RANGES})[field]
        before = state_from_fields(self.style_numbers)
        after = center_layer_axis(
            before, layer, axis, bounds,
            text=self.quick_visual_text.get_text() or self.quick_label.get_text(),
            font_size=int(self.style_numbers['font_size'].get_value()),
            horizontal=CHOICES['horizontal'][self.style_choices['horizontal'].get_selected()],
            vertical=CHOICES['vertical'][self.style_choices['vertical'].get_selected()],
        )
        if not self._composition_history.record(before, after):
            self.composition_status.set_text('Camada já centralizada neste eixo (aproximação).')
            return False
        self._composition_restore_state(after, coordinate_caption(after, layer) +
                                        ' — centralização aproximada.')
        return True

    def _composition_selection_priority_changed(self, *_):
        # Apenas hit-test local; não modifica o perfil nem o estado dirty.
        self.composition_canvas.queue_draw()

    def _composition_alignment_changed(self, *_):
        # Opção de encaixe é local: não entra no YAML nem no histórico.
        self._composition_guide = (None, None)
        self.composition_canvas.queue_draw()

    def _composition_update_coordinates(self):
        if not hasattr(self, 'composition_coordinates'):
            return
        target = 'image' if self.composition_target.get_selected() == 0 else 'text'
        self.composition_coordinates.set_text(
            coordinate_caption(state_from_fields(self.style_numbers), target)
        )

    def _composition_nudge(self, direction, step=None):
        if self._quick_loaded is None or 'quick_save' in self._busy:
            return False
        target = 'image' if self.composition_target.get_selected() == 0 else 'text'
        if getattr(self, '_composition_v6_is_locked', lambda _layer: False)(target):
            return False
        if step is None:
            step = (1, 5)[self.composition_nudge_step.get_selected()]
        field = 'image_x' if target == 'image' else 'offset_x'
        bounds = ({**INT_RANGES, **IMAGE_RANGES})[field]
        before = state_from_fields(self.style_numbers)
        after = nudge_state(before, target, direction, step, bounds)
        if before == after:
            self.composition_status.set_text('Limite de posição atingido; nada foi alterado.')
            return False
        if self._composition_history.record(before, after):
            self._composition_restore_state(after, coordinate_caption(after, target))
            if self.composition_align.get_active():
                self._composition_guide = guides_at_position(after, target)
            self.composition_canvas.queue_draw()
            return True
        return False

    def _composition_pick_target(self, x, y):
        # Hit-test local sobre o preview composto, sem ler/gravar o YAML.
        if self._quick_loaded is None or 'quick_save' in self._busy:
            return None
        area = self.composition_canvas
        if getattr(self, '_composition_v8_masks', None):
            candidates = self._composition_v8_candidates(x, y)
            prefer = ('image' if getattr(self, 'composition_prefer_image', None) is not None
                      and self.composition_prefer_image.get_active() else 'text')
            selected = choose_mask_layer(candidates, prefer)
            if selected is not None:
                self.composition_target.set_selected(0 if selected == 'image' else 1)
            return selected
        selected = hit_visual_element(
            x, y, area.get_width(), area.get_height(), self._composition_zoom,
            image_present=bool(self.quick_image.get_text().strip()),
            image_x=int(self.style_numbers['image_x'].get_value()),
            image_y=int(self.style_numbers['image_y'].get_value()),
            image_scale=int(self.style_numbers['image_scale'].get_value()),
            text=self.quick_visual_text.get_text() or self.quick_label.get_text(),
            show_text=self.style_show_text.get_active(),
            offset_x=int(self.style_numbers['offset_x'].get_value()),
            offset_y=int(self.style_numbers['offset_y'].get_value()),
            font_size=int(self.style_numbers['font_size'].get_value()),
            horizontal=CHOICES['horizontal'][self.style_choices['horizontal'].get_selected()],
            vertical=CHOICES['vertical'][self.style_choices['vertical'].get_selected()],
            prefer=('image' if getattr(self, 'composition_prefer_image', None) is not None
                    and self.composition_prefer_image.get_active() else 'text'),
        )
        if selected is not None:
            self.composition_target.set_selected(0 if selected == 'image' else 1)
        return selected

    def _composition_click_pressed(self, *_):
        self._composition_drag_did_move = False

    def _composition_click_released(self, _gesture, n_press, x, y):
        # Movimentação (inclusive pela alça) nunca muda automaticamente de aba.
        if self._composition_drag_did_move:
            self._composition_drag_did_move = False
            return
        if n_press != 1:
            return
        selected = self._composition_pick_target(x, y)
        if hasattr(self, '_composition_capture_overlap'):
            self._composition_capture_overlap(x, y)
        if selected is not None:
            self.quick_tabs.set_current_page(1 if selected == 'image' else 2)
            self.composition_status.set_text(
                ('Imagem' if selected == 'image' else 'Texto') +
                ': propriedades selecionadas; volte a Composição para arrastar.'
            )

    def _composition_resize_drag_begin(self, gesture, _x, _y):
        # O gesto origina-se na própria alça, não nas coordenadas da imagem:
        # é redimensionamento SEMPRE, independentemente de zoom, recorte ou
        # posição atual. Evita o hit-test no limite da superfície.
        if getattr(self, '_composition_v6_is_locked', lambda _layer: False)('image'):
            self._composition_before_drag = None
            return
        self._composition_drag_begin()
        if self._composition_before_drag is None:
            return
        self._composition_drag_kind = 'resize'
        self._composition_drag_did_move = True
        self.composition_status.set_text('Redimensionando imagem pela alça ↘…')
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def _composition_drag_begin(self, _gesture=None, x=0, y=0):
        self._composition_before_drag = None
        if self._quick_loaded is None or 'quick_save' in self._busy:
            self.composition_status.set_text('Selecione uma tecla e aguarde suas propriedades.')
            return
        self._composition_drag_did_move = False
        # O arrasto iniciado pelo GTK exige hit-test. Chamadas sem gesto são
        # usadas pela alça separada e pelos testes legados da composição.
        if _gesture is not None and self._composition_pick_target(x, y) is None:
            self.composition_status.set_text('Clique sobre a imagem ou o texto para selecionar.')
            return
        layer = 'image' if self.composition_target.get_selected() == 0 else 'text'
        if getattr(self, '_composition_v6_is_locked', lambda _layer: False)(layer):
            self.composition_status.set_text('Camada bloqueada: desbloqueie para arrastar.')
            return
        if not self.style_enabled.get_active():
            self.style_enabled.set_active(True)
        self._composition_before_drag = state_from_fields(self.style_numbers)
        target = ('image_x', 'image_y') if self.composition_target.get_selected() == 0 else ('offset_x', 'offset_y')
        self._composition_drag_start = tuple(int(self.style_numbers[field].get_value()) for field in target)
        self._composition_drag_kind = 'move'
        self._composition_guide = (None, None)
        if target[0] == 'image_x':
            area = self.composition_canvas
            w, h = area.get_width(), area.get_height()
            if w > 0 and h > 0 and hit_image_handle(x, y, w, h,
                 int(self.style_numbers['image_x'].get_value()),
                 int(self.style_numbers['image_y'].get_value()),
                 int(self.style_numbers['image_scale'].get_value()), self._composition_zoom):
                self._composition_drag_kind = 'resize'
        self.composition_status.set_text('Redimensionando imagem…' if self._composition_drag_kind == 'resize'
            else 'Arrastando ' + ('imagem' if target[0] == 'image_x' else 'texto') + '…')

    def _composition_drag_update(self, _gesture, offset_x, offset_y):
        if (self._quick_loaded is None or 'quick_save' in self._busy
                or not self.style_enabled.get_active() or self._composition_before_drag is None):
            return
        if offset_x or offset_y:
            self._composition_drag_did_move = True
        target = ('image_x', 'image_y') if self.composition_target.get_selected() == 0 else ('offset_x', 'offset_y')
        layer = 'image' if target[0] == 'image_x' else 'text'
        if getattr(self, '_composition_v6_is_locked', lambda _layer: False)(layer):
            return
        extent = min(self.composition_canvas.get_width(), self.composition_canvas.get_height())
        if extent <= 0:
            self.composition_status.set_text('Área de composição indisponível; amplie a janela.')
            return
        unit = extent / 100 * self._composition_zoom
        if self._composition_drag_kind == 'resize':
            previous = self._composition_before_drag[2]
            scale = resize_image_scale(previous, offset_x, offset_y, unit)
            self.style_numbers['image_scale'].set_value(scale)
            self.composition_status.set_text(f'Imagem: tamanho {scale}% — prévia sendo atualizada.')
            self.composition_canvas.queue_draw()
            return
        snap = bool(self.composition_grid.get_active())
        result = []
        guides = []
        anchor_target = 'image' if target[0] == 'image_x' else 'text'
        anchors = anchors_for_target(anchor_target, int(self.style_numbers['image_scale'].get_value()))
        for index, (field, diff) in enumerate(zip(target, (offset_x, offset_y))):
            lower, upper = ({**INT_RANGES, **IMAGE_RANGES})[field]
            value = clamp_drag(self._composition_drag_start[index], diff, unit, lower, upper)
            if snap:
                value = grid_coordinate(value, lower, upper)
            elif (not hasattr(self, 'composition_align')
                  or self.composition_align.get_active()):
                value, guide = smart_snap(value, lower, upper, anchors)
            guide = (value if value in anchors and
                     (not hasattr(self, 'composition_align')
                      or self.composition_align.get_active()) else None)
            self.style_numbers[field].set_value(value)
            result.append(value)
            guides.append(guide)
        self._composition_guide = tuple(guides)
        self.composition_canvas.queue_draw()
        self.composition_status.set_text(
            ('Imagem' if target[0] == 'image_x' else 'Texto') +
            f': X={result[0]} px, Y={result[1]} px — prévia sendo atualizada.'
        )

    def _composition_drag_end(self, *_):
        if self._composition_before_drag is not None:
            self._composition_history.record(self._composition_before_drag,
                                             state_from_fields(self.style_numbers))
        self._composition_before_drag = None
        self._composition_guide = (None, None)
        self.composition_canvas.queue_draw()
        self._composition_update_buttons()

    def _composition_update_buttons(self):
        ready = self._quick_loaded is not None and 'quick_save' not in self._busy
        self.composition_undo.set_sensitive(ready and bool(self._composition_history.undo_stack))
        self.composition_redo.set_sensitive(ready and bool(self._composition_history.redo_stack))
        layer = 'image' if self.composition_target.get_selected() == 0 else 'text'
        locked = getattr(self, '_composition_v6_is_locked', lambda _layer: False)(layer)
        self.composition_reset.set_sensitive(ready and not locked)
        if hasattr(self, '_composition_update_layer_panel'):
            self._composition_update_layer_panel()
        if hasattr(self, 'composition_nudge_buttons'):
            for button in self.composition_nudge_buttons:
                button.set_sensitive(ready and not locked)
            self.composition_nudge_step.set_sensitive(ready and not locked)
        # O bloqueio v6 também protege os cinco campos numéricos de
        # geometria, sem desabilitar cores, textos ou ações da tecla.
        if hasattr(self, '_composition_v6_locked') and hasattr(self, 'style_numbers'):
            for layer, fields in (
                ('image', ('image_x', 'image_y', 'image_scale')),
                ('text', ('offset_x', 'offset_y')),
            ):
                for field in fields:
                    spin = self.style_numbers[field]
                    if hasattr(spin, 'set_sensitive'):
                        spin.set_sensitive(not self._composition_v6_is_locked(layer))
        # Alça só aparece para uma tecla carregada no modo Imagem.
        self.composition_resize_handle.set_visible(
            ready and self.composition_target.get_selected() == 0 and not locked
        )

    def _composition_restore_state(self, state, message):
        if self._quick_loaded is None or 'quick_save' in self._busy:
            return
        if not self.style_enabled.get_active():
            self.style_enabled.set_active(True)
        apply_state(self.style_numbers, state)
        self._composition_guide = (None, None)
        self.composition_canvas.queue_draw()
        self.composition_status.set_text(message)
        self._composition_update_buttons()

    def _composition_undo_action(self, *_):
        if self._quick_loaded is None or 'quick_save' in self._busy:
            return
        state = self._composition_history.undo(state_from_fields(self.style_numbers))
        if state is not None:
            self._composition_restore_state(state, 'Composição: alteração desfeita.')

    def _composition_redo_action(self, *_):
        if self._quick_loaded is None or 'quick_save' in self._busy:
            return
        state = self._composition_history.redo(state_from_fields(self.style_numbers))
        if state is not None:
            self._composition_restore_state(state, 'Composição: alteração refeita.')

    def _composition_reset_action(self, *_):
        if self._quick_loaded is None or 'quick_save' in self._busy:
            return
        before = state_from_fields(self.style_numbers)
        target = 'image' if self.composition_target.get_selected() == 0 else 'text'
        if getattr(self, '_composition_v6_is_locked', lambda _layer: False)(target):
            return
        after = default_target(before, target)
        if self._composition_history.record(before, after):
            self._composition_restore_state(after, 'Posição padrão restaurada (' + target + ').')

    def _composition_key_pressed(self, _controller, keyval, _keycode, state):
        if (self.stack.get_visible_child_name() != 'keys' or self._quick_loaded is None
                or not state & Gdk.ModifierType.CONTROL_MASK):
            return False
        # Não interceptar Ctrl+Z dos campos editáveis (rótulo, YAML, URL etc.).
        focus = self.get_focus()
        if isinstance(focus, (Gtk.Entry, Gtk.TextView, Gtk.SpinButton)):
            return False
        # Escopo: aba Composição. Não roubar Ctrl+Setas de outras abas.
        directions = {Gdk.KEY_Left: 'left', Gdk.KEY_Right: 'right',
                      Gdk.KEY_Up: 'up', Gdk.KEY_Down: 'down'}
        if keyval in directions:
            if self.quick_tabs.get_current_page() != 3:
                return False
            step = 5 if state & Gdk.ModifierType.SHIFT_MASK else 1
            return self._composition_nudge(directions[keyval], step=step)
        if keyval not in (Gdk.KEY_z, Gdk.KEY_Z):
            return False
        if state & Gdk.ModifierType.SHIFT_MASK:
            self._composition_redo_action()
        else:
            self._composition_undo_action()
        return True

    def _composition_zoom_changed(self, *_):
        self._composition_zoom = ZOOMS[self.composition_zoom.get_selected()]
        self._composition_last_overlap = None
        self._composition_update_zoom()
        self.composition_canvas.queue_draw()

    def _composition_update_zoom(self):
        # Zoom é local ao GTK. Não modifica imagem persistida nem renderizador.
        source = self._composition_pixbuf
        if source is None:
            return
        if self._composition_zoom == 1.0:
            if self._composition_preview_path:
                self.composition_picture.set_file(Gio.File.new_for_path(self._composition_preview_path))
            return
        width, height = source.get_width(), source.get_height()
        zoom = self._composition_zoom
        scaled = source.scale_simple(round(width*zoom), round(height*zoom), GdkPixbuf.InterpType.BILINEAR)
        x = (scaled.get_width() - width)//2
        y = (scaled.get_height() - height)//2
        crop = GdkPixbuf.Pixbuf.new_subpixbuf(scaled, x, y, width, height)
        self.composition_picture.set_paintable(Gdk.Texture.new_for_pixbuf(crop))

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

    def _build_visual_style(self, parent, composition_parent=None):
        expander = Gtk.Expander(label='Tipografia, cores e alinhamento')
        expander.set_expanded(True)
        parent.append(expander)
        controls = _box(False, 8)
        controls.set_margin_top(8)
        controls.set_margin_bottom(10)
        expander.set_child(controls)
        # O controle geral style_enabled fica fixo acima das abas.
        self.style_options = _box(False, 7)
        controls.append(self.style_options)
        self.style_image_options = _box(False, 7)
        (composition_parent if composition_parent is not None else controls).append(self.style_image_options)
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
            dest = self.style_image_options if name == 'image_fit' else self.style_options
            dest.append(_label(title))
            widget = Gtk.DropDown.new_from_strings(list(captions))
            dest.append(widget)
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
            dest = self.style_image_options if name in IMAGE_RANGES else self.style_options
            dest.append(_label(names[name]))
            spin = Gtk.SpinButton.new_with_range(minimum, maximum, 1)
            spin.set_numeric(True)
            spin.connect('value-changed', self._visual_style_changed)
            dest.append(spin)
            self.style_numbers[name] = spin
        self.style_show_text = Gtk.CheckButton(label='Exibir texto sobre imagem/fundo')
        self.style_show_text.connect('toggled', self._visual_style_changed)
        self.style_options.append(self.style_show_text)
        self.style_enabled.connect('toggled', self._visual_style_changed)
        controls.append(_label('Texto: deslocamento X/Y de −40 a +40 px. '
                               'Os controles de imagem ficam na aba Composição.',
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
                  and 'quick_save' not in self._busy
                  and 'quick_batch_appearance' not in self._busy)
        self.style_options.set_sensitive(active)
        self.style_image_options.set_sensitive(active)
        self.style_enabled.set_sensitive(self._quick_loaded is not None and 'quick_save' not in self._busy
                                         and 'quick_batch_appearance' not in self._busy)

    def _visual_style_changed(self, *_):
        self._update_style_sensitivity()
        if hasattr(self, 'composition_coordinates'):
            self._composition_update_coordinates()
        # Redesenha a moldura junto com as alterações dos campos da aparência.
        if hasattr(self, 'composition_canvas'):
            self.composition_canvas.queue_draw()
        if hasattr(self, '_composition_update_layer_panel'):
            self._composition_update_layer_panel()
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
            widget.set_sensitive(loaded and 'quick_save' not in self._busy
                                 and 'quick_batch_appearance' not in self._busy)
        busy = 'quick_save' in self._busy or 'quick_preview' in self._busy or 'quick_batch_appearance' in self._busy
        self.quick_preview_btn.set_sensitive(loaded and not busy)
        self.quick_save_btn.set_sensitive(loaded and not busy)
        self.quick_apply_btn.set_sensitive(loaded and self._quick_saved and not self._quick_dirty and not busy)
        self._update_style_sensitivity()
        self._composition_update_buttons()
        self.quick_icon_flow.set_sensitive(loaded and 'quick_save' not in self._busy)
        self.quick_import_icon_btn.set_sensitive('import_icon' not in self._busy and 'quick_save' not in self._busy)
        if hasattr(self, 'quick_batch_apply_btn'):
            self._quick_batch_controls()
        if hasattr(self, 'preset_apply_btn'):
            self._preset_controls()

    def _quick_kind_changed(self, *_):
        kind = KINDS[self.quick_kind.get_selected()]
        self.quick_hint.set_text(HINTS[kind])
        count = {'none': 0, 'command': 1, 'url': 1, 'hotkey': 1,
                 'profile': 1, 'script': 3, 'obs': 4}[kind]
        for i, field in enumerate(self.quick_fields):
            field.set_visible(i < count)
        self._quick_changed()

    def _quick_changed(self, *_):
        if hasattr(self, '_composition_update_layer_panel'):
            self._composition_update_layer_panel()
        if self._quick_updating or self._quick_loaded is None:
            return
        # Evita acertar pixels do preview anterior enquanto novos campos
        # estão aguardando prévia. A seleção geométrica permanece disponível.
        self._composition_v8_masks = {}
        if hasattr(self, 'composition_v8_status'):
            self.composition_v8_status.set_text('Seleção aproximada: atualize a prévia para máscaras RGBA.')
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
        if hasattr(self, '_composition_v6_reset_local'):
            self._composition_v6_reset_local()
        self._composition_v7_paths = {}
        self._composition_v8_masks = {}
        self.composition_v8_status.set_text('Seleção: aguardando máscaras RGBA da prévia local.')
        for layer in ('image', 'text'):
            self._composition_v7_visible[layer] = True
            check = self.composition_v7_visibility_checks[layer]
            check.set_active(True)
            check.set_sensitive(False)
        self._quick_loaded = None
        self._quick_saved = False
        self._composition_history.clear()
        self._composition_before_drag = None
        self._composition_guide = (None, None)
        self._composition_preview_path = None
        self._composition_last_overlap = None
        self._composition_update_buttons()
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

    def _open_quick_icon_gallery(self, *_):
        """Galeria independente com rolagem: selecionar mantém o fluxo local.

        Não grava perfil, não toca no IPC e não duplica o catálogo no disco.
        A janela pertence ao Studio; só compartilha o campo de imagem atual.
        """
        existing = getattr(self, '_quick_icon_gallery_window', None)
        if existing is not None:
            existing.present()
            return
        window = Gtk.Window(title='Vision 02 — Galeria de ícones', transient_for=self)
        window.set_default_size(820, 680)
        window.set_resizable(True)
        window.set_destroy_with_parent(True)
        self._quick_icon_gallery_window = window

        def on_close(*_args):
            self._quick_icon_gallery_window = None
            return False

        window.connect('close-request', on_close)
        frame = _box(False, 10)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(frame, 'set_margin_' + side)(14)
        window.set_child(frame)
        frame.append(_label('Galeria de ícones · seleção local', style='title-3'))
        search = Gtk.SearchEntry()
        search.set_placeholder_text('Filtrar ícones pelo nome')
        frame.append(search)
        count = _label('Carregando…', style='caption')
        frame.append(count)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        frame.append(scroll)
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_max_children_per_line(6)
        flow.set_row_spacing(8)
        flow.set_column_spacing(8)
        flow.set_halign(Gtk.Align.FILL)
        scroll.set_child(flow)
        frame.append(_label('Selecionar um ícone altera somente a prévia local. '
                            'Para gravar, use Salvar YAML com backup no Studio.',
                            style='caption', wrap=True))

        def render(*_args):
            while (child := flow.get_first_child()) is not None:
                flow.remove(child)
            matches = filtered_icons(self._icons, search.get_text())
            count.set_text(f'{len(matches)} miniaturas / {len(self._icons)} ícones no catálogo')
            selected = self.quick_image.get_text()
            for icon in matches:
                path = icon['path']
                if not Path(path).is_file():
                    continue
                button = Gtk.Button()
                button.add_css_class('flat')
                button.set_tooltip_text(icon['name'])
                button.set_sensitive(self._quick_loaded is not None and 'quick_save' not in self._busy)
                contents = _box(False, 4)
                contents.set_halign(Gtk.Align.CENTER)
                picture = Gtk.Picture.new_for_file(Gio.File.new_for_path(path))
                picture.set_size_request(90, 90)
                picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                contents.append(picture)
                title = _label(icon['name'])
                title.set_max_width_chars(14)
                title.set_ellipsize(Pango.EllipsizeMode.END)
                title.set_halign(Gtk.Align.CENTER)
                contents.append(title)
                button.set_child(contents)
                if path == selected:
                    button.add_css_class('vision02-icon-selected')

                def choose(_button, chosen=path):
                    self._quick_pick_icon(_button, chosen)
                    window.close()

                button.connect('clicked', choose)
                flow.insert(button, -1)

        search.connect('search-changed', render)
        search.set_text(self.quick_icon_search.get_text())
        render()
        window.present()

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
            self._quick_batch_configured = set(response.get('configured_keys', []))
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
            self._quick_saved = self._quick_batch_pending_apply
            self._quick_batch_pending_apply = False
            self._composition_history.clear()
            self._composition_update_buttons()
            self.quick_state.set_text(
                'Aparências em lote salvas com backup. Clique em Aplicar ao dispositivo (IPC) '
                'para atualizar os LCDs.' if self._quick_saved else
                'Pronta para editar. Alterações só são salvas ao clicar em Salvar YAML.')
            # Prévia local automática ao selecionar a tecla, não exige
            # clicar em um botão oculto na parte inferior do painel.
            self._quick_preview()
            self._quick_batch_controls()
            self._preset_controls()
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
                    self._composition_preview_path = response['image']
                    self._composition_update_zoom()
                    self._composition_v7_set_paths(response.get('layers', {}))
                    self._composition_v8_set_components(response.get('components', {}))
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
        elif command == 'quick_batch_appearance':
            self.quick_batch_status.set_text(
                f"{len(response['targets'])} tecla(s) atualizada(s). Backup: {response['backup']}")
            self._quick_batch_clipboard = None
            self.quick_batch_confirm.set_active(False)
            self.quick_batch_source.set_text('Copie uma origem para nova operação.')
            self._quick_saved = False  # aguardar inspeção da nova revisão
            self._quick_batch_pending_apply = True
            self._quick_dirty = False
            self._quick_loaded = None
            self._quick_load()
            self._call('previews')
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
        _button(page, 'Menu de Perfis · Tecla 15',
                lambda *_: self.stack.set_visible_child_name('profile_menu'))
        page.append(_label('O recarregamento valida os YAML antes de atualizar os LCDs.',
                           style='caption', wrap=True))

    def _build_profile_menu(self):
        """Administração do menu físico com confirmação, backup e IPC explícitos."""
        page = self._page(
            'profile_menu', 'Menu de Perfis',
            'Configure a tecla 15 de cada perfil para retornar ao menu físico. '
            'A instalação altera apenas o YAML pessoal e gera ícones locais; '
            'nenhuma ação física é executada automaticamente.',
        )
        page.append(_label('Menu de Perfis · Navegação pelas 15 teclas', style='title-3'))
        page.append(_label(
            'O menu existente continuará funcionando. Para incluir novos perfis, inspecione '
            'as alterações e sincronize. As teclas 1 a 14 permanecem intactas.', wrap=True,
        ))
        options = _box(True, 8)
        page.append(options)
        self.menu_inspect_button = _button(options, 'Inspecionar catálogo',
                                           lambda *_: self._menu_run('--plan'))
        self.menu_reload_button = _button(options, 'Recarregar catálogo (IPC)',
                                          self._menu_reload)
        self.menu_open_button = _button(options, 'Abrir menu nos LCDs (IPC)',
                                        self._menu_open)

        self.menu_status = _label('Clique em Inspecionar catálogo para começar.', wrap=True)
        page.append(self.menu_status)
        self.menu_summary = _label('', wrap=True)
        page.append(self.menu_summary)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        list_scroll.set_min_content_height(260)
        list_scroll.set_size_request(-1, 310)
        page.append(list_scroll)
        self.menu_profile_rows = _box(False, 8)
        list_scroll.set_child(self.menu_profile_rows)

        self.menu_confirm = Gtk.CheckButton(label=(
            'Confirmo que a função atual da tecla 15 dos perfis será substituída '
            'por Voltar ao Menu (backup automático).'))
        self.menu_confirm.set_active(False)
        self.menu_confirm.connect('toggled', lambda *_: self._menu_update_controls())
        page.append(self.menu_confirm)
        actions = _box(True, 8)
        page.append(actions)
        self.menu_sync_button = _button(actions, 'Sincronizar menu e tecla 15',
                                        lambda *_: self._menu_run('--apply'))
        self.menu_restore_button = _button(actions, 'Restaurar último backup…',
                                           self._menu_restore_request)
        page.append(_label(
            'Depois de sincronizar, clique em Recarregar catálogo (IPC). '
            'A abertura do menu é uma ação separada. Nenhum serviço é reiniciado.',
            style='caption', wrap=True,
        ))
        self._menu_update_controls()

    def _menu_update_controls(self):
        busy = self._menu_busy
        editable = not self._quick_dirty
        self.menu_inspect_button.set_sensitive(not busy)
        self.menu_sync_button.set_sensitive(
            not busy and editable and self._menu_plan is not None
            and self.menu_confirm.get_active()
        )
        self.menu_confirm.set_sensitive(not busy and editable and self._menu_plan is not None)
        self.menu_restore_button.set_sensitive(not busy and editable)
        self.menu_reload_button.set_sensitive(not busy and self._connected)
        self.menu_open_button.set_sensitive(not busy and self._connected and editable)

    def _menu_render_plan(self, response):
        box = self.menu_profile_rows
        child = box.get_first_child()
        while child is not None:
            sibling = child.get_next_sibling()
            box.remove(child)
            child = sibling
        root = Path(os.environ.get('XDG_CONFIG_HOME') or (Path.home() / '.config'))
        icons = root / 'vision02/profile-icons/menu-de-perfis'
        for index, item in enumerate(response.get('profiles', []), start=1):
            row = _box(True, 12)
            image = icons / f'perfil-{index:02d}.png'
            if image.is_file() and not image.is_symlink():
                picture = Gtk.Picture.new_for_file(Gio.File.new_for_path(str(image)))
                picture.set_size_request(48, 48)
                picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                row.append(picture)
            row.append(_label(
                f"{index:02d}  ·  {item['name']}   |   tecla 15: "
                f"{item['key15_before']}  →  Menu de Perfis", wrap=True,
            ))
            box.append(row)
        count = response.get('count', 0)
        pages = len(response.get('pages') or [])
        changes = response.get('files_to_write', 0)
        self.menu_summary.set_text(
            f'{count} perfis identificados · {pages} página(s) · '
            f'{changes} arquivo(s) pendente(s) de sincronização.'
        )

    def _menu_run(self, operation, backup=None):
        if self._menu_busy:
            return
        if operation in ('--apply', '--restore') and self._quick_dirty:
            self.menu_status.set_text('Salve ou descarte a edição da tecla antes de modificar os perfis.')
            return
        revision = None
        if operation == '--apply':
            if not self._menu_plan or not self.menu_confirm.get_active():
                self.menu_status.set_text('Inspecione os perfis e confirme a substituição da tecla 15.')
                return
            revision = self._menu_plan['revision']
        self._menu_busy = True
        self._menu_update_controls()
        self.menu_status.set_text('Verificando perfis; aguarde…')

        def worker():
            command = [str(PYTHON), '-m', 'vision02.studio_profile_menu_v15',
                       '--project', str(ROOT)]
            if revision is not None:
                command.extend(['--expected-revision', revision])
            command.append(operation)
            if backup is not None:
                command.append(str(backup))
            environment = os.environ.copy()
            environment['PYTHONPATH'] = str(ROOT / 'src') + os.pathsep + environment.get('PYTHONPATH', '')
            try:
                result = subprocess.run(command, cwd=str(ROOT), env=environment,
                                        capture_output=True, text=True, timeout=120, check=False)
                response = json.loads(result.stdout)
                if not isinstance(response, dict):
                    raise ValueError('Resposta inválida do gerenciador de perfis')
                if result.returncode or not response.get('ok'):
                    raise ValueError(response.get('error') or result.stderr.strip() or 'Falha na operação')
            except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
                GLib.idle_add(self._menu_finished, operation, False, str(exc))
            else:
                GLib.idle_add(self._menu_finished, operation, True, response)

        threading.Thread(target=worker, daemon=True, name='vision02-menu-perfis').start()

    def _menu_finished(self, operation, ok, result):
        self._menu_busy = False
        if self._closed:
            return False
        if not ok:
            self._menu_plan = None
            self.menu_confirm.set_active(False)
            self.menu_status.set_text('Falha: ' + str(result))
        elif operation == '--plan':
            self._menu_plan = result
            self.menu_confirm.set_active(False)
            self._menu_render_plan(result)
            self.menu_status.set_text('Inspeção concluída. Revise a lista e confirme antes de sincronizar.')
        else:
            self._menu_plan = None
            self.menu_confirm.set_active(False)
            message = result.get('message', 'Operação concluída.')
            if operation == '--apply':
                message += ' Clique em Recarregar catálogo (IPC) para atualizar o dispositivo.'
            self.menu_status.set_text(message)
        self._menu_update_controls()
        return False

    def _menu_reload(self, *_):
        if not self._menu_busy:
            self._call('reload')
            self.menu_status.set_text('Recarregamento IPC solicitado. Aguarde a atualização do catálogo.')

    def _menu_open(self, *_):
        if self._quick_dirty:
            self.menu_status.set_text('Salve ou descarte a edição da tecla antes de trocar de perfil.')
            return
        if not self._menu_busy and self._connected:
            self._call('switch', target='Menu de Perfis')
            self.menu_status.set_text('Abertura do Menu de Perfis solicitada por IPC.')

    def _menu_restore_request(self, *_):
        if self._menu_busy or self._quick_dirty:
            return
        state = Path(os.environ.get('XDG_STATE_HOME') or (Path.home() / '.local/state'))
        backup_root = state / 'vision02/menu-perfis-backups'
        backups = sorted(backup_root.glob('*/manifest.json'), reverse=True) if backup_root.is_dir() else []
        if not backups:
            self.menu_status.set_text('Nenhum backup anterior do Menu de Perfis foi encontrado.')
            return
        backup = backups[0].parent
        dialog = Gtk.AlertDialog()
        dialog.set_message('Restaurar a configuração anterior da tecla 15?')
        dialog.set_detail(
            f'Backup: {backup}\nA operação será recusada se algum arquivo foi alterado '
            'depois da instalação. Recarregue o catálogo após restaurar.'
        )
        dialog.set_buttons(['Cancelar', 'Restaurar'])

        def answered(alert, result):
            try:
                choice = alert.choose_finish(result)
            except GLib.Error:
                return
            if choice == 1:
                self._menu_run('--restore', backup)

        dialog.choose(self, None, answered)

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
                          'Brilho global dos 15 LCDs e caminhos da instalação.')
        page.append(_label('Brilho das teclas LCD (global)', style='title-3'))
        self.brightness_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.brightness_scale.set_value(25)
        self.brightness_scale.set_digits(0)
        self.brightness_scale.set_hexpand(True)
        self.brightness_scale.connect('value-changed', self._brightness_changed)
        page.append(self.brightness_scale)
        self.brightness_status = _label('Brilho atual: aguardando serviço…', style='caption', wrap=True)
        page.append(self.brightness_status)
        _button(page, 'Aplicar brilho', self._brightness_apply)
        page.append(_label('Ajuste global dos 15 LCDs (0–100%). A preferência será restaurada ao iniciar o Ubuntu.', style='caption', wrap=True))
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

    def _brightness_changed(self, _scale):
        if not self._brightness_syncing:
            self._brightness_dirty = True
            self.brightness_status.set_text(
                f'Brilho selecionado: {round(self.brightness_scale.get_value())}% — clique em Aplicar brilho.'
            )

    def _brightness_apply(self, *_args):
        if not self._connected:
            self.brightness_status.set_text('Controlador indisponível; verifique vision02.service.')
            return
        percent = int(round(self.brightness_scale.get_value()))
        self._call('brightness', value=percent)

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
            elif command.startswith('preset_'):
                if command.startswith('preset_editor_') and hasattr(self, 'preset_editor_status'):
                    self.preset_editor_status.set_text(f'Falha: {message}')
                    if command == 'preset_editor_preview' and self._preset_editor_preview_pending:
                        self._preset_editor_preview_pending = False
                        self._preset_editor_schedule()
                self.preset_status.set_text(f'Falha: {message}')
                self._preset_controls()
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
            elif command == 'brightness':
                self.brightness_status.set_text(f'Falha ao ajustar brilho: {message}')
            elif command == 'obs':
                self.obs_state.set_text(f'OBS indisponível: {message}')
            elif command == 'system':
                self.system_state.set_text(f'Métricas indisponíveis: {message}')
            else:
                self.top_status.set_text(f'{command}: {message}')
            return False
        if command.startswith('preset_'):
            self._preset_received(command, response)
            return False
        if command in {'quick_inspect', 'quick_preview', 'quick_save', 'quick_batch_appearance'}:
            self._quick_received(command, response)
            return False
        if command == 'brightness':
            self._brightness_dirty = False
            self.brightness_status.set_text(f'Brilho aplicado: {response.get("brightness", "?")}%')
            self._call('status')
            return False
        if command in {'status', 'switch', 'reload'}:
            if command == 'reload':
                self._call('previews')
                self._call('live_preview')
            self._call('status') if command in {'switch', 'reload'} else None
            if command != 'status':
                return False
            self._connected = bool(response.get('connected'))
            actual_brightness = response.get('brightness')
            if type(actual_brightness) is int and 0 <= actual_brightness <= 100:
                if not self._brightness_dirty:
                    self._brightness_syncing = True
                    try:
                        self.brightness_scale.set_value(actual_brightness)
                    finally:
                        self._brightness_syncing = False
                    self.brightness_status.set_text(f'Brilho atual: {actual_brightness}%')
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
            if self.stack.get_visible_child_name() == 'profile_menu':
                self._menu_update_controls()
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
        if 'quick_batch_appearance' in self._busy or 'preset_apply' in self._busy:
            self._update_combo()
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
        if 'quick_batch_appearance' in self._busy or 'preset_apply' in self._busy:
            self.quick_state.set_text('Aguarde a gravação em lote.')
            return
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
                # Nomes longos aumentam a largura natural do Gtk.Button.
                # A borda selecionada e o painel de detalhes ja comunicam
                # a selecao; manter apenas o numero evita sobrepor vizinhos.
                number_label.set_text(f'{ident:02d}')
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
            cell = _box(False, 1)
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
                live_picture.set_size_request(DECK_ICON_SIZE, DECK_ICON_SIZE)
                live_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                cell.append(live_picture)
            elif isinstance(png, str) and Path(png).is_file():
                picture = Gtk.Picture.new_for_file(Gio.File.new_for_path(png))
                picture.set_size_request(DECK_ICON_SIZE, DECK_ICON_SIZE)
                picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                cell.append(picture)
            else:
                blank = _label('—')
                blank.set_size_request(DECK_ICON_SIZE, DECK_ICON_SIZE)
                cell.append(blank)
            title = _label(f'{key_id:02d}', style='vision02-key-number')
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
        elif key == 'profile_menu':
            self._menu_run('--plan')
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

    def _panel_position_changed(self, paned, *_):
        if self._closed or paned.get_position() < 1:
            return
        if self._panel_save_timer:
            GLib.source_remove(self._panel_save_timer)
        self._panel_save_timer = GLib.timeout_add(550, self._persist_panel_width)

    def _persist_panel_width(self):
        self._panel_save_timer = 0
        try:
            save_panel_width(self.editor_split.get_position())
        except (OSError, ValueError) as exc:
            self.top_status.set_text('Não foi possível salvar a largura do editor: ' + str(exc))
        return False

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
        if self._panel_save_timer:
            GLib.source_remove(self._panel_save_timer)
            self._persist_panel_width()
        try:
            save_window_size(self.get_width(), self.get_height())
        except (OSError, ValueError) as exc:
            print(f'Vision 02 Studio: não foi possível guardar a janela: {exc}', file=sys.stderr)
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
