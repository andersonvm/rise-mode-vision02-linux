"""Supervisor de conexão USB para o controlador Rise Mode Vision 02.

Sem privilégios, sem udev, sem acesso ao dispositivo fora do processo filho.
Mantém o processo vivo enquanto o periférico estiver ausente; reinicia a CLI
em uma nova sessão HID após reconexão ou encerramento inesperado.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Callable


def probe_device() -> Path | None:
    """Identifica o hidraw por VID:PID; nunca abre nem inicializa o USB."""
    from .device import find_device

    try:
        path = find_device()
    except FileNotFoundError:
        return None
    except OSError as exc:
        print(f"[Vision02 hotplug] Falha na descoberta: {exc}", flush=True)
        return None
    return path if path.exists() else None


def validate_profiles(paths: list[Path]) -> list[Path]:
    """Falha cedo em perfis inválidos, inclusive sem periférico conectado."""
    from .profiles import ProfileManager, validate_profile_targets

    paths = [path.resolve(strict=True) for path in paths]
    manager = ProfileManager()
    manager.load_many(paths)
    validate_profile_targets(manager)
    return paths


def _stop_child(process: subprocess.Popen, *, timeout: float = 12.0) -> None:
    """Interrompe a CLI como Ctrl+C; só força encerramento se necessário."""
    if process.poll() is not None:
        return
    try:
        process.send_signal(signal.SIGINT)
        process.wait(timeout=timeout)
        return
    except subprocess.TimeoutExpired:
        print("[Vision02 hotplug] Encerramento demorou; enviando SIGTERM.", flush=True)
    except ProcessLookupError:
        return

    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=3)
        return
    except subprocess.TimeoutExpired:
        print("[Vision02 hotplug] Processo persistiu; enviando SIGKILL.", flush=True)
    except ProcessLookupError:
        return

    if process.poll() is None:
        try:
            process.kill()
            process.wait(timeout=3)
        except ProcessLookupError:
            pass


class HotplugSupervisor:
    """Supervisiona uma única CLI; probe/sleep/spawn injetáveis em testes."""

    def __init__(
        self,
        command: list[str],
        *,
        interval: float = 1.0,
        max_retry: float = 60.0,
        stop: threading.Event | None = None,
        probe: Callable[[], Path | None] = probe_device,
        spawn: Callable[[list[str]], subprocess.Popen] | None = None,
        pause: Callable[[float], object] | None = None,
    ):
        if not 0.1 <= interval <= 30:
            raise ValueError("Intervalo deve estar entre 0,1 e 30 segundos")
        if not 5 <= max_retry <= 300:
            raise ValueError("Espera máxima deve estar entre 5 e 300 segundos")
        self.command = list(command)
        self.interval = interval
        self.max_retry = max_retry
        self.stop = stop if stop is not None else threading.Event()
        self.probe = probe
        self.spawn = spawn or (lambda args: subprocess.Popen(args))
        self.pause = pause or self.stop.wait

    def run(self) -> None:
        process: subprocess.Popen | None = None
        bound: Path | None = None
        waiting = False
        retry = 5.0
        started = 0.0

        try:
            while not self.stop.is_set():
                path = self.probe()

                if process is not None:
                    code = process.poll()
                    if code is not None:
                        print(
                            f"[Vision02 hotplug] Controlador encerrado (status={code}).",
                            flush=True,
                        )
                        process = None
                        bound = None
                        if path is not None:
                            # Evita reinicialização contínua se outro programa
                            # tomou o periférico ou se a configuração falhou.
                            if time.monotonic() - started >= 30:
                                retry = 5.0
                            else:
                                retry = min(retry * 2, self.max_retry)
                            print(
                                f"[Vision02 hotplug] Nova tentativa em {retry:g}s.",
                                flush=True,
                            )
                            self.pause(retry)
                            continue
                        retry = 5.0
                    elif path is None or path != bound:
                        print(
                            "[Vision02 hotplug] Dispositivo ausente ou reenumerado; "
                            "encerrando sessão HID.",
                            flush=True,
                        )
                        _stop_child(process)
                        process = None
                        bound = None
                        retry = 5.0

                if self.stop.is_set():
                    break

                if process is None:
                    if path is None:
                        if not waiting:
                            print(
                                "[Vision02 hotplug] Aguardando Vision 02 via hidraw...",
                                flush=True,
                            )
                            waiting = True
                    else:
                        waiting = False
                        print(
                            f"[Vision02 hotplug] Detectada em {path}; "
                            "iniciando controlador.",
                            flush=True,
                        )
                        try:
                            process = self.spawn(self.command)
                        except OSError as exc:
                            print(
                                f"[Vision02 hotplug] Falha ao iniciar: {exc}. "
                                f"Tentando novamente em {retry:g}s.",
                                flush=True,
                            )
                            self.pause(retry)
                            retry = min(retry * 2, self.max_retry)
                            continue
                        bound = path
                        started = time.monotonic()

                self.pause(self.interval)
        finally:
            if process is not None:
                print("[Vision02 hotplug] Encerrando controlador...", flush=True)
                _stop_child(process)
            print("[Vision02 hotplug] Supervisor encerrado.", flush=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Inicia/reconecta automaticamente Vision 02 via hidraw"
    )
    parser.add_argument("profile", type=Path, nargs="?")
    parser.add_argument("--catalog", action="store_true", help="Descobre os perfis pessoais dinamicamente")
    parser.add_argument("--with", dest="other_profiles", type=Path, nargs="+", default=[])
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--max-retry", type=float, default=60.0)
    args = parser.parse_args(argv)

    if args.catalog:
        if args.profile is not None or args.other_profiles:
            parser.error("--catalog não aceita caminhos explícitos")
        from .user_profiles import default_profile_paths
        requested_paths = list(default_profile_paths(Path.cwd()))
    else:
        if args.profile is None:
            parser.error("Informe um perfil ou use --catalog")
        requested_paths = [args.profile, *args.other_profiles]

    try:
        profiles = validate_profiles(requested_paths)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(f"Perfis inválidos: {exc}")
    except Exception as exc:
        # Preserve error from existing YAML validation classes without
        # importing implementation details into the supervisor loop.
        parser.error(f"Não foi possível validar perfis: {exc}")

    command = [sys.executable, "-m", "vision02.cli", "profile", "run"]
    if args.catalog:
        command.append("--catalog")
    else:
        command.append(str(profiles[0]))
        if len(profiles) > 1:
            command.extend(["--with", *(str(p) for p in profiles[1:])])

    # O filho é o único dono do HID e publica o socket local da interface.
    command.append("--ipc")

    supervisor = HotplugSupervisor(
        command, interval=args.interval, max_retry=args.max_retry
    )
    def stop_handler(_signum, _frame):
        supervisor.stop.set()

    # Sem grupo de processos próprio: systemd usa KillMode=mixed para
    # sinalizar apenas o supervisor, que finaliza o controlador com SIGINT.
    old_int = signal.signal(signal.SIGINT, stop_handler)
    old_term = signal.signal(signal.SIGTERM, stop_handler)
    try:
        supervisor.run()
    finally:
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGTERM, old_term)


if __name__ == "__main__":
    main()
