"""GTK4 / libadwaita: assistente de criação dos perfis OBS especializados."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv/bin/python'
BACKEND = ROOT / 'apps/vision02_obs_profiles_backend.py'

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib


def call(command: str, payload=None):
    proc = subprocess.run([str(PYTHON), str(BACKEND), '--command', command],
                          input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                          text=True, capture_output=True, timeout=35, check=False)
    try:
        result = json.loads(proc.stdout)
    except ValueError as exc:
        raise RuntimeError(proc.stderr.strip() or 'Backend indisponível') from exc
    if not result.get('ok'):
        raise RuntimeError(result.get('error', 'Operação não concluída'))
    return result


class OBSProfilesWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='Perfis OBS — Vision 02')
        self.set_default_size(760, 780)
        self.catalog = None
        self.obs = None
        self.busy = False
        self._generation = 0
        self._closed = False
        self.scene_checks = []
        self.audio_checks = []

        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        self.set_content(view)
        scroll = Gtk.ScrolledWindow()
        view.set_content(scroll)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for edge in ('top', 'bottom', 'start', 'end'):
            getattr(root, 'set_margin_' + edge)(20)
        scroll.set_child(root)

        title = Gtk.Label(label='Criar perfis OBS especializados')
        title.add_css_class('title-1')
        title.set_xalign(0)
        root.append(title)
        explanation = Gtk.Label(label='Cria três novos perfis sem substituir OBS Studio: '
                             'OBS — Controle, OBS — Cenas e OBS — Áudio. '
                             'Nenhuma ação OBS é executada durante a configuração.')
        explanation.set_wrap(True)
        explanation.set_xalign(0)
        root.append(explanation)
        self.discover_btn = Gtk.Button(label='Consultar cenas e fontes do OBS')
        self.discover_btn.connect('clicked', lambda *_: self._work('discover'))
        root.append(self.discover_btn)
        self.catalog_label = Gtk.Label(label='Consultando catálogo…')
        self.catalog_label.set_xalign(0)
        self.catalog_label.set_wrap(True)
        root.append(self.catalog_label)
        scenes_header = Gtk.Label(label='Cenas: selecione até 14 (uma por tecla)')
        scenes_header.add_css_class('title-3')
        scenes_header.set_xalign(0)
        root.append(scenes_header)
        self.scene_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        root.append(self.scene_box)
        aud_header = Gtk.Label(label='Fontes de áudio: selecione até 12')
        aud_header.add_css_class('title-3')
        aud_header.set_xalign(0)
        root.append(aud_header)
        self.audio_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        root.append(self.audio_box)
        root.append(Gtk.Label(label='No perfil Cenas, a tecla 15 volta ao Controle. '
                                     'No perfil Áudio, as teclas 13–15 permitem navegar.'))
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        root.append(buttons)
        self.create_btn = Gtk.Button(label='Criar os três perfis')
        self.create_btn.add_css_class('suggested-action')
        self.create_btn.connect('clicked', self._confirm)
        buttons.append(self.create_btn)
        self.apply_btn = Gtk.Button(label='Aplicar ao dispositivo (IPC)')
        self.apply_btn.connect('clicked', lambda *_: self._work('apply'))
        buttons.append(self.apply_btn)
        self.status = Gtk.Label(label='')
        self.status.set_xalign(0)
        self.status.set_wrap(True)
        root.append(self.status)
        self.connect('close-request', self._on_close)
        self._work('discover')

    def _on_close(self, *_):
        self._closed = True
        self._generation += 1
        return False

    def _render_checks(self, where, names, maximum, selected):
        while row := where.get_first_child():
            where.remove(row)
        result = []
        if not names:
            label = Gtk.Label(label='Nenhuma entrada encontrada.')
            label.set_xalign(0)
            where.append(label)
        for index, name in enumerate(names):
            check = Gtk.CheckButton(label=name)
            check.set_active(index < selected)
            where.append(check)
            result.append((name, check))
        return result

    def _busy(self, yes: bool):
        self.busy = yes
        self.discover_btn.set_sensitive(not yes)
        self.create_btn.set_sensitive(not yes and self.catalog is not None and self.obs is not None)
        self.apply_btn.set_sensitive(not yes)

    def _work(self, command, payload=None):
        if self.busy:
            return
        self._busy(True)
        self.status.set_text('Executando ' + command + '…')
        self._generation += 1
        generation = self._generation
        def worker():
            try:
                response, error = call(command, payload), None
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                response, error = None, str(exc)
            GLib.idle_add(self._done, generation, command, response, error)
        threading.Thread(target=worker, daemon=True, name='vision02-obs-profiles-gui').start()

    def _done(self, generation, command, response, error):
        if self._closed or generation != self._generation:
            return False
        self._busy(False)
        if error:
            self.status.set_text('Falha: ' + error)
            return False
        if command == 'discover':
            self.obs = response['obs']
            self.catalog = response['catalog']
            names = [item['name'] for item in self.catalog['profiles']]
            self.catalog_label.set_text('OBS ' + str(self.obs.get('obs_version')) +
                                        ' · Perfis atuais: ' + ', '.join(names))
            scenes = list(dict.fromkeys(self.obs.get('scenes', [])))
            inputs = list(dict.fromkeys(x['name'] for x in self.obs.get('inputs', [])))
            self.scene_checks = self._render_checks(self.scene_box, scenes, 14, min(len(scenes), 14))
            self.audio_checks = self._render_checks(self.audio_box, inputs, 12, 0)
            self.status.set_text('Selecione as fontes. A tecla de transmissão do perfil Controle poderá iniciar uma live ao ser pressionada.')
        elif command == 'create':
            self.create_btn.set_sensitive(False)
            self.status.set_text('Três perfis criados. Clique Aplicar ao dispositivo ou use control reload.')
        elif command == 'apply':
            self.status.set_text('Catálogo recarregado por IPC. Selecione OBS — Controle na Vision 02.')
        return False

    def _confirm(self, *_):
        if self.busy or not self.catalog or not self.obs:
            return
        scenes = [name for name, check in self.scene_checks if check.get_active()]
        inputs = [name for name, check in self.audio_checks if check.get_active()]
        if len(scenes) > 14 or len(inputs) > 12:
            self.status.set_text('Selecione até 14 cenas e até 12 fontes de áudio.')
            return
        payload = {'scenes': scenes, 'inputs': inputs, 'version': self.catalog['version']}
        prompt = Adw.MessageDialog.new(
            self, 'Criar três perfis OBS?',
            f'{len(scenes)} cenas e {len(inputs)} fontes de áudio. '
            'Os perfis existentes permanecerão intactos. '
            'O novo perfil Controle incluirá uma tecla capaz de iniciar transmissão ao vivo; '
            'nada será transmitido agora.')
        prompt.add_response('cancel', 'Cancelar')
        prompt.add_response('save', 'Criar perfis')
        prompt.set_response_appearance('save', Adw.ResponseAppearance.SUGGESTED)
        prompt.connect('response', lambda _d, choice: self._work('create', payload) if choice == 'save' else None)
        prompt.present()


class OBSProfilesApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='io.github.vision02.OBSProfiles')
        self.connect('activate', self._activated)

    def _activated(self, *_):
        window = self.props.active_window
        if window is None:
            window = OBSProfilesWindow(self)
        window.present()


def main():
    return OBSProfilesApp().run(sys.argv)


if __name__ == '__main__':
    raise SystemExit(main())
