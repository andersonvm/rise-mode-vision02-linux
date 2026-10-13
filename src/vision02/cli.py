"""CLI mínima. Não executa comandos do sistema ao pressionar teclas."""
import argparse
from .device import Vision02, find_device
from .protocol import physical_key_to_display_id


def main():
    parser = argparse.ArgumentParser(prog="vision02")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("discover", help="Identifica a interface hidraw")
    sub.add_parser("listen", help="Mostra pressionamentos e liberações")
    sub.add_parser("number", help="Atualiza os 15 LCDs com números")
    image = sub.add_parser("image", help="Atualiza um display com um JPEG/PNG")
    image.add_argument("id", type=int, help="ID BAT, 1 a 15")
    image.add_argument("path")
    mapping = sub.add_parser("mapping", help="Tabela de mapeamento físico")
    args = parser.parse_args()
    if args.action == "discover":
        print(find_device())
        return
    if args.action == "mapping":
        print("Tecla física (linha superior primeiro) -> ID do display:")
        for start in (1, 6, 11):
            print(" ".join(f"{physical_key_to_display_id(k):02d}" for k in range(start, start + 5)))
        return
    if args.action == "image" and not 1 <= args.id <= 15:
        parser.error("ID BAT deve estar entre 1 e 15")
    with Vision02() as controller:
        if args.action == "number":
            controller.show_numbers()
            print("15 envios concluídos; confira os LCDs fisicamente")
        elif args.action == "image":
            controller.set_image(args.id, args.path)
            print(f"Transmissão do ID {args.id} concluída; confira o LCD")
        elif args.action == "listen":
            for key in range(1, 16):
                controller.on_press(key, lambda k: print(f"Tecla {k:02d}: PRESSIONADA", flush=True))
                controller.on_release(key, lambda k: print(f"Tecla {k:02d}: LIBERADA", flush=True))
            print("Aguardando eventos; Ctrl+C encerra")
            try:
                controller.run()
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
