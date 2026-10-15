"""Painel OBS GTK4/libadwaita; usa um backend isolado sob a .venv.

Nunca recebe a senha do OBS, não abre HID e não executa operações OBS:
apenas lê estados e grava configurações YAML após confirmação do usuário.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv/bin/python'
BACKEND = ROOT / 'apps/vision02_obs_panel_backend.py'

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, GLib, Gtk

OPERATIONS = [
    ('toggle_record', 'Alternar gravação'),
    ('toggle_pause', 'Pausar / retomar gravação'),
    ('toggle_stream', 'Alternar transmissão ao vivo'),
    ('toggle_mic', 'Alternar microfone'),
    ('toggle_desktop', 'Alternar áudio desktop'),
    ('scene_name', 'Selecionar cena por nome'),
    ('scene_slot', 'Cena por posição (legado; ordem instável)'),
    ('next_scene', 'Próxima cena'),
    ('previous_scene', 'Cena anterior'),
    ('toggle_virtualcam', 'Alternar câmera virtual'),
    ('save_replay', 'Salvar replay'),
    ('screenshot', 'Capturar imagem'),
    ('refresh', 'Consultar estado do OBS'),
]
OP_KEYS = [op for op, _ in OPERATIONS]


def backend(command, payload=None, *, timeout=25):
    result = subprocess.run([str(PYTHON), str(BACKEND), '--command', command],
                            text=True, capture_output=True, timeout=timeout, check=False,
                            input=json.dumps(payload, ensure_ascii=False) if payload is not None else None)
    try:
        response = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise RuntimeError((result.stderr or result.stdout or str(exc)).strip()) from exc
    if not response.get('ok'):
        raise RuntimeError(response.get('error', 'Falha no backend OBS'))
    return response


class OBSPanel(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='Configuração OBS — Vision 02')
        self.set_default_size(810, 790)
        self.set_size_request(680, 570)
        self.profile = None
        self.discovery = None
        self.selected_key = 1
        self.dirty = False
        self.busy = False
        self._syncing = True
        self._closed = False
        self._generation = 0

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)
        self.set_content(toolbar)
        scroll = Gtk.ScrolledWindow()
        toolbar.set_content(scroll)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.set_margin_top(18)
        root.set_margin_bottom(18)
        root.set_margin_start(22)
        root.set_margin_end(22)
        scroll.set_child(root)
        title = Gtk.Label(label='Painel OBS Studio')
        title.add_css_class('title-1')
        title.set_xalign(0)
        root.append(title)
        caption = Gtk.Label(label='Configura apenas o perfil OBS Studio. Nenhum comando é executado no OBS ao salvar.')
        caption.set_xalign(0)
        caption.set_wrap(True)
        caption.add_css_class('dim-label')
        root.append(caption)

        connection = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.test_btn = Gtk.Button(label='Testar conexão / atualizar cenas')
        self.test_btn.connect('clicked', lambda *_: self._work('discover'))
        connection.append(self.test_btn)
        self.obs_state = Gtk.Label(label='OBS ainda não consultado')
        self.obs_state.set_xalign(0)
        self.obs_state.set_wrap(True)
        self.obs_state.set_hexpand(True)
        connection.append(self.obs_state)
        root.append(connection)
        self.live_state = Gtk.Label(label='Estados de gravação, transmissão e câmera serão consultados sem executar ações.')
        self.live_state.set_xalign(0)
        self.live_state.set_wrap(True)
        self.live_state.add_css_class('dim-label')
        root.append(self.live_state)
        self.scene_info = Gtk.Label(label='Cenas disponíveis: não consultadas')
        self.scene_info.set_xalign(0)
        self.scene_info.set_wrap(True)
        root.append(self.scene_info)
        self.batch_btn = Gtk.Button(label='Organizar cenas nas teclas (até 14)…')
        self.batch_btn.connect('clicked', self._open_scene_batch)
        root.append(self.batch_btn)
        self._batch_window = None
        self.multi_profiles_btn = Gtk.Button(label='Criar perfis OBS: Controle / Cenas / Áudio…')
        self.multi_profiles_btn.connect('clicked', self._open_multi_profiles)
        root.append(self.multi_profiles_btn)
        self.visual_btn = Gtk.Button(label='Editor visual de cenas e áudio…')
        self.visual_btn.connect('clicked', self._open_visual)
        root.append(self.visual_btn)

        choice = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        choice.append(Gtk.Label(label='Tecla física OBS:'))
        self.key_combo = Gtk.DropDown.new_from_strings([f'{i:02d}' for i in range(1, 15)])
        self.key_combo.connect('notify::selected', self._key_changed)
        choice.append(self.key_combo)
        choice.append(Gtk.Label(label='15 = Voltar ao Sistema (preservada)'))
        root.append(choice)

        fields = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        root.append(fields)
        fields.append(Gtk.Label(label='Rótulo da tecla (mantém ícone e aparência existentes)'))
        self.label_entry = Gtk.Entry()
        self.label_entry.connect('changed', self._changed)
        fields.append(self.label_entry)
        fields.append(Gtk.Label(label='Ação OBS'))
        self.operation = Gtk.DropDown.new_from_strings([name for _, name in OPERATIONS])
        self.operation.connect('notify::selected', self._operation_changed)
        fields.append(self.operation)

        self.scene_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.scene_row.append(Gtk.Label(label='Cena exata (requer conexão ao OBS para listar)'))
        self.scene_combo = Gtk.DropDown.new_from_strings(['Consulte as cenas do OBS'])
        self.scene_combo.connect('notify::selected', self._changed)
        self.scene_row.append(self.scene_combo)
        fields.append(self.scene_row)
        self.slot_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.slot_row.append(Gtk.Label(label='Posição da cena (modo legado)'))
        self.slot_combo = Gtk.DropDown.new_from_strings(['Cena 1', 'Cena 2', 'Cena 3'])
        self.slot_combo.connect('notify::selected', self._changed)
        self.slot_row.append(self.slot_combo)
        fields.append(self.slot_row)
        self.input_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.input_row.append(Gtk.Label(label='Entrada OBS (automática ou nome exato)'))
        self.input_combo = Gtk.DropDown.new_from_strings(['Automática'])
        self.input_combo.connect('notify::selected', self._changed)
        self.input_row.append(self.input_combo)
        fields.append(self.input_row)
        self.warning = Gtk.Label(label='Transmissão ao vivo pode iniciar uma live real ao pressionar a tecla. O painel nunca inicia uma live.')
        self.warning.set_wrap(True)
        self.warning.set_xalign(0)
        self.warning.add_css_class('dim-label')
        fields.append(self.warning)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.save_btn = Gtk.Button(label='Salvar associação no YAML')
        self.save_btn.add_css_class('suggested-action')
        self.save_btn.connect('clicked', self._save_clicked)
        actions.append(self.save_btn)
        self.apply_btn = Gtk.Button(label='Aplicar ao dispositivo')
        self.apply_btn.connect('clicked', lambda *_: self._work('apply'))
        actions.append(self.apply_btn)
        self.load_btn = Gtk.Button(label='Recarregar configuração')
        self.load_btn.connect('clicked', self._reload_profile)
        actions.append(self.load_btn)
        root.append(actions)
        self.status = Gtk.Label(label='')
        self.status.set_wrap(True)
        self.status.set_xalign(0)
        root.append(self.status)
        self.connect('close-request', self._on_close)
        self._load_profile()
        self._work('discover')
        self._syncing = False

    def _open_visual(self, *_):
        launcher = ROOT / 'scripts/vision02-obs-visual'
        try:
            subprocess.Popen([str(launcher)], cwd=ROOT, start_new_session=True)
        except OSError as exc:
            self.status.set_text(f'Falha ao abrir editor OBS visual: {exc}')

    def _open_multi_profiles(self, *_):
        # Processo GTK independente: mantém o painel principal responsivo.
        launcher = ROOT / 'scripts/vision02-obs-profiles'
        try:
            subprocess.Popen([str(launcher)], cwd=ROOT, start_new_session=True)
        except OSError as exc:
            self.status.set_text(f'Falha ao abrir gerenciador de perfis OBS: {exc}')

    def _open_scene_batch(self, *_):
        if self.busy or self.dirty:
            self.status.set_text('Salve ou descarte a edição atual antes de organizar cenas.')
            return
        scenes = list(dict.fromkeys((self.discovery or {}).get('scenes') or []))
        if not scenes:
            self.status.set_text('Clique em Testar conexão / atualizar cenas antes de organizar.')
            return
        if self._batch_window is not None:
            self._batch_window.present()
            return
        win = Gtk.Window(title='Organizar cenas OBS — Vision 02', transient_for=self, modal=True)
        win.set_default_size(650, 640)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(16); box.set_margin_bottom(16)
        box.set_margin_start(16); box.set_margin_end(16)
        win.set_child(box)
        label = Gtk.Label(label='Cada cena é associada pelo nome exato; a ordem do OBS não importa.\nTecla 15 permanece Voltar. As ações das teclas escolhidas serão substituídas.')
        label.set_xalign(0); label.set_wrap(True)
        box.append(label)
        settings = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.append(settings)
        settings.append(Gtk.Label(label='Primeira tecla:'))
        first = Gtk.SpinButton.new_with_range(1, 14, 1)
        first.set_value(6)
        settings.append(first)
        settings.append(Gtk.Label(label='Quantidade:'))
        count = Gtk.SpinButton.new_with_range(1, 14, 1)
        count.set_value(min(5, len(scenes)))
        settings.append(count)
        area = Gtk.ScrolledWindow()
        area.set_vexpand(True)
        box.append(area)
        rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        area.set_child(rows)
        feedback = Gtk.Label(label='Escolha as cenas na ordem desejada e confirme. Não altera cenas no OBS.')
        feedback.set_xalign(0); feedback.set_wrap(True)
        box.append(feedback)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(actions)
        cancel = Gtk.Button(label='Cancelar')
        cancel.connect('clicked', lambda *_: win.close())
        actions.append(cancel)
        submit = Gtk.Button(label='Salvar cenas no YAML')
        submit.add_css_class('suggested-action')
        actions.append(submit)
        choices = []
        def rebuild(*_):
            while row := rows.get_first_child():
                rows.remove(row)
            choices.clear()
            start = first.get_value_as_int()
            total = count.get_value_as_int()
            if start + total > 15 or total > len(scenes):
                feedback.set_text('A quantidade excede as teclas 01–14 ou as cenas existentes no OBS.')
                submit.set_sensitive(False)
                return
            submit.set_sensitive(True)
            feedback.set_text(f'{total} cena(s) nas teclas {start:02d}–{start+total-1:02d}. Revise as associações antes de salvar.')
            for offset in range(total):
                key = start + offset
                line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                line.append(Gtk.Label(label=f'Tecla {key:02d}'))
                combo = Gtk.DropDown.new_from_strings(scenes)
                existing = (self.profile or {}).get('keys', {}).get(str(key), {}).get('action') or {}
                selected = existing.get('scene') if existing.get('operation') == 'scene_name' else None
                combo.set_selected(scenes.index(selected) if selected in scenes else offset)
                combo.set_hexpand(True)
                line.append(combo)
                rows.append(line)
                choices.append((key, combo))
        first.connect('value-changed', rebuild)
        count.connect('value-changed', rebuild)
        def ask_save(*_):
            assignments = [{'key_id': key, 'scene': scenes[combo.get_selected()]}
                           for key, combo in choices]
            if len({item['scene'] for item in assignments}) != len(assignments):
                feedback.set_text('Uma cena foi selecionada em duas teclas. Cada tecla precisa de cena diferente.')
                return
            if self.profile is None:
                return
            payload = {'sha256': self.profile['sha256'], 'assignments': assignments}
            description = ', '.join(f'{item["key_id"]:02d} → {item["scene"]}' for item in assignments)
            dialog = Adw.MessageDialog.new(win, 'Substituir ações dessas teclas?',
                                           description + '\nAs imagens e a aparência serão preservadas. Nenhum comando será executado no OBS.')
            dialog.add_response('cancel', 'Cancelar')
            dialog.add_response('save', 'Salvar associações')
            dialog.set_response_appearance('save', Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.connect('response', lambda _d, response: self._work('save_scenes', payload) if response == 'save' else None)
            dialog.present()
        submit.connect('clicked', ask_save)
        win.connect('close-request', lambda *_: setattr(self, '_batch_window', None) or False)
        self._batch_window = win
        rebuild()
        win.present()

    def _on_close(self, *_):
        self._closed = True
        self._generation += 1
        return False

    def _busy_state(self, value):
        self.busy = value
        self.save_btn.set_sensitive(not value)
        self.apply_btn.set_sensitive(not value and not self.dirty)
        self.test_btn.set_sensitive(not value)
        self.load_btn.set_sensitive(not value)
        self.batch_btn.set_sensitive(not value)

    def _changed(self, *_):
        if not self._syncing:
            self.dirty = True
            self.apply_btn.set_sensitive(False)
            self.status.set_text('Configuração local não salva.')

    def _operation_changed(self, *_):
        op = OP_KEYS[self.operation.get_selected()]
        self.scene_row.set_visible(op == 'scene_name')
        self.slot_row.set_visible(op == 'scene_slot')
        self.input_row.set_visible(op in ('toggle_mic', 'toggle_desktop'))
        self.warning.set_visible(op == 'toggle_stream')
        self._changed()

    def _key_changed(self, combo, *_):
        if self._syncing or self.busy:
            return
        key_id = combo.get_selected() + 1
        if key_id == self.selected_key:
            return
        if self.dirty:
            self.status.set_text('Salve ou recarregue antes de mudar de tecla.')
            self._syncing = True
            self.key_combo.set_selected(self.selected_key - 1)
            self._syncing = False
            return
        self.selected_key = key_id
        self._populate()

    def _load_profile(self):
        try:
            self.profile = backend('inspect')['profile']
            self._populate()
            self.status.set_text(f'Perfil pessoal: {self.profile["path"]}')
        except (RuntimeError, OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
            self.profile = None
            self.status.set_text(f'Falha ao carregar perfil OBS Studio: {exc}')
            self.save_btn.set_sensitive(False)

    def _reload_profile(self, *_):
        if self.busy:
            return
        if self.dirty:
            dialog = Adw.MessageDialog.new(self, 'Descartar alterações não salvas?',
                                            'O perfil será recarregado do disco.')
            dialog.add_response('cancel', 'Cancelar')
            dialog.add_response('discard', 'Descartar')
            dialog.set_response_appearance('discard', Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.connect('response', self._reloaded_response)
            dialog.present()
        else:
            self._load_profile()

    def _reloaded_response(self, _dialog, response):
        if response == 'discard':
            self.dirty = False
            self._load_profile()

    def _populate(self):
        if self.profile is None:
            return
        self._syncing = True
        try:
            cfg = self.profile['keys'][str(self.selected_key)]
            action = cfg.get('action') or {}
            self.label_entry.set_text(cfg.get('label') or f'OBS {self.selected_key:02d}')
            operation = action.get('operation') if action.get('type') == 'obs' else 'refresh'
            self.operation.set_selected(OP_KEYS.index(operation) if operation in OP_KEYS else OP_KEYS.index('refresh'))
            self.slot_combo.set_selected(max(0, min(2, int(action.get('slot') or 1) - 1)))
            self._sync_choices(scene=action.get('scene'), audio=action.get('input'))
            self.dirty = False
            self.apply_btn.set_sensitive(True)
            self._operation_changed()
            if action.get('type') != 'obs':
                self.status.set_text('Essa tecla não contém ação OBS; salvar substituirá somente a ação.')
        finally:
            self._syncing = False

    def _sync_choices(self, scene=None, audio=None):
        scenes = (self.discovery or {}).get('scenes') or []
        self._scene_names = list(scenes)
        if scene and scene not in self._scene_names:
            self._scene_names.append(scene)  # permite preservar cena ausente, sem inventar uma nova
        self.scene_combo.set_model(Gtk.StringList.new(self._scene_names or ['(sem cenas; consulte o OBS)']))
        self.scene_combo.set_selected(self._scene_names.index(scene) if scene in self._scene_names else 0)
        inputs = [item['name'] for item in (self.discovery or {}).get('inputs', [])]
        self._input_names = [''] + list(dict.fromkeys(inputs))
        if audio and audio not in self._input_names:
            self._input_names.append(audio)
        self.input_combo.set_model(Gtk.StringList.new(['Automática'] + [name for name in self._input_names[1:]]))
        self.input_combo.set_selected(self._input_names.index(audio) if audio in self._input_names else 0)

    def _work(self, command, payload=None):
        if self.busy:
            return
        if command == 'apply' and self.dirty:
            self.status.set_text('Salve a associação antes de aplicar.')
            return
        self._busy_state(True)
        self.status.set_text('Processando ' + command + '…')
        self._generation += 1
        generation = self._generation
        def worker():
            try:
                response = backend(command, payload, timeout=60 if command == 'apply' else 25)
                error = None
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                response, error = None, str(exc)
            GLib.idle_add(self._done, generation, command, response, error)
        threading.Thread(target=worker, name='vision02-obs-panel', daemon=True).start()

    def _done(self, generation, command, response, error):
        if self._closed or generation != self._generation:
            return False
        self._busy_state(False)
        if error:
            self.status.set_text(f'Falha em {command}: {error}')
            if command == 'discover':
                self.obs_state.set_text('OBS OFFLINE / autenticação indisponível')
            return False
        if command == 'discover':
            self.discovery = response['obs']
            self.obs_state.set_text(f'OBS {self.discovery.get("obs_version")} · WebSocket {self.discovery.get("websocket_version")} · conectado')
            self.scene_info.set_text('Cenas: ' + ', '.join(self.discovery['scenes']) if self.discovery['scenes'] else 'Nenhuma cena')
            states = self.discovery['states']
            def state(value):
                return 'SIM' if value is True else 'NÃO' if value is False else 'N/D'
            self.live_state.set_text('Gravando: {}  |  Ao vivo: {}  |  Câmera virtual: {}  |  Cena: {}'.format(
                state(states.get('recording')), state(states.get('streaming')),
                state(states.get('virtualcam')), self.discovery.get('active_scene') or 'N/D'))
            self._syncing = True
            try:
                cfg = self.profile['keys'][str(self.selected_key)] if self.profile else {}
                action = cfg.get('action', {})
                current_scene = self._scene_names[self.scene_combo.get_selected()] if getattr(self, '_scene_names', []) and self.scene_combo.get_selected() < len(self._scene_names) else None
                current_input = self._input_names[self.input_combo.get_selected()] if hasattr(self, '_input_names') and self.input_combo.get_selected() < len(self._input_names) else None
                self._sync_choices(scene=current_scene or action.get('scene'), audio=current_input or action.get('input'))
            finally:
                self._syncing = False
            self.status.set_text('Conexão autenticada. Nenhuma ação OBS foi executada.')
        elif command in ('save', 'save_scenes'):
            self.dirty = False
            self._load_profile()
            if command == 'save_scenes' and self._batch_window is not None:
                self._batch_window.close()
            self.status.set_text(f'YAML salvo. Backup: {response.get("backup", "disponível")}. Clique Aplicar ao dispositivo.')
        elif command == 'apply':
            self.status.set_text('Configuração aplicada por IPC, sem reiniciar o serviço.')
        return False

    def _save_clicked(self, *_):
        if self.busy or self.profile is None:
            return
        op = OP_KEYS[self.operation.get_selected()]
        scene = ''
        if op == 'scene_name':
            if not self._scene_names or self.scene_combo.get_selected() >= len(self._scene_names):
                self.status.set_text('Conecte ao OBS e escolha uma cena válida.')
                return
            scene = self._scene_names[self.scene_combo.get_selected()]
        audio = ''
        if op in ('toggle_mic', 'toggle_desktop'):
            audio = self._input_names[self.input_combo.get_selected()]
        payload = {'key_id': self.selected_key, 'sha256': self.profile['sha256'],
                   'label': self.label_entry.get_text(), 'operation': op,
                   'scene': scene, 'input': audio,
                   'slot': self.slot_combo.get_selected() + 1 if op == 'scene_slot' else None}
        if op == 'toggle_stream':
            dialog = Adw.MessageDialog.new(self, 'Configurar tecla de transmissão?',
                                           'Pressionar essa tecla no equipamento poderá iniciar uma transmissão real. Salvar agora NÃO inicia a live.')
            dialog.add_response('cancel', 'Cancelar')
            dialog.add_response('save', 'Salvar associação')
            dialog.set_response_appearance('save', Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.connect('response', lambda _d, choice: self._work('save', payload) if choice == 'save' else None)
            dialog.present()
        else:
            self._work('save', payload)


class OBSApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='io.github.vision02.OBSPanel')
        self.connect('activate', self._activate)

    def _activate(self, app):
        win = self.props.active_window
        if win is None:
            win = OBSPanel(self)
        win.present()


def main():
    return OBSApp().run(sys.argv)


if __name__ == '__main__':
    raise SystemExit(main())
