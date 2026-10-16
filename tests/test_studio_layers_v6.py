"""Regressões v6: camadas locais, centralização aproximada e bloqueios.

Executáveis sem sessão gráfica, serviços ou dispositivos conectados.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from vision02.studio_layers_v6 import center_layer_axis, is_layer_locked
from vision02.studio_composition_v2 import FIELDS, CompositionHistory, state_from_fields
from vision02.studio_composition_v4 import nudge_state, guides_at_position, coordinate_caption

SOURCE = (Path(__file__).resolve().parents[1] / 'apps/vision02_studio.py').read_text()
TREE = ast.parse(SOURCE)
WINDOW = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'StudioWindow')
STATE = (12, -18, 125, 22, -9)


def snippet(name):
    return ast.get_source_segment(SOURCE, next(
        n for n in WINDOW.body if isinstance(n, ast.FunctionDef) and n.name == name
    ))


def callback(name, namespace=None):
    node = next(n for n in WINDOW.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = dict(namespace or {})
    exec(compile(ast.fix_missing_locations(ast.Module([node], [])), '<v6-callback>', 'exec'), scope)
    return scope[name]


@pytest.mark.parametrize('layer,locks,result', [
    ('image', {}, False), ('image', {'image': False}, False),
    ('image', {'image': True}, True), ('text', {'text': True}, True),
    ('text', {'text': False}, False), ('image', {'image': 1}, False),
    ('image', {'image': 'true'}, False),
])
def test_lock_state_requires_explicit_boolean_true(layer, locks, result):
    assert is_layer_locked(locks, layer) is result


@pytest.mark.parametrize('layer', ['background', '', 'Image', None])
def test_lock_invalid_layer_fails_closed(layer):
    with pytest.raises(ValueError):
        is_layer_locked({}, layer)


@pytest.mark.parametrize('layer,axis,field', [
    ('image', 'x', 0), ('image', 'y', 1),
    ('text', 'x', 3), ('text', 'y', 4),
])
def test_center_only_updates_requested_coordinate(layer, axis, field):
    output = center_layer_axis(STATE, layer, axis,
                               (-100, 100) if layer == 'image' else (-40, 40),
                               text='A', font_size=16)
    assert output[field] == 0
    assert all(output[i] == STATE[i] for i in range(len(STATE)) if i != field)


@pytest.mark.parametrize('horizontal,expected_sign', [('left', 1), ('right', -1), ('center', 0)])
def test_horizontal_text_uses_alignment_for_centering(horizontal, expected_sign):
    output = center_layer_axis(STATE, 'text', 'x', (-40, 40), text='OK', font_size=16,
                               horizontal=horizontal)
    assert (output[3] > 0) - (output[3] < 0) == expected_sign
    assert output[4] == STATE[4]


@pytest.mark.parametrize('vertical,expected_sign', [('top', 1), ('bottom', -1), ('center', 0)])
def test_vertical_text_uses_alignment_for_centering(vertical, expected_sign):
    output = center_layer_axis(STATE, 'text', 'y', (-40, 40), text='OK', font_size=16,
                               vertical=vertical)
    assert (output[4] > 0) - (output[4] < 0) == expected_sign
    assert output[3] == STATE[3]


@pytest.mark.parametrize('bounds,expected', [((-100, -5), -5), ((3, 100), 3), ((0, 0), 0)])
def test_center_image_clamps_to_widget_bounds(bounds, expected):
    assert center_layer_axis(STATE, 'image', 'x', bounds)[0] == expected


@pytest.mark.parametrize('invalid', [
    ((1, 2), 'image', 'x', (-100, 100)),
    ((1, 2, 3, 4, True), 'image', 'x', (-100, 100)),
    (STATE, 'other', 'x', (-40, 40)),
    (STATE, 'text', 'z', (-40, 40)),
    (STATE, 'image', 'x', (5, -5)),
    (STATE, 'image', 'x', (0, True)),
])
def test_center_rejects_malformed_state(invalid):
    with pytest.raises(ValueError):
        center_layer_axis(*invalid)


def test_center_rejects_missing_text_and_invalid_alignment():
    with pytest.raises(ValueError):
        center_layer_axis(STATE, 'text', 'x', (-40, 40), text='   ')
    with pytest.raises(ValueError):
        center_layer_axis(STATE, 'text', 'x', (-40, 40), text='ABC', horizontal='invalid')


class Target:
    def __init__(self, selected): self.selected = selected
    def get_selected(self): return self.selected


class Spin:
    def __init__(self, value): self.value = value
    def get_value(self): return self.value
    def set_value(self, value): self.value = value
    def set_sensitive(self, value): self.sensitive = value


class Label:
    def __init__(self): self.text = ''
    def set_text(self, text): self.text = text


class Check:
    def __init__(self, value=False): self.active = value
    def get_active(self): return self.active
    def set_active(self, value): self.active = value


class Widget:
    def set_sensitive(self, value): self.sensitive = value
    def set_visible(self, value): self.visible = value


def fake_window(*, layer='image', locked=False, loaded=True, busy=False):
    obj = SimpleNamespace(
        _quick_loaded={} if loaded else None,
        _busy={'quick_save'} if busy else set(),
        _composition_v6_locked={'image': locked if layer == 'image' else False,
                                'text': locked if layer == 'text' else False},
        _composition_v6_outlines={'image': True, 'text': True},
        _composition_history=CompositionHistory(),
        composition_target=Target(0 if layer == 'image' else 1),
        composition_status=Label(),
        composition_canvas=SimpleNamespace(queue_draw=lambda: None),
        composition_nudge_step=Target(0),
        composition_align=Check(),
        style_numbers={**{key: Spin(value) for key, value in zip(FIELDS, STATE)},
                       'font_size': Spin(16)},
        quick_visual_text=SimpleNamespace(get_text=lambda: 'Oi'),
        quick_label=SimpleNamespace(get_text=lambda: 'Rótulo'),
        style_choices={'horizontal': Target(1), 'vertical': Target(1)},
        style_enabled=Check(),
        composition_undo=Widget(), composition_redo=Widget(),
        composition_reset=Widget(), composition_resize_handle=Widget(),
        composition_v6_center_buttons={'x': Widget(), 'y': Widget()},
        _composition_before_drag=None,
        _composition_drag_kind='move',
    )
    obj._composition_available_layers = lambda: ('image', 'text')
    obj._composition_v6_is_locked = lambda candidate: is_layer_locked(obj._composition_v6_locked, candidate)
    def restore(state, message):
        for field, value in zip(FIELDS, state): obj.style_numbers[field].set_value(value)
        obj.composition_status.set_text(message)
    obj._composition_restore_state = restore
    return obj


CENTER = callback('_composition_v6_center', {
    'state_from_fields': state_from_fields,
    'center_layer_axis': center_layer_axis,
    'coordinate_caption': coordinate_caption,
    'INT_RANGES': {'offset_x': (-40, 40), 'offset_y': (-40, 40)},
    'IMAGE_RANGES': {'image_x': (-100, 100), 'image_y': (-100, 100)},
    'CHOICES': {'horizontal': ('left', 'center', 'right'),
                'vertical': ('top', 'center', 'bottom')},
})


@pytest.mark.parametrize('layer,axis,index', [
    ('image', 'x', 0), ('image', 'y', 1),
    ('text', 'x', 3), ('text', 'y', 4),
])
def test_center_callback_records_once_and_only_updates_axis(layer, axis, index):
    obj = fake_window(layer=layer)
    assert CENTER(obj, axis) is True
    assert obj.style_numbers[FIELDS[index]].value == 0
    assert obj._composition_history.undo_stack == [STATE]
    assert not hasattr(obj, '_quick_dirty')


@pytest.mark.parametrize('layer', ['image', 'text'])
def test_center_blocked_layer_does_not_record(layer):
    obj = fake_window(layer=layer, locked=True)
    assert CENTER(obj, 'x') is False
    assert state_from_fields(obj.style_numbers) == STATE
    assert not obj._composition_history.undo_stack


@pytest.mark.parametrize('loaded,busy', [(False, False), (True, True)])
def test_center_requires_loaded_key_and_no_save(loaded, busy):
    obj = fake_window(loaded=loaded, busy=busy)
    assert CENTER(obj, 'x') is False
    assert not obj._composition_history.undo_stack


def test_center_noop_does_not_create_undo_entry():
    obj = fake_window()
    obj.style_numbers['image_x'].set_value(0)
    assert CENTER(obj, 'x') is False
    assert not obj._composition_history.undo_stack


@pytest.mark.parametrize('layer', ['image', 'text'])
def test_lock_blocks_nudge(layer):
    nudge = callback('_composition_nudge', {
        'state_from_fields': state_from_fields, 'nudge_state': nudge_state,
        'coordinate_caption': coordinate_caption, 'guides_at_position': guides_at_position,
        'INT_RANGES': {'offset_x': (-40, 40)},
        'IMAGE_RANGES': {'image_x': (-100, 100)},
    })
    obj = fake_window(layer=layer, locked=True)
    assert nudge(obj, 'left', step=1) is False
    assert state_from_fields(obj.style_numbers) == STATE
    assert not obj._composition_history.undo_stack


@pytest.mark.parametrize('layer', ['image', 'text'])
def test_lock_blocks_reset(layer):
    reset = callback('_composition_reset_action', {
        'state_from_fields': state_from_fields,
    })
    obj = fake_window(layer=layer, locked=True)
    reset(obj)
    assert state_from_fields(obj.style_numbers) == STATE
    assert not obj._composition_history.undo_stack


def test_lock_controls_hide_handle_and_disable_buttons():
    update = callback('_composition_update_buttons')
    obj = fake_window(locked=True)
    update(obj)
    assert obj.composition_resize_handle.visible is False
    assert obj.composition_reset.sensitive is False


def test_unlock_image_restores_handle():
    update = callback('_composition_update_buttons')
    obj = fake_window()
    update(obj)
    assert obj.composition_resize_handle.visible is True
    assert obj.composition_reset.sensitive is True


def test_lock_toggle_is_editor_only_and_requests_redraw():
    change = callback('_composition_v6_lock_changed')
    obj = fake_window()
    calls = []
    obj._composition_update_buttons = lambda: calls.append('buttons')
    obj.composition_canvas.queue_draw = lambda: calls.append('draw')
    change(obj, Check(True), 'image')
    assert obj._composition_v6_locked['image'] is True
    assert calls == ['buttons', 'draw']
    assert not obj._composition_history.undo_stack


def test_outline_toggle_is_local_only():
    change = callback('_composition_v6_outline_changed')
    obj = fake_window()
    calls = []
    obj.composition_canvas.queue_draw = lambda: calls.append('draw')
    change(obj, Check(False), 'text')
    assert obj._composition_v6_outlines == {'image': True, 'text': False}
    assert calls == ['draw']
    assert not obj._composition_history.undo_stack


def test_switching_key_resets_both_layers():
    reset = callback('_composition_v6_reset_local')
    obj = fake_window(locked=True)
    obj._composition_v6_outlines['text'] = False
    obj.composition_v6_lock_checks = {'image': Check(True), 'text': Check(False)}
    obj.composition_v6_outline_checks = {'image': Check(True), 'text': Check(False)}
    obj._composition_update_buttons = lambda: None
    reset(obj)
    assert obj._composition_v6_locked == {'image': False, 'text': False}
    assert obj._composition_v6_outlines == {'image': True, 'text': True}
    assert all(not item.get_active() for item in obj.composition_v6_lock_checks.values())
    assert all(item.get_active() for item in obj.composition_v6_outline_checks.values())


@pytest.mark.parametrize('needle', [
    'self._composition_v6_lock_changed', 'self._composition_v6_outline_changed',
    'self.composition_v6_center_buttons', 'Centralizar X', 'Centralizar Y',
    'Mostrar moldura', 'Bloquear ',
])
def test_ui_exposes_v6_controls(needle):
    assert needle in snippet('_build_composition_canvas')


@pytest.mark.parametrize('method,keyword', [
    ('_composition_drag_begin', '_composition_v6_is_locked'),
    ('_composition_drag_update', '_composition_v6_is_locked'),
    ('_composition_resize_drag_begin', '_composition_v6_is_locked'),
    ('_composition_reset_action', '_composition_v6_is_locked'),
    ('_composition_nudge', '_composition_v6_is_locked'),
    ('_composition_update_buttons', 'locked'),
    ('_quick_load', '_composition_v6_reset_local'),
])
def test_ui_blocks_transformations_and_resets_on_switch(method, keyword):
    assert keyword in snippet(method)


def test_local_controls_do_not_write_yaml_or_call_ipc():
    for method in ('_composition_v6_lock_changed', '_composition_v6_outline_changed',
                   '_composition_v6_reset_local', '_composition_v6_center'):
        code = snippet(method)
        assert "_call(" not in code
        assert 'quick_save' not in code or "'quick_save' in self._busy" in code
        assert 'yaml' not in code.lower() or 'YAML' in code  # only documentation comment

@pytest.mark.parametrize('layer', ['image', 'text'])
def test_drag_begin_on_locked_layer_does_not_enable_style(layer):
    begin = callback('_composition_drag_begin', {'state_from_fields': state_from_fields})
    obj = fake_window(layer=layer, locked=True)
    obj._composition_drag_did_move = False
    begin(obj)
    assert obj._composition_before_drag is None
    assert obj.style_enabled.get_active() is False
    assert 'bloqueada' in obj.composition_status.text


def test_locked_layer_cannot_continue_started_drag():
    update = callback('_composition_drag_update')
    obj = fake_window(locked=True)
    obj._composition_before_drag = STATE
    obj.style_enabled.set_active(True)
    update(obj, None, 100, 50)
    assert state_from_fields(obj.style_numbers) == STATE


def test_locked_image_cannot_start_handle_drag():
    begin = callback('_composition_resize_drag_begin')
    obj = fake_window(locked=True)
    obj._composition_drag_begin = lambda: pytest.fail('gesture cannot start while locked')
    begin(obj, SimpleNamespace(), 0, 0)
    assert obj._composition_before_drag is None


def test_unlocked_text_not_blocked_by_locked_image():
    nudge = callback('_composition_nudge', {
        'state_from_fields': state_from_fields, 'nudge_state': nudge_state,
        'coordinate_caption': coordinate_caption, 'guides_at_position': guides_at_position,
        'INT_RANGES': {'offset_x': (-40, 40)},
        'IMAGE_RANGES': {'image_x': (-100, 100)},
    })
    obj = fake_window(layer='text')
    obj._composition_v6_locked['image'] = True
    obj._composition_guide = (None, None)
    assert nudge(obj, 'left', step=1) is True
    assert obj.style_numbers['offset_x'].value == STATE[3] - 1


def test_layer_status_indicates_lock_and_hidden_outline():
    panel = callback('_composition_update_layer_panel', {
        'is_layer_locked': is_layer_locked,
        'hit_layer_candidates': lambda *args: (),
    })
    obj = fake_window(locked=True)
    obj._composition_v6_outlines['text'] = False
    obj.composition_layer_buttons = {'image': Widget(), 'text': Widget()}
    for button in obj.composition_layer_buttons.values():
        button.add_css_class = lambda _name: None
        button.remove_css_class = lambda _name: None
    obj.composition_layers_status = Label()
    obj.composition_cycle_overlap = Widget()
    obj.composition_v6_lock_checks = {'image': Widget(), 'text': Widget()}
    obj.composition_v6_outline_checks = {'image': Widget(), 'text': Widget()}
    obj._composition_last_overlap = None
    panel(obj)
    assert 'Imagem: bloqueada' in obj.composition_layers_status.text
    assert 'Texto: moldura oculta' in obj.composition_layers_status.text
    assert obj.composition_v6_center_buttons['x'].sensitive is False


def test_lock_disables_only_its_geometry_fields():
    update = callback('_composition_update_buttons')
    obj = fake_window(locked=True)
    update(obj)
    for name in ('image_x', 'image_y', 'image_scale'):
        assert obj.style_numbers[name].sensitive is False
    for name in ('offset_x', 'offset_y'):
        assert obj.style_numbers[name].sensitive is True
    obj._composition_v6_locked['image'] = False
    obj._composition_v6_locked['text'] = True
    update(obj)
    for name in ('image_x', 'image_y', 'image_scale'):
        assert obj.style_numbers[name].sensitive is True
    for name in ('offset_x', 'offset_y'):
        assert obj.style_numbers[name].sensitive is False
