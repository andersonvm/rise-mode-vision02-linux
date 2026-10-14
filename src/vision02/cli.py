"""Interface de linha de comando da Rise Mode Vision 02."""

from __future__ import annotations

import argparse
from pathlib import Path

from .controller import Vision02Controller
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
    run.add_argument("path", type=Path)
    run.add_argument(
        "--with",
        dest="other_paths",
        nargs="+",
        type=Path,
        default=[],
        metavar="PROFILE",
        help="Perfis adicionais disponíveis para alternância",
    )

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


def _run_profile(manager: ProfileManager) -> None:
    """Executa perfis em uma única sessão HID."""
    profile = manager.active
    controller = Vision02Controller(profile)

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

        try:
            controller.start()

            for key_id, image in render_profile(profile).items():
                device.set_image(
                    physical_key_to_display_id(key_id),
                    image,
                    skip_unchanged=True,
                )

            print(
                f"Perfil ativo: {profile.name}. "
                "Aguardando teclas; Ctrl+C encerra.",
                flush=True,
            )

            while True:
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
                        print(
                            f"Perfil ativo: {manager.active_name}",
                            flush=True,
                        )

                    continue

                controller.handle_event(key_id, True)

        except KeyboardInterrupt:
            print("\\nEncerrando perfil...", flush=True)

        finally:
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

    if args.action == "profile":
        if args.profile_action == "validate":
            try:
                profile = load_profile(args.path)
            except (ProfileValidationError, OSError) as exc:
                parser.error(f"Perfil inválido: {exc}")

            _print_profile(profile)
            return

        manager = ProfileManager()

        try:
            manager.load_many([args.path, *args.other_paths])
            validate_profile_targets(manager)
        except (
            ProfileValidationError,
            ProfileManagerError,
            OSError,
        ) as exc:
            parser.error(f"Perfis inválidos: {exc}")

        _run_profile(manager)
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
