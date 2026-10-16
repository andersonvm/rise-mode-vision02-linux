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
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from vision02.editor_navigation import editor_args
from vision02.studio_interaction import DoubleClickDetector
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
        self._icons = []
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
        self.key_grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        self.key_grid.set_column_homogeneous(True)
        page.append(self.key_grid)
        self.key_activity_label = _label('Pressione uma tecla física para verificar o destaque.', wrap=True)
        page.append(self.key_activity_label)
        self.key_buttons = {}
        for ident in range(1, 16):
            button = Gtk.Button()
            button.add_css_class('card')
            button.set_size_request(117, 142)
            button.connect('clicked', self._key_selected, ident)
            self.key_grid.attach(button, (ident - 1) % 5, (ident - 1) // 5, 1, 1)
            self.key_buttons[ident] = button
        self.key_detail = _label('Selecione uma tecla.', wrap=True)
        page.append(self.key_detail)
        self._render_keys()

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
            elif command == 'key_activity':
                self.key_activity_label.set_text(
                    'Sem eventos via IPC: ' + str(message) +
                    '. Confirme o reinício de vision02.service.'
                )
            elif command == 'obs':
                self.obs_state.set_text(f'OBS indisponível: {message}')
            elif command == 'system':
                self.system_state.set_text(f'Métricas indisponíveis: {message}')
            else:
                self.top_status.set_text(f'{command}: {message}')
            return False
        if command in {'status', 'switch', 'reload'}:
            if command == 'reload':
                self._call('previews')
                self._call('live_preview')
            self._call('status') if command in {'switch', 'reload'} else None
            if command != 'status':
                return False
            self._connected = bool(response.get('connected'))
            self._current = str(response.get('active') or '')
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
        elif command == 'import_icon':
            self._call('icons')
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
        double_click = self._click_detector.click(key_id)
        self._selected_key = key_id
        self._update_key_highlight()
        self._update_key_detail()
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

    def _choose_icon(self, *_):
        dialog = Gtk.FileChooserNative.new('Importar ícone', self,
                                           Gtk.FileChooserAction.OPEN,
                                           'Importar', 'Cancelar')
        def done(chooser, response):
            if response == Gtk.ResponseType.ACCEPT:
                selected = chooser.get_file()
                if selected and selected.get_path():
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
