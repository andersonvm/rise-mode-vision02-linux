"""GTK 4 visual OBS scenes/audio editor; OBS and YAML I/O in isolated backend.

Drag OBS names onto physical grid. Source/scene changes are only committed after
Save; audio mixer actions are explicit buttons and do not access system volume.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv/bin/python'
BACKEND = ROOT / 'apps/vision02_obs_visual_backend.py'

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, GLib, GObject, Gtk

MODES = ['OBS — Cenas', 'OBS — Áudio']


def backend(command: str, payload=None):
    proc = subprocess.run([str(PYTHON), str(BACKEND), '--command', command],
                          input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                          text=True, capture_output=True, timeout=40, check=False)
    try:
        response = json.loads(proc.stdout)
    except ValueError as exc:
        raise RuntimeError(proc.stderr.strip() or 'Backend OBS indisponível') from exc
    if not response.get('ok'):
        raise RuntimeError(response.get('error', 'Operação não concluída'))
    return response


class OBSVisualWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='Editor visual OBS — Vision 02')
        self.set_default_size(980, 820)
        self.mode = MODES[0]
        self.profile = None
        self.obs = None
        self.audio = None
        self.entries = {}
        self.selected = 1
        self.palette_selected = None
        self.dirty = False
        self.busy = False
        self._closed = False
        self._generation = 0
        self._syncing_mode = False

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        self.set_content(toolbar)
        scroll = Gtk.ScrolledWindow()
        toolbar.set_content(scroll)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(content, 'set_margin_' + side)(18)
        scroll.set_child(content)
        title = Gtk.Label(label='Cenas e fontes de áudio — grade física 5 × 3')
        title.add_css_class('title-1')
        title.set_xalign(0)
        content.append(title)
        info = Gtk.Label(label='Arraste uma cena/fonte para uma tecla. Arraste teclas entre si para trocar posições. '
                               'Também é possível selecionar uma fonte e clicar na tecla. '
                               'Nada é enviado ao OBS durante a organização do layout.')
        info.set_xalign(0)
        info.set_wrap(True)
        content.append(info)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        content.append(actions)
        actions.append(Gtk.Label(label='Editar perfil:'))
        self.mode_combo = Gtk.DropDown.new_from_strings(MODES)
        self.mode_combo.connect('notify::selected', self._change_mode)
        actions.append(self.mode_combo)
        self.refresh_btn = Gtk.Button(label='Consultar OBS e recarregar')
        self.refresh_btn.connect('clicked', self._refresh)
        actions.append(self.refresh_btn)

        mid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        content.append(mid)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        left.set_hexpand(True)
        mid.append(left)
        grid_title = Gtk.Label(label='Vision 02 — teclas 01–15')
        grid_title.add_css_class('title-3')
        grid_title.set_xalign(0)
        left.append(grid_title)
        self.grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        left.append(self.grid)
        self.position_info = Gtk.Label(label='Tecla 01 selecionada')
        self.position_info.set_xalign(0)
        left.append(self.position_info)
        self.clear_btn = Gtk.Button(label='Limpar tecla selecionada')
        self.clear_btn.connect('clicked', self._clear_selected)
        left.append(self.clear_btn)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        right.set_hexpand(True)
        mid.append(right)
        palette_title = Gtk.Label(label='Cenas ou fontes disponíveis no OBS')
        palette_title.add_css_class('title-3')
        palette_title.set_xalign(0)
        right.append(palette_title)
        palette_scroll = Gtk.ScrolledWindow()
        palette_scroll.set_min_content_height(290)
        palette_scroll.set_vexpand(True)
        right.append(palette_scroll)
        self.palette = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        palette_scroll.set_child(self.palette)
        hint = Gtk.Label(label='Clique em uma fonte para selecioná-la; clique na tecla para associar.')
        hint.set_wrap(True)
        hint.set_xalign(0)
        hint.add_css_class('dim-label')
        right.append(hint)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        content.append(row)
        self.save_btn = Gtk.Button(label='Salvar layout no YAML')
        self.save_btn.add_css_class('suggested-action')
        self.save_btn.connect('clicked', self._save_clicked)
        row.append(self.save_btn)
        self.apply_btn = Gtk.Button(label='Aplicar ao dispositivo (IPC)')
        self.apply_btn.connect('clicked', lambda *_: self._work('apply'))
        row.append(self.apply_btn)
        self.state = Gtk.Label(label='')
        self.state.set_wrap(True)
        self.state.set_xalign(0)
        content.append(self.state)

        mixer_title = Gtk.Label(label='Mixer OBS — volumes individuais (0–100%)')
        mixer_title.add_css_class('title-2')
        mixer_title.set_xalign(0)
        content.append(mixer_title)
        mixer_hint = Gtk.Label(label='O mixer altera exclusivamente as fontes do OBS, não o volume do Ubuntu. '
                                    'O ajuste só é enviado ao clicar em Aplicar volume ou Mudo/Ativo.')
        mixer_hint.set_wrap(True)
        mixer_hint.set_xalign(0)
        content.append(mixer_hint)
        self.mixer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.append(self.mixer_box)
        self.audio_refresh_btn = Gtk.Button(label='Atualizar volumes e mute')
        self.audio_refresh_btn.connect('clicked', lambda *_: self._work('audio'))
        content.append(self.audio_refresh_btn)

        self.connect('close-request', self._close)
        self._draw_grid()
        self._work('discover')
        GLib.timeout_add_seconds(8, self._poll)

    def _close(self, *_):
        self._closed = True
        self._generation += 1
        return False

    def _busy(self, state: bool):
        self.busy = state
        for control in (self.refresh_btn, self.save_btn, self.apply_btn,
                        self.audio_refresh_btn, self.clear_btn, self.mode_combo):
            control.set_sensitive(not state)

    def _work(self, command: str, payload=None):
        if self.busy or self._closed:
            return
        self._busy(True)
        self.state.set_text('Executando ' + command + '…')
        self._generation += 1
        gen = self._generation

        def worker():
            try:
                response, error = backend(command, payload), None
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                response, error = None, str(exc)
            GLib.idle_add(self._done, gen, command, response, error)

        threading.Thread(target=worker, daemon=True, name='vision02-obs-visual').start()

    def _done(self, gen, command, result, error):
        if self._closed or gen != self._generation:
            return False
        self._busy(False)
        if error:
            self.state.set_text('Falha: ' + error)
            return False
        if command == 'discover':
            self.obs = result['obs']
            self._draw_palette()
            self.state.set_text(f"OBS conectado · {len(self.obs.get('scenes', []))} cenas disponíveis")
            self._work('inspect', {'profile': self.mode})
        elif command == 'live':
            self.obs = result['obs']
            if 'audio' in result:
                self.audio = result['audio']
            self._draw_palette()
            self._draw_grid()
            self.state.set_text('Estado das cenas atualizado.')
        elif command == 'inspect':
            self.profile = result
            self.entries = dict(result['entries'])
            self.dirty = False
            self.selected = 1
            self.palette_selected = None
            self._draw_grid()
            self._draw_palette()
            self.state.set_text(f'{self.mode}: {sum(v is not None for v in self.entries.values())} teclas configuradas')
            self._work('audio')
        elif command == 'audio':
            self.audio = result
            self._draw_mixer()
            self._draw_grid()
            self.state.set_text('Estados do áudio OBS atualizados.')
        elif command == 'save':
            self.dirty = False
            self.profile['version'] = result['version']
            self.state.set_text('Layout salvo com backup. Clique Aplicar ao dispositivo.')
            self._draw_grid()
        elif command == 'apply':
            self.state.set_text('Layout aplicado pelo IPC. Os LCDs serão atualizados.')
        elif command == 'audio_set':
            self.state.set_text('Alteração aplicada ao mixer OBS.')
            self._work('audio')
        return False

    def _names(self):
        if not self.obs:
            return []
        if self.mode == MODES[0]:
            return list(dict.fromkeys(self.obs.get('scenes', [])))
        return list(dict.fromkeys(row['name'] for row in self.obs.get('inputs', []) if isinstance(row, dict)))

    def _drag(self, widget, get_value):
        source = Gtk.DragSource()
        source.set_actions(Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        source.connect('prepare', lambda _s, _x, _y: Gdk.ContentProvider.new_for_value(get_value()))
        widget.add_controller(source)

    def _drop(self, widget, slot):
        target = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        target.connect('drop', lambda _t, value, _x, _y: self._dropped(slot, value))
        widget.add_controller(target)

    def _dropped(self, target: int, value):
        if not isinstance(value, str) or target > (14 if self.mode == MODES[0] else 12):
            return False
        if value.startswith('slot:'):
            try:
                source = int(value[5:])
            except ValueError:
                return False
            if source not in range(1, (14 if self.mode == MODES[0] else 12) + 1):
                return False
            self.entries[str(source)], self.entries[str(target)] = self.entries.get(str(target)), self.entries.get(str(source))
        elif value.startswith(self.mode + ':'):
            name = value[len(self.mode) + 1:]
            if name not in self._names():
                return False
            # A name belongs to just one key; previous assignment becomes empty.
            for key, old in list(self.entries.items()):
                if old == name:
                    self.entries[key] = None
            self.entries[str(target)] = name
        else:
            return False
        self.selected = target
        self.dirty = True
        GLib.idle_add(self._draw_grid)  # O alvo do drop não é destruído no callback GTK.
        self.state.set_text('Layout alterado (não salvo).')
        return True

    def _draw_grid(self):
        while child := self.grid.get_first_child():
            self.grid.remove(child)
        maximum = 14 if self.mode == MODES[0] else 12
        live_scene = (self.obs or {}).get('active_scene')
        muted = {row['name']: row.get('muted') for row in (self.audio or {}).get('inputs', [])}
        for slot in range(1, 16):
            name = self.entries.get(str(slot))
            if slot > maximum:
                if self.mode == MODES[0]:
                    label = '↩ Controle'
                else:
                    label = {13: '↗ Cenas', 14: '↩ Controle', 15: '⌂ Sistema'}[slot]
            else:
                status = ''
                if name and self.mode == MODES[0]:
                    status = '● ATIVA' if name == live_scene else '○ inativa'
                if name and self.mode == MODES[1]:
                    flag = muted.get(name)
                    status = 'MUDO' if flag is True else 'ATIVO' if flag is False else 'N/D'
                label = (name or '— livre —')[:24] + ('\n' + status if status else '')
            button = Gtk.Button(label=f'{slot:02d}\n{label}')
            button.set_size_request(130, 92)
            if slot == self.selected:
                button.add_css_class('suggested-action')
            if slot <= maximum:
                button.connect('clicked', lambda _b, index=slot: self._select_slot(index))
                self._drag(button, lambda index=slot: f'slot:{index}')
                self._drop(button, slot)
            else:
                button.set_sensitive(False)
            self.grid.attach(button, (slot - 1) % 5, (slot - 1) // 5, 1, 1)
        self.position_info.set_text(f'Tecla {self.selected:02d}: {self.entries.get(str(self.selected)) or "sem atribuição"}')

    def _select_slot(self, slot):
        self.selected = slot
        if self.palette_selected is not None:
            self._dropped(slot, self.mode + ':' + self.palette_selected)
        else:
            self._draw_grid()

    def _draw_palette(self):
        while child := self.palette.get_first_child():
            self.palette.remove(child)
        for name in self._names():
            row = Gtk.Button(label=('● ' if (self.obs or {}).get('active_scene') == name else '  ') + name)
            row.set_hexpand(True)
            row.connect('clicked', lambda _b, name=name: self._choose_name(name))
            self._drag(row, lambda name=name: self.mode + ':' + name)
            self.palette.append(row)

    def _choose_name(self, name):
        self.palette_selected = name
        self.state.set_text(f'{name} selecionada. Clique na tecla para associar ou arraste o nome.')

    def _clear_selected(self, *_):
        limit = 14 if self.mode == MODES[0] else 12
        if 1 <= self.selected <= limit:
            self.entries[str(self.selected)] = None
            self.dirty = True
            self._draw_grid()
            self.state.set_text('Tecla liberada (não salva).')

    def _change_mode(self, *_):
        if self._syncing_mode:
            return
        new_mode = MODES[self.mode_combo.get_selected()]
        if new_mode == self.mode:
            return
        if self.dirty:
            # No silent loss: revert selector and request explicit save/discard.
            self._syncing_mode = True
            try:
                self.mode_combo.set_selected(MODES.index(self.mode))
            finally:
                self._syncing_mode = False
            self.state.set_text('Salve as alterações ou use Recarregar para descartá-las antes de trocar o perfil.')
            return
        self.mode = new_mode
        self.palette_selected = None
        self._draw_palette()
        self._work('inspect', {'profile': self.mode})

    def _refresh(self, *_):
        if self.dirty:
            self.state.set_text('Salve o layout antes de recarregar. A atualização descartaria edições não salvas.')
            return
        self._work('discover')

    def _poll(self):
        if self._closed:
            return False
        if not self.busy:
            self._work('live')
        return True

    def _save_clicked(self, *_):
        if not self.profile or not self.dirty:
            self.state.set_text('Nenhuma alteração de layout para salvar.')
            return
        req = {'profile': self.mode, 'version': self.profile['version'], 'entries': dict(self.entries)}
        # Explicit action, with summary before writing the personal YAML.
        count = sum(item is not None for item in self.entries.values())
        dialog = Adw.MessageDialog.new(self, 'Salvar distribuição de teclas?',
                                       f'{count} associações em {self.mode}. As teclas desocupadas serão limpas. '
                                       'O YAML atual receberá backup; não será enviada nenhuma ação ao OBS.')
        dialog.add_response('cancel', 'Cancelar')
        dialog.add_response('save', 'Salvar layout')
        dialog.set_response_appearance('save', Adw.ResponseAppearance.SUGGESTED)
        dialog.connect('response', lambda _d, choice: self._work('save', req) if choice == 'save' else None)
        dialog.present()

    def _draw_mixer(self):
        while child := self.mixer_box.get_first_child():
            self.mixer_box.remove(child)
        if not self.audio:
            self.mixer_box.append(Gtk.Label(label='O mixer não foi consultado.'))
            return
        for item in self.audio.get('inputs', []):
            name = item['name']
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            box.append(Gtk.Label(label=name[:32]))
            volume = item.get('volume')
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
            scale.set_hexpand(True)
            scale.set_digits(0)
            scale.set_value(volume if volume is not None else 100)
            scale.set_sensitive(volume is not None)
            box.append(scale)
            submit = Gtk.Button(label='Aplicar volume')
            submit.set_sensitive(volume is not None)
            submit.connect('clicked', lambda _b, n=name, s=scale: self._work('audio_set', {'name': n, 'volume': int(s.get_value())}))
            box.append(submit)
            state = item.get('muted')
            mute = Gtk.Button(label='Ativar' if state else 'Silenciar')
            mute.set_sensitive(type(state) is bool)
            mute.connect('clicked', lambda _b, n=name, currently=state: self._work('audio_set', {'name': n, 'muted': not currently}))
            box.append(mute)
            self.mixer_box.append(box)


class OBSVisualApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='io.github.vision02.OBSVisual')
        self.connect('activate', self._activate)

    def _activate(self, *_):
        window = self.props.active_window
        if window is None:
            window = OBSVisualWindow(self)
        window.present()


def main():
    return OBSVisualApp().run(sys.argv)


if __name__ == '__main__':
    raise SystemExit(main())
