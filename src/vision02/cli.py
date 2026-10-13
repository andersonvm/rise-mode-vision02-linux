"""Interface de linha de comando da Rise Mode Vision 02."""

from __future__ import annotations

import argparse
from pathlib import Path

from .controller import Vision02Controller
from .device import Vision02, find_device
from .profiles import ProfileValidationError, load_profile
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


def _run_profile(profile) -> None:
    controller = Vision02Controller(profile)

    with Vision02() as device:
        try:
            controller.start()

            for key_id, config in sorted(profile.keys.items()):
                if config.image is not None:
                    device.set_image(
                        physical_key_to_display_id(key_id),
                        config.image,
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
                controller.handle_event(key_id, pressed)

        except KeyboardInterrupt:
            print("\nEncerrando perfil...", flush=True)

        finally:
            controller.stop()


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
        try:
            profile = load_profile(args.path)
        except (ProfileValidationError, OSError) as exc:
            parser.error(f"Perfil inválido: {exc}")

        if args.profile_action == "validate":
            _print_profile(profile)
            return

        _run_profile(profile)
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
