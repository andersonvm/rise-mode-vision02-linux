"""Unit tests for portal hotkeys; no real D-Bus calls, keyboard, or USB."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from vision02.actions.wayland_portal import (
    PortalHotkeyError, WaylandPortalKeyboard, keys_to_keysyms,
)
from vision02.actions.executor import close_wayland_keyboard, execute_action
from vision02.profiles.models import Action


def test_keysyms_ctrl_shift_t():
    assert keys_to_keysyms(('ctrl', 'shift', 't')) == (0xFFE3, 0xFFE1, ord('t'))


@pytest.mark.parametrize('keys, expected', [
    (('ctrl', 'f5'), (0xFFE3, 0xFFC2)),
    (('alt', 'tab'), (0xFFE9, 0xFF09)),
    (('super', 'left'), (0xFFEB, 0xFF51)),
    (('enter',), (0xFF0D,)),
])
def test_keysyms_supported(keys, expected):
    assert keys_to_keysyms(keys) == expected


@pytest.mark.parametrize('keys', [
    (), ('ctrl', 'ctrl'), ('ctrl', 'unknown'), ('bad;cmd',), ('f13',),
    ('ctrl', 'shift', 'alt', 'super', 'a', 'b'),
])
def test_keysyms_reject_invalid(keys):
    with pytest.raises(PortalHotkeyError):
        keys_to_keysyms(keys)


def test_press_release_are_ordered_and_session_reused():
    async def scenario():
        client = WaylandPortalKeyboard()
        client._bus = object()
        client._session = '/session/test'
        client._call = AsyncMock(return_value=[])
        client._open_session = AsyncMock()
        await client._send((0xFFE3, 0xFFE1, ord('t')))
        await client._send((0xFFE3, ord('a')))
        assert client._open_session.await_count == 0
        return [(call.kwargs['member'], call.kwargs['body'][-2:]) for call in client._call.await_args_list]
    assert asyncio.run(scenario()) == [
        ('NotifyKeyboardKeysym', [0xFFE3, 1]),
        ('NotifyKeyboardKeysym', [0xFFE1, 1]),
        ('NotifyKeyboardKeysym', [ord('t'), 1]),
        ('NotifyKeyboardKeysym', [ord('t'), 0]),
        ('NotifyKeyboardKeysym', [0xFFE1, 0]),
        ('NotifyKeyboardKeysym', [0xFFE3, 0]),
        ('NotifyKeyboardKeysym', [0xFFE3, 1]),
        ('NotifyKeyboardKeysym', [ord('a'), 1]),
        ('NotifyKeyboardKeysym', [ord('a'), 0]),
        ('NotifyKeyboardKeysym', [0xFFE3, 0]),
    ]


def test_release_modifiers_even_when_press_fails():
    async def scenario():
        client = WaylandPortalKeyboard()
        client._session = '/session/test'
        calls = []

        async def fake_call(**kwargs):
            sym, state = kwargs['body'][-2:]
            calls.append((sym, state))
            if sym == ord('t') and state == 1:
                raise PortalHotkeyError('simulado')
            return []
        client._call = fake_call
        with pytest.raises(PortalHotkeyError, match='simulado'):
            await client._send((0xFFE3, 0xFFE1, ord('t')))
        return calls
    assert asyncio.run(scenario()) == [
        (0xFFE3, 1), (0xFFE1, 1), (ord('t'), 1),
        (ord('t'), 0), (0xFFE1, 0), (0xFFE3, 0),
    ]


def test_first_send_opens_one_session():
    async def scenario():
        client = WaylandPortalKeyboard()
        calls = []

        async def fake_open():
            calls.append('open')
            client._session = '/session/test'
        client._open_session = fake_open
        client._call = AsyncMock(return_value=[])
        await client._send((ord('t'),))
        await client._send((ord('t'),))
        return calls
    assert asyncio.run(scenario()) == ['open']


def test_wayland_portal_failure_is_wrapped(monkeypatch):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'wayland')
    with patch('vision02.actions.executor._get_wayland_keyboard') as portal:
        portal.return_value.send.side_effect = PortalHotkeyError('permissão negada')
        from vision02.actions.executor import ActionExecutionError
        with pytest.raises(ActionExecutionError, match='permissão negada'):
            execute_action(Action(type='hotkey', keys=('ctrl', 't')))


def test_backend_close_is_idempotent_and_does_not_connect():
    client = WaylandPortalKeyboard()
    client.close()
    client.close()
    with pytest.raises(PortalHotkeyError, match='encerrado'):
        client.send(('ctrl', 't'))


def test_global_backend_close_is_idempotent():
    close_wayland_keyboard()
    close_wayland_keyboard()


def test_cli_cleanup_on_keyboard_interrupt(tmp_path):
    from vision02.cli import main
    profile = tmp_path / 'test.yaml'
    profile.write_text('version: 1\nname: Teste\nkeys: {}\n', encoding='utf-8')
    from unittest.mock import MagicMock
    device = MagicMock()
    device.read_event.side_effect = KeyboardInterrupt()
    with (
        patch('vision02.cli.Vision02') as d,
        patch('vision02.cli.Vision02Controller') as controller,
        patch('vision02.cli.close_wayland_keyboard') as close,
    ):
        d.return_value.__enter__.return_value = device
        main(['profile', 'run', str(profile)])
    controller.return_value.stop.assert_called_once_with()
    close.assert_called_once_with()
