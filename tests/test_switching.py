"""Testes de transição de perfis sem hardware USB."""

from unittest.mock import Mock

import pytest
from PIL import Image

from vision02.controller import Vision02Controller
from vision02.profiles.models import Action, KeyConfig, Profile
from vision02.profiles.manager import ProfileManager
from vision02.switching import ProfileSwitcher


def make_profile(name, command):
    return Profile(
        name=name,
        keys={
            1: KeyConfig(
                key_id=1,
                label=name,
                action=Action(
                    type="command",
                    argv=(command,),
                ),
            ),
        },
    )


@pytest.fixture
def environment():
    first = make_profile("Desenvolvimento", "first")
    second = make_profile("Observabilidade", "second")

    manager = ProfileManager()
    manager.register(first)
    manager.register(second)

    executed = []
    controller = Vision02Controller(
        first,
        executor=executed.append,
    )
    controller.start()

    device = Mock()
    drain = Mock()

    switcher = ProfileSwitcher(
        manager,
        controller,
        device,
        drain_events=drain,
    )

    yield manager, controller, device, drain, switcher, executed

    controller.stop()


def test_switch_updates_all_displays(environment):
    manager, controller, device, drain, switcher, _ = environment

    assert switcher.switch("Observabilidade")

    assert manager.active_name == "Observabilidade"
    assert controller.profile.name == "Observabilidade"

    assert device.set_image.call_count == 15
    assert {
        call.args[0]
        for call in device.set_image.call_args_list
    } == set(range(1, 16))

    assert all(
        call.kwargs == {"skip_unchanged": True}
        for call in device.set_image.call_args_list
    )

    drain.assert_called_once()


def test_switch_changes_executed_actions(environment):
    manager, controller, _, _, switcher, executed = environment

    assert controller.handle_event(1, True)
    assert controller.wait_idle(timeout=2)

    switcher.switch("Observabilidade")

    assert controller.handle_event(1, True)
    assert controller.wait_idle(timeout=2)

    assert [action.argv for action in executed] == [
        ("first",),
        ("second",),
    ]


def test_switch_to_active_profile_does_nothing(environment):
    manager, controller, device, drain, switcher, _ = environment

    assert not switcher.switch("Desenvolvimento")

    assert manager.active_name == "Desenvolvimento"
    assert device.set_image.call_count == 0
    drain.assert_not_called()


def test_unknown_target_preserves_active_profile(environment):
    manager, controller, device, drain, switcher, _ = environment

    with pytest.raises(Exception, match="não encontrado"):
        switcher.switch("Inexistente")

    assert manager.active_name == "Desenvolvimento"
    assert controller.profile.name == "Desenvolvimento"
    assert controller.handle_event(1, True)

    device.set_image.assert_not_called()
    drain.assert_not_called()


def test_usb_failure_keeps_controller_suspended(environment):
    manager, controller, device, drain, switcher, executed = environment

    device.set_image.side_effect = OSError("Falha USB simulada")

    with pytest.raises(OSError, match="Falha USB"):
        switcher.switch("Observabilidade")

    assert manager.active_name == "Desenvolvimento"
    assert controller.profile.name == "Desenvolvimento"

    # Não executar ações enquanto a tela possa estar inconsistente.
    assert not controller.handle_event(1, True)

    drain.assert_not_called()
    assert executed == []


def test_drain_failure_keeps_controller_suspended(environment):
    manager, controller, device, drain, switcher, _ = environment

    drain.side_effect = RuntimeError("Fila HID não foi esvaziada")

    with pytest.raises(RuntimeError, match="Fila HID"):
        switcher.switch("Observabilidade")

    assert device.set_image.call_count == 15
    assert manager.active_name == "Desenvolvimento"
    assert not controller.handle_event(1, True)


def test_pending_actions_timeout_restores_old_profile(environment):
    manager, controller, device, drain, switcher, _ = environment

    # Simular um executor que ainda não terminou.
    controller.wait_idle = Mock(return_value=False)

    with pytest.raises(TimeoutError, match="Ações pendentes"):
        switcher.switch("Observabilidade")

    assert manager.active_name == "Desenvolvimento"

    # O controlador voltou a aceitar eventos do perfil anterior.
    assert controller.handle_event(1, True)

    device.set_image.assert_not_called()
    drain.assert_not_called()


def test_invalid_idle_timeout(environment):
    manager, controller, device, drain, _, _ = environment

    with pytest.raises(ValueError, match="idle_timeout"):
        ProfileSwitcher(
            manager,
            controller,
            device,
            drain_events=drain,
            idle_timeout=-1,
        )
