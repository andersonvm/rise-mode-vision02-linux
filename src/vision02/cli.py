"""Interface de linha de comando da Rise Mode Vision 02."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .controller import Vision02Controller
from .actions.executor import execute_action
from .obs_control import OBSWorker
from .control_ipc import ControlServer, request as ipc_request
from .profile_reload import FatalReloadError, reload_profiles
from .actions.executor import close_wayland_keyboard
from .device import Vision02, find_device
from .profiles import (
    ProfileManager,
    ProfileManagerError,
    ProfileValidationError,
    load_profile,
    validate_profile_targets,
)
from .switching import ProfileSwitcher
from .rendering import render_profile
from .system_dashboard import Dashboard, MetricsWorker
from .system_status import StatusWorker
from .user_profiles import default_profile_paths
from .profile_catalog import choose_initial, write_last_active
from .protocol import physical_key_to_display_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vision02")
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("discover", help="Identifica a interface hidraw")
    sub.add_parser("listen", help="Mostra pressionamentos e liberações")
    sub.add_parser("number", help="Atualiza os 15 LCDs com números")

    image = sub.add_parser(
        "image",
        help="Atualiza um display com um JPEG/PNG",
    )
    image.add_argument("id", type=int, help="ID BAT, 1 a 15")
    image.add_argument("path")

    sub.add_parser("mapping", help="Tabela de mapeamento físico")

    profile = sub.add_parser(
        "profile",
        help="Validação e execução de perfis YAML",
    )
    profile_sub = profile.add_subparsers(
        dest="profile_action",
        required=True,
    )

    validate = profile_sub.add_parser(
        "validate",
        help="Valida um perfil sem acessar o hardware",
    )
    validate.add_argument("path", type=Path)

    run = profile_sub.add_parser(
        "run",
        help="Executa um perfil na Vision 02",
    )
    run.add_argument("path", type=Path, nargs="?")
    run.add_argument("--catalog", action="store_true", help="Carrega todos os YAML pessoais e restaura perfil ativo")
    run.add_argument("--ipc", action="store_true", help="Habilita controle local para GUI e CLI")
    run.add_argument(
        "--with",
        dest="other_paths",
        nargs="+",
        type=Path,
        default=[],
        metavar="PROFILE",
        help="Perfis adicionais disponíveis para alternância",
    )

    control = sub.add_parser("control", help="Consulta e controla a instância ativa sem abrir HID")
    control_sub = control.add_subparsers(dest="control_action", required=True)
    control_sub.add_parser("status", help="Estado e perfil ativo")
    control_sub.add_parser("profiles", help="Perfis disponíveis")
    control_sub.add_parser("reload", help="Recarrega os YAML sem reiniciar HID")
    control_switch = control_sub.add_parser("switch", help="Ativa um perfil existente")
    control_switch.add_argument("target", help="Nome exato do perfil")

    return parser


def _print_profile(profile) -> None:
    print(f"Perfil válido: {profile.name}")
    print(f"Versão do formato: {profile.version}")
    print(f"Teclas configuradas: {len(profile.keys)}/15")

    for key_id, config in sorted(profile.keys.items()):
        print(
            f"  Tecla {key_id:02d}: "
            f"{config.label} [{config.action.type}]"
        )


def _run_profile(
    manager: ProfileManager, *, ipc: bool = False,
    profile_paths: tuple[Path, ...] = (), catalog: bool = False,
) -> None:
    """Executa perfis em uma única sessão HID."""
    profile = manager.active
    obs_worker = OBSWorker()
    def dispatch_action(action):
        if action.type == 'obs':
            obs_worker.submit(action)
        else:
            execute_action(action)
    controller = Vision02Controller(profile, executor=dispatch_action)
    metrics_worker = MetricsWorker()
    status_worker = StatusWorker()
    dashboard = Dashboard(metrics_worker, status_worker=status_worker, obs_worker=obs_worker)

    # Teclas cujos eventos devem ser ignorados até a liberação.
    blocked_keys: set[int] = set()

    with Vision02() as device:
        def drain_events() -> None:
            """Descarta eventos antigos sem bloquear indefinidamente."""
            limit = 256

            for _ in range(limit):
                event = device.read_event(timeout=0)

                if event is None:
                    return

                key_id, pressed = event

                if pressed:
                    blocked_keys.add(key_id)
                else:
                    blocked_keys.discard(key_id)

            raise RuntimeError(
                "Limite de eventos HID pendentes excedido"
            )

        switcher = ProfileSwitcher(
            manager,
            controller,
            device,
            drain_events=drain_events,
        )

        control_server: ControlServer | None = None
        reload_fatal: FatalReloadError | None = None

        def handle_control(command: str, target: str | None) -> dict:
            nonlocal manager, reload_fatal, profile_paths
            if command == "status":
                return {
                    "connected": True,
                    "active": manager.active_name,
                    "profiles": list(manager.list_profiles()),
                }
            if command == "profiles":
                return {"profiles": list(manager.list_profiles())}
            if command == "reload":
                if catalog:
                    profile_paths = default_profile_paths(Path.cwd())
                if not profile_paths:
                    raise ValueError("Caminhos dos perfis não configurados para reload")
                try:
                    updated = reload_profiles(
                        manager, profile_paths, controller, device, drain_events
                    )
                except FatalReloadError as exc:
                    reload_fatal = exc
                    raise
                manager = updated
                switcher.manager = updated
                dashboard.invalidate()
                print(f"Perfis recarregados: {manager.active_name}", flush=True)
                return {"active": manager.active_name,
                        "profiles": list(manager.list_profiles()), "reloaded": True}
            if command == "switch" and target is not None:
                changed = switcher.switch(target)
                if changed:
                    dashboard.invalidate()
                    print(f"Perfil ativo: {manager.active_name}", flush=True)
                    remember_active()
                return {"active": manager.active_name, "changed": changed}
            raise ValueError("Comando IPC desconhecido")

        def remember_active() -> None:
            if catalog and manager.active_name is not None:
                try:
                    write_last_active(manager.active_name)
                except (OSError, ValueError) as exc:
                    print(f"[Vision02] Não foi possível persistir perfil: {exc}", flush=True)

        try:
            controller.start()
            metrics_worker.start()
            status_worker.start()
            obs_worker.start()

            for key_id, image in render_profile(profile).items():
                device.set_image(
                    physical_key_to_display_id(key_id),
                    image,
                    skip_unchanged=True,
                )

            if ipc:
                control_server = ControlServer()
                control_server.start()

            print(
                f"Perfil ativo: {profile.name}. "
                "Aguardando teclas; Ctrl+C encerra.",
                flush=True,
            )

            while True:
                if control_server is not None:
                    control_server.process_pending(handle_control)
                    if reload_fatal is not None:
                        raise RuntimeError(
                            "Falha na atualização dos LCDs; reiniciando sessão HID"
                        ) from reload_fatal
                # Atualização de UM LCD por passagem, na thread proprietária HID.
                dashboard.tick(manager.active, device)
                event = device.read_event(timeout=0.2)

                if event is None:
                    continue

                key_id, pressed = event

                if not pressed:
                    blocked_keys.discard(key_id)
                    controller.handle_event(key_id, False)
                    continue

                if key_id in blocked_keys:
                    continue

                active_profile = manager.active
                config = active_profile.keys.get(key_id)

                if (
                    config is not None
                    and config.action.type == "profile"
                ):
                    # A mesma pressão não pode produzir outra
                    # troca após a atualização dos LCDs.
                    blocked_keys.add(key_id)

                    target = config.action.target
                    changed = switcher.switch(target)

                    if changed:
                        dashboard.invalidate()
                        print(
                            f"Perfil ativo: {manager.active_name}",
                            flush=True,
                        )
                        remember_active()

                    continue

                controller.handle_event(key_id, True)

        except KeyboardInterrupt:
            print("\\nEncerrando perfil...", flush=True)

        finally:
            obs_worker.close()
            status_worker.close()
            metrics_worker.close()
            if control_server is not None:
                control_server.close()
            try:
                controller.stop()
            finally:
                close_wayland_keyboard()


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.action == "discover":
        print(find_device())
        return

    if args.action == "mapping":
        print(
            "Tecla física (linha superior primeiro) "
            "-> ID do display:"
        )
        for start in (1, 6, 11):
            print(
                " ".join(
                    f"{physical_key_to_display_id(key):02d}"
                    for key in range(start, start + 5)
                )
            )
        return

    if args.action == "control":
        try:
            response = ipc_request(
                args.control_action,
                getattr(args, "target", None),
            )
        except (ConnectionError, OSError, RuntimeError, ValueError, TimeoutError) as exc:
            parser.error(str(exc))
        print(json.dumps(response, ensure_ascii=False, indent=2))
        if not response["ok"]:
            raise SystemExit(1)
        return

    if args.action == "profile":
        if args.profile_action == "validate":
            try:
                profile = load_profile(args.path)
            except (ProfileValidationError, OSError) as exc:
                parser.error(f"Perfil inválido: {exc}")

            _print_profile(profile)
            return

        if args.catalog:
            if args.path is not None or args.other_paths:
                parser.error("--catalog não pode ser combinado com caminhos explícitos")
            paths = default_profile_paths(Path.cwd())
        else:
            if args.path is None:
                parser.error("Informe o caminho do perfil ou use --catalog")
            paths = tuple([args.path, *args.other_paths])

        manager = ProfileManager()

        try:
            manager.load_many(paths)
            validate_profile_targets(manager)
            if args.catalog:
                manager.switch(choose_initial(manager.list_profiles()))
        except (
            ProfileValidationError,
            ProfileManagerError,
            OSError,
        ) as exc:
            parser.error(f"Perfis inválidos: {exc}")

        if args.ipc:
            _run_profile(
                manager, ipc=True,
                profile_paths=tuple(paths), catalog=args.catalog,
            )
        else:
            _run_profile(manager, catalog=args.catalog)
        return

    if args.action == "image" and not 1 <= args.id <= 15:
        parser.error("ID BAT deve estar entre 1 e 15")

    with Vision02() as device:
        if args.action == "number":
            device.show_numbers()
            print("15 envios concluídos; confira os LCDs fisicamente")

        elif args.action == "image":
            device.set_image(args.id, args.path)
            print(
                f"Transmissão do ID {args.id} concluída; "
                "confira o LCD"
            )

        elif args.action == "listen":
            for key in range(1, 16):
                device.on_press(
                    key,
                    lambda k: print(
                        f"Tecla {k:02d}: PRESSIONADA",
                        flush=True,
                    ),
                )
                device.on_release(
                    key,
                    lambda k: print(
                        f"Tecla {k:02d}: LIBERADA",
                        flush=True,
                    ),
                )

            print("Aguardando eventos; Ctrl+C encerra")

            try:
                device.run()
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
