"""Testes do controlador assíncrono sem hardware."""

import threading

import pytest

from vision02.controller import Vision02Controller
from vision02.profiles.models import Action, KeyConfig, Profile


@pytest.fixture
def profile():
    actions = {
        key: Action(type="command", argv=(f"action-{key}",))
        for key in (1, 2, 3)
    }

    return Profile(
        name="Teste",
        keys={
            key: KeyConfig(
                key_id=key,
                label=f"Tecla {key}",
                action=action,
            )
            for key, action in actions.items()
        },
    )


def test_press_executes_action(profile):
    executed = []
    controller = Vision02Controller(
        profile,
        executor=executed.append,
    )

    controller.start()

    assert controller.handle_event(1, True)

    controller.stop()

    assert executed == [profile.keys[1].action]


def test_release_is_ignored(profile):
    executed = []
    controller = Vision02Controller(
        profile,
        executor=executed.append,
    )

    controller.start()

    assert not controller.handle_event(1, False)

    controller.stop()

    assert executed == []


def test_unconfigured_key_is_ignored(profile):
    controller = Vision02Controller(
        profile,
        executor=lambda _: None,
    )

    controller.start()

    assert not controller.handle_event(15, True)

    controller.stop()


def test_actions_preserve_order(profile):
    executed = []
    controller = Vision02Controller(
        profile,
        executor=executed.append,
    )

    controller.start()

    for key in (1, 2, 3):
        assert controller.handle_event(key, True)

    controller.stop()

    assert executed == [
        profile.keys[key].action
        for key in (1, 2, 3)
    ]


def test_actions_run_in_worker_thread(profile):
    thread_names = []

    controller = Vision02Controller(
        profile,
        executor=lambda _: thread_names.append(
            threading.current_thread().name
        ),
    )

    controller.start()
    controller.handle_event(1, True)
    controller.stop()

    assert thread_names == ["vision02-actions"]


def test_executor_failure_does_not_stop_queue(profile):
    executed = []

    def executor(action):
        executed.append(action)

        if len(executed) == 1:
            raise RuntimeError("Falha simulada")

    controller = Vision02Controller(
        profile,
        executor=executor,
    )

    controller.start()

    assert controller.handle_event(1, True)
    assert controller.handle_event(2, True)

    controller.stop()

    assert len(executed) == 2


def test_full_queue_does_not_prevent_shutdown(profile):
    started = threading.Event()
    release = threading.Event()
    executed = []

    def executor(action):
        started.set()
        assert release.wait(timeout=3)
        executed.append(action)

    controller = Vision02Controller(
        profile,
        executor=executor,
        queue_size=1,
    )

    controller.start()

    assert controller.handle_event(1, True)
    assert started.wait(timeout=3)

    # A thread executa a primeira ação enquanto
    # a segunda permanece aguardando na fila.
    assert controller.handle_event(2, True)

    # A terceira ação deve ser rejeitada.
    assert not controller.handle_event(3, True)

    release.set()
    controller.stop(timeout=3)

    assert executed == [
        profile.keys[1].action,
        profile.keys[2].action,
    ]


def test_events_rejected_after_stop(profile):
    controller = Vision02Controller(
        profile,
        executor=lambda _: None,
    )

    controller.start()
    controller.stop()

    assert not controller.handle_event(1, True)


def test_restart_after_stop_is_rejected(profile):
    controller = Vision02Controller(
        profile,
        executor=lambda _: None,
    )

    controller.start()
    controller.stop()

    with pytest.raises(RuntimeError, match="encerrado"):
        controller.start()


def test_invalid_queue_size(profile):
    with pytest.raises(ValueError, match="queue_size"):
        Vision02Controller(profile, queue_size=0)


def test_stop_without_start(profile):
    controller = Vision02Controller(
        profile,
        executor=lambda _: None,
    )

    controller.stop()

    assert not controller.handle_event(1, True)


def test_negative_timeout_rejected(profile):
    controller = Vision02Controller(
        profile,
        executor=lambda _: None,
    )

    with pytest.raises(ValueError, match="timeout"):
        controller.stop(timeout=-1)


def test_start_after_stop_without_start_is_rejected(profile):
    controller = Vision02Controller(
        profile,
        executor=lambda _: None,
    )

    controller.stop()

    with pytest.raises(RuntimeError, match="encerrado"):
        controller.start()


def test_start_during_shutdown_is_rejected(profile):
    started = threading.Event()
    release = threading.Event()

    def executor(_action):
        started.set()
        assert release.wait(timeout=3)

    controller = Vision02Controller(
        profile,
        executor=executor,
    )

    controller.start()
    assert controller.handle_event(1, True)
    assert started.wait(timeout=3)

    try:
        with pytest.raises(TimeoutError):
            controller.stop(timeout=0)

        with pytest.raises(RuntimeError, match="encerrado"):
            controller.start()
    finally:
        release.set()
        controller.stop(timeout=3)
