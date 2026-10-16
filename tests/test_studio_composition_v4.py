"""Regressão da composição v4 sem importar GTK nem acionar IPC/HID."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from vision02.studio_composition_v2 import CompositionHistory, FIELDS
from vision02.studio_composition_v4 import (
    coordinate_caption, guides_at_position, nudge_state,
)

SOURCE = (Path(__file__).resolve().parents[1] / 'apps' / 'vision02_studio.py').read_text()
TREE = ast.parse(SOURCE)
WINDOW = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'StudioWindow')


def method(name, namespace=None):
    node = next(n for n in WINDOW.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = dict(namespace or {})
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 '<studio-v4-method>', 'exec'), scope)
    return scope[name]


INITIAL = (0, 0, 100, 0, 0)


@pytest.mark.parametrize('target,direction,result', [
    ('image', 'left', (-1, 0, 100, 0, 0)),
    ('image', 'right', (1, 0, 100, 0, 0)),
    ('image', 'up', (0, -1, 100, 0, 0)),
    ('image', 'down', (0, 1, 100, 0, 0)),
    ('text', 'left', (0, 0, 100, -1, 0)),
    ('text', 'right', (0, 0, 100, 1, 0)),
    ('text', 'up', (0, 0, 100, 0, -1)),
    ('text', 'down', (0, 0, 100, 0, 1)),
])
def test_precise_nudge(target, direction, result):
    assert nudge_state(INITIAL, target, direction, 1, (-100, 100)) == result
    assert INITIAL == (0, 0, 100, 0, 0)


@pytest.mark.parametrize('target,bounds', [('image', (-100, 100)), ('text', (-40, 40))])
def test_step_five(target, bounds):
    state = nudge_state(INITIAL, target, 'right', 5, bounds)
    assert state[0 if target == 'image' else 3] == 5
    assert state[2] == 100


@pytest.mark.parametrize('target,bounds,start,desired', [
    ('image', (-100, 100), (99, -99, 120, 0, 0), (100, -100, 120, 0, 0)),
    ('text', (-40, 40), (9, 6, 75, 39, -39), (9, 6, 75, 40, -40)),
])
def test_bounds_and_scale_preserved(target, bounds, start, desired):
    result = nudge_state(start, target, 'right', 5, bounds)
    assert result[0 if target == 'image' else 3] == desired[0 if target == 'image' else 3]
    result = nudge_state(start, target, 'up', 5, bounds)
    assert result[1 if target == 'image' else 4] == desired[1 if target == 'image' else 4]
    assert result[2] == start[2]


@pytest.mark.parametrize('target,direction,step,bounds', [
    ('invalid', 'right', 1, (-40, 40)),
    ('image', 'north', 1, (-40, 40)),
    ('image', 'left', 0, (-40, 40)),
    ('image', 'left', 2, (-40, 40)),
    ('image', 'left', True, (-40, 40)),
    ('image', 'left', 1, (40, -40)),
    ('image', 'left', 1, (0.5, 40)),
])
def test_reject_bad_arguments(target, direction, step, bounds):
    with pytest.raises(ValueError):
        nudge_state(INITIAL, target, direction, step, bounds)


def test_reject_bad_state():
    with pytest.raises(ValueError):
        nudge_state((0, 0, 100, 0), 'image', 'left', 1, (-100, 100))


def test_coordinates_include_only_selected_element():
    state = (12, -9, 150, -3, 7)
    assert coordinate_caption(state, 'image') == 'Imagem: X=12 px, Y=-9 px, escala=150%'
    assert coordinate_caption(state, 'text') == 'Texto: X=-3 px, Y=7 px'


def test_guides_match_existing_anchors_without_snapping():
    assert guides_at_position((0, 5, 100, 8, -40), 'image') == (0, None)
    assert guides_at_position((17, 12, 100, 0, -40), 'text') == (0, -40)
    assert guides_at_position((25, -25, 50, 9, 10), 'image') == (25, -25)


def test_source_keeps_legacy_drag_logic_and_v3_selection():
    drag = ast.get_source_segment(SOURCE, next(n for n in WINDOW.body
                                if isinstance(n, ast.FunctionDef) and n.name == '_composition_drag_update'))
    assert 'clamp_drag(' in drag
    assert 'grid_coordinate(' in drag
    assert 'smart_snap(' in drag
    assert 'self.composition_align.get_active()' in drag
    assert '_composition_pick_target(x, y)' in SOURCE
    assert 'self.composition_prefer_image' in SOURCE


def test_ui_declares_nudge_and_alignment_controls():
    build = ast.get_source_segment(SOURCE, next(n for n in WINDOW.body
                                 if isinstance(n, ast.FunctionDef) and n.name == '_build_composition_canvas'))
    for expected in ('self.composition_align = Gtk.CheckButton(',
                     'self.composition_align.set_active(True)',
                     'self.composition_coordinates = _label(',
                     'self.composition_nudge_buttons.append(button)',
                     "Gtk.DropDown.new_from_strings(['1 px', '5 px'])",
                     "('left', '←')", "('up', '↑')", "('down', '↓')", "('right', '→')",
                     'Ctrl+Setas', 'Ctrl+Shift+Setas'):
        assert expected in build


class Spin:
    def __init__(self, value):
        self.value = value
    def get_value(self):
        return self.value
    def set_value(self, value):
        self.value = value


class Label:
    def __init__(self):
        self.text = ''
    def set_text(self, text):
        self.text = text


class Target:
    def __init__(self, selected):
        self.selected = selected
    def get_selected(self):
        return self.selected


def fake_window(*, target=0, initial=INITIAL, align=True, loaded=True, step_choice=0):
    obj = SimpleNamespace(
        _quick_loaded=object() if loaded else None,
        _busy=set(),
        _composition_history=CompositionHistory(),
        _composition_guide=(None, None),
        composition_target=Target(target),
        composition_align=SimpleNamespace(get_active=lambda: align),
        composition_nudge_step=Target(step_choice),
        style_numbers={key: Spin(val) for key, val in zip(FIELDS, initial)},
        composition_status=Label(),
        composition_coordinates=Label(),
        composition_canvas=SimpleNamespace(queue_draw=lambda: None),
    )
    def restore(state, message):
        for field, value in zip(FIELDS, state):
            obj.style_numbers[field].set_value(value)
        obj.composition_status.set_text(message)
    obj._composition_restore_state = restore
    return obj


NUDGE = method('_composition_nudge', {'nudge_state': nudge_state,
                                     'guides_at_position': guides_at_position,
                                     'coordinate_caption': coordinate_caption,
                                     'state_from_fields': lambda spins: tuple(int(spins[k].get_value()) for k in FIELDS),
                                     'INT_RANGES': {'offset_x': (-40, 40)},
                                     'IMAGE_RANGES': {'image_x': (-100, 100)}})


def test_gtk_nudge_updates_history_and_display_once():
    obj = fake_window(target=0)
    assert NUDGE(obj, 'left') is True
    assert obj.style_numbers['image_x'].get_value() == -1
    assert obj._composition_history.undo_stack == [INITIAL]
    assert obj.composition_status.text.startswith('Imagem: X=-1')
    assert obj._composition_guide == (None, 0)


def test_gtk_nudge_uses_dropdown_step_and_ignores_grid():
    obj = fake_window(target=1, step_choice=1)
    assert NUDGE(obj, 'down') is True
    assert obj.style_numbers['offset_y'].get_value() == 5
    assert obj._composition_history.undo_stack == [INITIAL]


def test_gtk_nudge_clamps_and_avoids_empty_history():
    obj = fake_window(target=1, initial=(0, 0, 100, 40, 0))
    assert NUDGE(obj, 'right', step=5) is False
    assert obj._composition_history.undo_stack == []
    assert 'Limite' in obj.composition_status.text


def test_gtk_nudge_disabled_before_load_and_during_save():
    obj = fake_window(loaded=False)
    assert NUDGE(obj, 'left') is False
    assert not obj._composition_history.undo_stack
    obj._quick_loaded = object()
    obj._busy.add('quick_save')
    assert NUDGE(obj, 'left') is False


def test_gtk_nudge_marks_guide_on_exact_anchor():
    obj = fake_window(target=0, initial=(1, 0, 100, 0, 0))
    assert NUDGE(obj, 'left') is True
    assert obj._composition_guide == (0, 0)
    obj = fake_window(target=0, initial=(1, 0, 100, 0, 0), align=False)
    NUDGE(obj, 'left')
    assert obj._composition_guide == (None, None)


def test_coordinates_are_updated_from_live_spins():
    obj = fake_window(target=1, initial=(10, 11, 130, 12, -8))
    method('_composition_update_coordinates', {
        'coordinate_caption': coordinate_caption,
        'state_from_fields': lambda spins: tuple(int(spins[k].get_value()) for k in FIELDS),
    })(obj)
    assert obj.composition_coordinates.text == 'Texto: X=12 px, Y=-8 px'


def test_alignment_toggle_is_local_redraw_only():
    obj = fake_window()
    obj._composition_guide = (0, 0)
    method('_composition_alignment_changed')(obj)
    assert obj._composition_guide == (None, None)
    assert not obj._composition_history.undo_stack


class MockGtk:
    class Entry: pass
    class TextView: pass
    class SpinButton: pass


class MockGdk:
    class ModifierType:
        CONTROL_MASK = 1
        SHIFT_MASK = 2
    KEY_Left, KEY_Right, KEY_Up, KEY_Down, KEY_z, KEY_Z = range(6)


KEY = method('_composition_key_pressed', {'Gdk': MockGdk, 'Gtk': MockGtk})


def fake_keys(*, page=3, focus=None, loaded=True, busy=False):
    obj = fake_window(loaded=loaded)
    if busy:
        obj._busy.add('quick_save')
    obj.stack = SimpleNamespace(get_visible_child_name=lambda: 'keys')
    obj.quick_tabs = SimpleNamespace(get_current_page=lambda: page)
    obj.get_focus = lambda: focus
    moves = []
    obj._composition_nudge = lambda direction, step: moves.append((direction, step)) or True
    obj._composition_undo_action = lambda: None
    obj._composition_redo_action = lambda: None
    return obj, moves


@pytest.mark.parametrize('key,expected', [(MockGdk.KEY_Left, 'left'),
                                          (MockGdk.KEY_Right, 'right'),
                                          (MockGdk.KEY_Up, 'up'),
                                          (MockGdk.KEY_Down, 'down')])
def test_ctrl_arrows_only_on_composition_tab(key, expected):
    obj, moves = fake_keys()
    assert KEY(obj, None, key, None, 1) is True
    assert moves == [(expected, 1)]
    obj, moves = fake_keys(page=2)
    assert KEY(obj, None, key, None, 1) is False
    assert not moves


def test_ctrl_shift_arrows_are_five_pixels():
    obj, moves = fake_keys()
    assert KEY(obj, None, MockGdk.KEY_Down, None, 3) is True
    assert moves == [('down', 5)]


@pytest.mark.parametrize('focus', [MockGtk.Entry(), MockGtk.TextView(), MockGtk.SpinButton()])
def test_shortcut_never_steals_editable_focus(focus):
    obj, moves = fake_keys(focus=focus)
    assert KEY(obj, None, MockGdk.KEY_Left, None, 1) is False
    assert not moves


def test_shortcut_does_not_steal_plain_arrows_or_unloaded_key():
    obj, moves = fake_keys()
    assert KEY(obj, None, MockGdk.KEY_Left, None, 0) is False
    obj, moves = fake_keys(loaded=False)
    assert KEY(obj, None, MockGdk.KEY_Left, None, 1) is False
    assert not moves


def test_shortcut_does_not_mutate_during_save():
    obj, moves = fake_keys(busy=True)
    # Nudge itself refuses to write, independently of shortcut dispatch.
    assert NUDGE(obj, 'right') is False
    assert obj._composition_history.undo_stack == []


def test_new_callbacks_never_apply_or_save():
    for name in ('_composition_nudge', '_composition_alignment_changed',
                 '_composition_update_coordinates'):
        snippet = ast.get_source_segment(SOURCE, next(n for n in WINDOW.body
                                         if isinstance(n, ast.FunctionDef) and n.name == name))
        assert 'self._quick_save(' not in snippet
        assert 'self._quick_apply(' not in snippet
        assert 'self._call(' not in snippet
        assert 'subprocess' not in snippet
