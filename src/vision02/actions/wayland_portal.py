"""GNOME Wayland hotkeys via XDG RemoteDesktop portal (user consent required).

One D-Bus connection/session is reused for the controller lifetime. The D-Bus
asyncio loop lives on its own thread; no root privileges or uinput access.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
import re
import threading
import uuid

DEST = "org.freedesktop.portal.Desktop"
OBJECT = "/org/freedesktop/portal/desktop"
REMOTE = "org.freedesktop.portal.RemoteDesktop"
REQUEST = "org.freedesktop.portal.Request"
KEYBOARD = 1

_KEYSYMS = {
    "ctrl": 0xFFE3, "control": 0xFFE3, "control_l": 0xFFE3,
    "shift": 0xFFE1, "shift_l": 0xFFE1,
    "alt": 0xFFE9, "alt_l": 0xFFE9,
    "super": 0xFFEB, "super_l": 0xFFEB, "meta": 0xFFEB,
    "enter": 0xFF0D, "return": 0xFF0D,
    "tab": 0xFF09, "esc": 0xFF1B, "escape": 0xFF1B,
    "backspace": 0xFF08, "space": 0x0020,
    "delete": 0xFFFF, "insert": 0xFF63,
    "left": 0xFF51, "up": 0xFF52, "right": 0xFF53,
    "down": 0xFF54, "home": 0xFF50, "end": 0xFF57,
    "pageup": 0xFF55, "pagedown": 0xFF56,
}


class PortalHotkeyError(RuntimeError):
    """GNOME portal refused or could not deliver a shortcut."""


def keys_to_keysyms(keys: tuple[str, ...]) -> tuple[int, ...]:
    """Resolve a bounded subset of X11 keysyms; never evaluate strings."""
    if not 1 <= len(keys) <= 5:
        raise PortalHotkeyError("Atalho deve conter entre 1 e 5 teclas")
    resolved = []
    for raw in keys:
        if not isinstance(raw, str) or not re.fullmatch(r"[A-Za-z0-9_]+", raw):
            raise PortalHotkeyError(f"Nome de tecla inválido: {raw!r}")
        key = raw.lower()
        if key in _KEYSYMS:
            resolved.append(_KEYSYMS[key])
        elif len(key) == 1 and key.isascii() and key.isalnum():
            resolved.append(ord(key))
        elif re.fullmatch(r"f(?:[1-9]|1[0-2])", key):
            resolved.append(0xFFBE + int(key[1:]) - 1)
        else:
            raise PortalHotkeyError(f"Tecla não suportada no GNOME: {raw!r}")
    if len(set(resolved)) != len(resolved):
        raise PortalHotkeyError("Atalho contém teclas duplicadas")
    return tuple(resolved)


class WaylandPortalKeyboard:
    """Consent-aware, persistent keyboard session with synchronous send API."""

    def __init__(self):
        self._guard = threading.Lock()
        self._loop = None
        self._thread = None
        self._bus = None
        self._session = None
        self._sequence_lock = None
        self._closed = False

    def _ensure_loop(self):
        with self._guard:
            if self._closed:
                raise PortalHotkeyError("Backend de atalhos já encerrado")
            if self._loop is not None:
                return self._loop
            loop = asyncio.new_event_loop()
            ready = threading.Event()

            def runner():
                asyncio.set_event_loop(loop)
                ready.set()
                try:
                    loop.run_forever()
                finally:
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    loop.close()

            thread = threading.Thread(
                target=runner, name="vision02-wayland-portal", daemon=True
            )
            thread.start()
            if not ready.wait(timeout=5):
                raise PortalHotkeyError("Não foi possível iniciar thread D-Bus")
            self._loop = loop
            self._thread = thread
            return loop

    def send(self, keys: tuple[str, ...]) -> None:
        syms = keys_to_keysyms(keys)
        loop = self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(self._send(syms), loop)
        try:
            fut.result(timeout=180)  # Start can wait for explicit GNOME consent.
        except FutureTimeout as exc:
            fut.cancel()
            raise PortalHotkeyError("Timeout ao solicitar controle de teclado") from exc
        except PortalHotkeyError:
            raise
        except Exception as exc:
            raise PortalHotkeyError(f"Falha no atalho GNOME Wayland: {exc}") from exc

    async def _call(self, *, member, signature="", body=None, path=OBJECT, interface=REMOTE):
        from dbus_next import Message, MessageType

        msg = Message(
            destination=DEST, path=path, interface=interface,
            member=member, signature=signature, body=body if body is not None else [],
        )
        reply = await asyncio.wait_for(self._bus.call(msg), timeout=25)
        if reply is None or reply.message_type == MessageType.ERROR:
            raise PortalHotkeyError(
                f"D-Bus {member}: {getattr(reply, 'error_name', 'sem resposta')}: "
                f"{getattr(reply, 'body', [])}"
            )
        return reply.body

    async def _add_match(self, rule, *, remove=False):
        from dbus_next import Message, MessageType
        reply = await self._bus.call(Message(
            destination="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus",
            member="RemoveMatch" if remove else "AddMatch",
            signature="s", body=[rule],
        ))
        if not remove and (reply is None or reply.message_type == MessageType.ERROR):
            raise PortalHotkeyError("Não foi possível assinar resposta do portal")

    async def _request(self, member, signature, body, timeout=120):
        from dbus_next import MessageType, Variant

        token = "v02_" + uuid.uuid4().hex
        sender = self._bus.unique_name.lstrip(":").replace(".", "_")
        path = f"{OBJECT}/request/{sender}/{token}"
        options = dict(body[-1])
        options["handle_token"] = Variant("s", token)
        body = [*body[:-1], options]
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        rule = f"type='signal',interface='{REQUEST}',member='Response',path='{path}'"

        def handler(msg):
            if (msg.message_type == MessageType.SIGNAL and msg.path == path
                    and msg.interface == REQUEST and msg.member == "Response"
                    and not future.done()):
                future.set_result(msg.body)
            return False

        self._bus.add_message_handler(handler)
        subscribed = False
        try:
            await self._add_match(rule)
            subscribed = True
            result = await self._call(member=member, signature=signature, body=body)
            if result[0] != path:
                raise PortalHotkeyError(f"Caminho de resposta inesperado em {member}")
            code, values = await asyncio.wait_for(future, timeout=timeout)
            if code != 0:
                raise PortalHotkeyError(
                    f"{member}: autorização cancelada ou negada (código {code})"
                )
            return {key: value.value for key, value in values.items()}
        finally:
            self._bus.remove_message_handler(handler)
            if subscribed:
                try:
                    await asyncio.wait_for(self._add_match(rule, remove=True), timeout=2)
                except Exception:
                    pass

    async def _open_session(self):
        from dbus_next import Variant
        from dbus_next.aio import MessageBus

        self._bus = await MessageBus().connect()
        try:
            props = await self._call(
                member="Get", interface="org.freedesktop.DBus.Properties",
                signature="ss", body=[REMOTE, "AvailableDeviceTypes"],
            )
            if not props[0].value & KEYBOARD:
                raise PortalHotkeyError("Portal não oferece controle de teclado")

            created = await self._request(
                "CreateSession", "a{sv}",
                [{"session_handle_token": Variant("s", "v02_" + uuid.uuid4().hex)}],
            )
            self._session = created.get("session_handle")
            if not isinstance(self._session, str) or not self._session.startswith("/"):
                raise PortalHotkeyError("Sessão retornada pelo portal é inválida")
            await self._request(
                "SelectDevices", "oa{sv}",
                [self._session, {"types": Variant("u", KEYBOARD),
                                 "persist_mode": Variant("u", 0)}],
            )
            print("[Vision02] GNOME: autorize o controle de teclado quando solicitado.", flush=True)
            started = await self._request(
                "Start", "osa{sv}", [self._session, "", {}], timeout=120,
            )
            if not started.get("devices", 0) & KEYBOARD:
                raise PortalHotkeyError("O GNOME não concedeu controle de teclado")
            print("[Vision02] Teclado autorizado. Selecione a janela de destino (4 s).", flush=True)
            await asyncio.sleep(4)
        except BaseException:
            await self._cleanup()
            raise

    async def _send(self, syms):
        if self._sequence_lock is None:
            self._sequence_lock = asyncio.Lock()
        async with self._sequence_lock:
            if self._session is None:
                await self._open_session()
            pressed = []
            failure = None
            try:
                for sym in syms:
                    pressed.append(sym)  # Even a failed reply may have delivered the key.
                    await self._call(
                        member="NotifyKeyboardKeysym", signature="oa{sv}iu",
                        body=[self._session, {}, sym, 1],
                    )
                    await asyncio.sleep(0.03)
            except BaseException as exc:
                failure = exc
            finally:
                for sym in reversed(pressed):
                    try:
                        await self._call(
                            member="NotifyKeyboardKeysym", signature="oa{sv}iu",
                            body=[self._session, {}, sym, 0],
                        )
                    except Exception as exc:
                        if failure is None:
                            failure = exc
            if failure is not None:
                raise failure

    async def _cleanup(self):
        session, bus = self._session, self._bus
        self._session = None
        if bus is None:
            return
        try:
            if session:
                try:
                    await asyncio.wait_for(self._call(
                        member="Close", path=session,
                        interface="org.freedesktop.portal.Session"
                    ), timeout=3)
                except Exception:
                    pass
        finally:
            self._bus = None
            bus.disconnect()

    def close(self):
        with self._guard:
            if self._closed:
                return
            self._closed = True
            loop, thread = self._loop, self._thread
        if loop is None:
            return
        task = asyncio.run_coroutine_threadsafe(self._cleanup(), loop)
        try:
            task.result(timeout=5)
        except FutureTimeout:
            task.cancel()
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)
