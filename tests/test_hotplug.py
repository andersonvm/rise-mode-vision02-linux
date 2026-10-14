"""Testes offline do supervisor USB: nenhuma operação HID é executada."""
from pathlib import Path
import signal
import subprocess
import threading
from unittest.mock import Mock

import pytest

from vision02.hotplug import HotplugSupervisor, _stop_child


class FakeProcess:
    def __init__(self):
        self.code = None
        self.signals = []
        self.waits = []

    def poll(self):
        return self.code

    def send_signal(self, sig):
        self.signals.append(sig)
        self.code = 0

    def wait(self, timeout):
        self.waits.append(timeout)
        if self.code is None:
            raise subprocess.TimeoutExpired("vision02", timeout)
        return self.code

    def terminate(self):
        self.signals.append(signal.SIGTERM)
        self.code = 0

    def kill(self):
        self.signals.append(signal.SIGKILL)
        self.code = -9


def drive(states, *, exits=None):
    stop = threading.Event()
    processes = []
    launches = []
    delays = []
    states = iter(states)
    count = 0

    def probe():
        nonlocal count
        count += 1
        try:
            state = next(states)
        except StopIteration:
            stop.set()
            return None
        if exits and count in exits and processes:
            processes[-1].code = 1
        return Path(f"/dev/{state}") if state else None

    def spawn(args):
        launches.append(args)
        proc = FakeProcess()
        processes.append(proc)
        return proc

    def pause(delay):
        delays.append(delay)

    sup = HotplugSupervisor(
        ["vision02", "profile", "run", "dev.yaml"],
        interval=0.2,
        stop=stop,
        probe=probe,
        spawn=spawn,
        pause=pause,
    )
    sup.run()
    return processes, launches, delays


def test_waits_for_initial_connection():
    processes, launches, _ = drive([None, None, "hidraw9", "hidraw9"])
    assert len(launches) == 1
    assert processes[0].signals == [signal.SIGINT]


def test_unplug_closes_then_replug_starts_again():
    processes, launches, _ = drive([
        "hidraw9", "hidraw9", None, None, "hidraw10", "hidraw10"
    ])
    assert len(launches) == 2
    assert all(proc.signals == [signal.SIGINT] for proc in processes)


def test_reenumeration_without_absence_restarts():
    processes, launches, _ = drive(["hidraw9", "hidraw10", "hidraw10"])
    assert len(launches) == 2
    assert len(processes[0].signals) == 1


def test_successful_child_exit_still_restarts_with_backoff():
    _, launches, delays = drive(["hidraw9", "hidraw9", "hidraw9"], exits={2})
    assert len(launches) == 2
    assert 10.0 in delays  # First unexpected exit -> bounded delay.


def test_stop_child_sends_sigint_for_clean_shutdown():
    proc = FakeProcess()
    _stop_child(proc)
    assert proc.signals == [signal.SIGINT]
    assert proc.waits == [12.0]


def test_stop_child_already_finished_does_nothing():
    proc = FakeProcess()
    proc.code = 0
    _stop_child(proc)
    assert proc.signals == []


def test_stop_child_escalates_to_sigterm():
    proc = FakeProcess()
    proc.send_signal = Mock(side_effect=lambda sig: proc.signals.append(sig))
    _stop_child(proc)
    assert proc.signals == [signal.SIGINT, signal.SIGTERM]


def test_invalid_intervals():
    with pytest.raises(ValueError, match="Intervalo"):
        HotplugSupervisor(["cmd"], interval=0)
    with pytest.raises(ValueError, match="Espera máxima"):
        HotplugSupervisor(["cmd"], max_retry=0)


def test_spawn_failure_is_backed_off():
    stop = threading.Event()
    attempts = []
    ticks = 0
    def pause(delay):
        nonlocal ticks
        ticks += 1
        if ticks >= 3:
            stop.set()
    def spawn(args):
        attempts.append(list(args))
        raise OSError("nenhum executável")
    sup = HotplugSupervisor(
        ["cmd"], stop=stop, probe=lambda: Path("/dev/hidraw9"),
        spawn=spawn, pause=pause,
    )
    sup.run()
    assert len(attempts) == 3


def test_no_double_spawn_while_connected():
    _, launches, _ = drive(["hidraw9"] * 8)
    assert len(launches) == 1
