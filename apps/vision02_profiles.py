"""Gerenciador GTK 4/libadwaita de perfis pessoais da Vision 02.

Cliente IPC e editor YAML externo. Não acessa dispositivos hidraw.
"""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv/bin/python'
BACKEND = ROOT / 'apps/vision02_profile_manager_backend.py'

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib


class ProfilesWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='Gerenciar perfis — Vision 02')
        self.set_default_size(690, 560)
        self.busy = False
        self.info = {}
        self.names = []
        root = Adw.ToolbarView()
        root.add_top_bar(Adw.HeaderBar())
        self.set_content(root)
        scroll = Gtk.ScrolledWindow()
        root.set_content(scroll)
        area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        for key in ('margin_top','margin_bottom','margin_start','margin_end'):
            setattr(area.props, key, 22)
        scroll.set_child(area)
        heading = Gtk.Label(label='Perfis pessoais')
        heading.add_css_class('title-1')
        heading.set_xalign(0)
        area.append(heading)
        help_text = Gtk.Label(label='Gerencie os perfis YAML locais. O serviço HID permanece independente.')
        help_text.set_wrap(True)
        help_text.set_xalign(0)
        area.append(help_text)

        def line(label):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row.append(Gtk.Label(label=label))
            area.append(row)
            return row

        row = line('Selecionar perfil:')
        self.select = Gtk.DropDown.new_from_strings(['Carregando…'])
        self.select.set_hexpand(True)
        row.append(self.select)
        self.refresh = Gtk.Button(icon_name='view-refresh-symbolic')
        self.refresh.connect('clicked', lambda *_: self._run('list'))
        row.append(self.refresh)
        row = line('Nome novo:')
        self.name_entry = Gtk.Entry()
        self.name_entry.set_hexpand(True)
        self.name_entry.set_placeholder_text('Ex.: Produtividade')
        row.append(self.name_entry)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        area.append(row)
        for label, command in [('Criar', 'create'), ('Duplicar', 'duplicate'), ('Renomear', 'rename'), ('Excluir', 'delete')]:
            btn = Gtk.Button(label=label)
            btn.connect('clicked', self._on_action, command)
            row.append(btn)
        self.startup = Gtk.Button(label='Definir como inicial')
        self.startup.connect('clicked', self._on_action, 'startup')
        area.append(self.startup)
        self.restore = Gtk.CheckButton(label='Restaurar o último perfil ativo ao iniciar')
        area.append(self.restore)
        hint = Gtk.Label(label='Para excluir um perfil referenciado por outras teclas, altere essas ações primeiro.\nNão é possível renomear ou excluir o perfil atualmente ativo no dispositivo.')
        hint.set_wrap(True)
        hint.set_xalign(0)
        hint.add_css_class('dim-label')
        area.append(hint)
        self.apply_btn = Gtk.Button(label='Aplicar catálogo ao dispositivo (IPC reload)')
        self.apply_btn.add_css_class('suggested-action')
        self.apply_btn.connect('clicked', self._on_action, 'apply')
        area.append(self.apply_btn)
        self.status = Gtk.Label(label='Consultando…')
        self.status.set_xalign(0)
        self.status.set_wrap(True)
        area.append(self.status)
        self._run('list')

    def _on_action(self, _button, command):
        if self.busy:
            return
        index = self.select.get_selected()
        selected = self.names[index] if 0 <= index < len(self.names) else None
        new_name = self.name_entry.get_text().strip()
        version = self.info.get('version')
        if command == 'delete':
            dialog = Adw.AlertDialog(heading='Excluir perfil?', body=f'O perfil {selected} será removido do disco após backup. Esta operação não pode ser desfeita pela interface.')
            dialog.add_response('cancel', 'Cancelar')
            dialog.add_response('delete', 'Excluir')
            dialog.set_response_appearance('delete', Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.connect('response', lambda _dialog, response: self._run('delete', {'name': selected, 'version': version}) if response == 'delete' else None)
            dialog.present(self)
            return
        if command == 'create':
            payload = {'name': new_name, 'version': version}
        elif command == 'duplicate':
            payload = {'source': selected, 'name': new_name, 'version': version}
        elif command == 'rename':
            payload = {'source': selected, 'name': new_name, 'version': version}
        elif command == 'startup':
            payload = {'name': selected, 'restore_last': self.restore.get_active(), 'version': version}
        else:
            payload = None
        self._run(command, payload)

    def _run(self, command: str, payload=None):
        if self.busy:
            return
        self.busy = True
        self.refresh.set_sensitive(False)
        self.status.set_text(f'Executando: {command}…')

        def worker():
            try:
                if command == 'apply':
                    proc = subprocess.run([str(PYTHON), '-m', 'vision02.cli', 'control', 'reload'], text=True, capture_output=True, timeout=55)
                else:
                    proc = subprocess.run([str(PYTHON), str(BACKEND), '--command', command], input=json.dumps(payload, ensure_ascii=False) if payload is not None else None, text=True, capture_output=True, timeout=40)
                response = json.loads(proc.stdout)
                if proc.returncode or not response.get('ok'):
                    raise RuntimeError(response.get('error') or proc.stderr or 'Operação falhou')
                message = ('Catálogo aplicado ao dispositivo.' if command == 'apply'
                           else ('Configuração atualizada. Clique em Aplicar ao dispositivo para recarregar.' if command != 'list' else None))
                error = None
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                response, message, error = None, None, str(exc)
            GLib.idle_add(self._complete, command, response, message, error)
        threading.Thread(target=worker, daemon=True, name='vision02-profile-operation').start()

    def _complete(self, command, response, message, error):
        self.busy = False
        self.refresh.set_sensitive(True)
        if error:
            self.status.set_text(f'Erro: {error}')
            return False
        if command == 'list':
            self.info = response
            self.names = [item['name'] for item in response['profiles']]
            self.select.set_model(Gtk.StringList.new(self.names))
            active = response.get('active')
            if active in self.names:
                self.select.set_selected(self.names.index(active))
            self.restore.set_active(response['settings']['restore_last'])
            self.status.set_text(f'{len(self.names)} perfis disponíveis; em uso: {active or "indisponível"}')
        elif command != 'apply':
            self.status.set_text(message)
            self._run('list')
        else:
            self.status.set_text(message)
        return False


class ProfileManagerApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='io.github.vision02.Profiles')
        self.connect('activate', self._activate)

    def _activate(self, _app):
        window = self.props.active_window
        if window is None:
            window = ProfilesWindow(self)
        window.present()


def main():
    Adw.init()
    return ProfileManagerApp().run(sys.argv)


if __name__ == '__main__':
    raise SystemExit(main())
