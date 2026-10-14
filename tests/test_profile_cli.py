"""Integração da CLI de perfis sem acesso a hardware."""

from unittest.mock import MagicMock, patch

import pytest

from vision02.cli import main
from vision02.protocol import physical_key_to_display_id


PROFILE = """
version: 1
name: Desenvolvimento
keys:
  1:
    label: Terminal
    action:
      type: command
      argv: [echo, teste]
"""


def profile_file(tmp_path, content=PROFILE):
    path = tmp_path / "perfil.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_validate_does_not_access_usb(tmp_path, capsys):
    path = profile_file(tmp_path)

    with patch("vision02.cli.Vision02") as device:
        main(["profile", "validate", str(path)])

    output = capsys.readouterr().out
    assert "Perfil válido: Desenvolvimento" in output
    assert "Teclas configuradas: 1/15" in output
    device.assert_not_called()


def test_invalid_profile_does_not_access_usb(tmp_path):
    path = profile_file(
        tmp_path,
        "version: 99\nname: Inválido\nkeys: {}\n",
    )

    with patch("vision02.cli.Vision02") as device:
        with pytest.raises(SystemExit) as exc:
            main(["profile", "run", str(path)])

    assert exc.value.code == 2
    device.assert_not_called()


def test_run_dispatches_only_presses(tmp_path):
    path = profile_file(tmp_path)

    device = MagicMock()
    device.read_event.side_effect = [
        (1, True),
        (1, False),
        (15, True),
        KeyboardInterrupt(),
    ]

    with (
        patch("vision02.cli.Vision02") as device_class,
        patch("vision02.cli.Vision02Controller") as controller_class,
    ):
        device_class.return_value.__enter__.return_value = device
        main(["profile", "run", str(path)])

    controller = controller_class.return_value
    controller.start.assert_called_once()
    controller.handle_event.assert_any_call(1, True)
    controller.handle_event.assert_any_call(1, False)
    controller.handle_event.assert_any_call(15, True)
    assert controller.handle_event.call_count == 3
    controller.stop.assert_called_once()


def test_run_uploads_configured_image(tmp_path):
    image = tmp_path / "icon.png"
    image.write_bytes(b"imagem-simulada")

    path = profile_file(
        tmp_path,
        """
version: 1
name: Com ícone
keys:
  1:
    label: Terminal
    image: icon.png
    action:
      type: command
      argv: [echo]
""",
    )

    device = MagicMock()
    device.read_event.side_effect = KeyboardInterrupt()

    with (
        patch("vision02.cli.Vision02") as device_class,
        patch("vision02.cli.Vision02Controller"),
    ):
        device_class.return_value.__enter__.return_value = device
        main(["profile", "run", str(path)])

    assert device.set_image.call_count == 15

    device.set_image.assert_any_call(
        physical_key_to_display_id(1),
        image.resolve(),
        skip_unchanged=True,
    )

    display_ids = {
        call.args[0]
        for call in device.set_image.call_args_list
    }

    assert display_ids == set(range(1, 16))


def test_existing_mapping_command_without_usb(capsys):
    with patch("vision02.cli.Vision02") as device:
        main(["mapping"])

    output = capsys.readouterr().out
    assert "ID do display" in output
    device.assert_not_called()


def switch_profiles(tmp_path):
    development = tmp_path / "desenvolvimento.yaml"
    observability = tmp_path / "observabilidade.yaml"

    development.write_text(
        """
version: 1
name: Desenvolvimento
keys:
  15:
    label: Observar
    action:
      type: profile
      target: Observabilidade
""",
        encoding="utf-8",
    )

    observability.write_text(
        """
version: 1
name: Observabilidade
keys:
  15:
    label: Desenvolv.
    action:
      type: profile
      target: Desenvolvimento
""",
        encoding="utf-8",
    )

    return development, observability


def test_multiple_profiles_switch_on_key_15(tmp_path):
    development, observability = switch_profiles(tmp_path)

    device = MagicMock()
    device.read_event.side_effect = [
        (15, True),
        None,              # Fim dos eventos pendentes.
        (15, False),
        KeyboardInterrupt(),
    ]

    with (
        patch("vision02.cli.Vision02") as device_class,
        patch("vision02.cli.Vision02Controller") as controller_class,
    ):
        device_class.return_value.__enter__.return_value = device

        main([
            "profile",
            "run",
            str(development),
            "--with",
            str(observability),
        ])

    controller = controller_class.return_value

    assert device.set_image.call_count == 30
    controller.suspend.assert_called_once()
    controller.wait_idle.assert_called_once()
    controller.activate.assert_called_once()

    assert (
        controller.activate.call_args.args[0].name
        == "Observabilidade"
    )

    controller.stop.assert_called_once()


def test_invalid_switch_target_does_not_open_usb(tmp_path):
    development = tmp_path / "desenvolvimento.yaml"
    development.write_text(
        """
version: 1
name: Desenvolvimento
keys:
  15:
    label: Inexistente
    action:
      type: profile
      target: PerfilInexistente
""",
        encoding="utf-8",
    )

    with patch("vision02.cli.Vision02") as device_class:
        with pytest.raises(SystemExit) as exc:
            main(["profile", "run", str(development)])

    assert exc.value.code == 2
    device_class.assert_not_called()


def test_drain_discards_old_presses(tmp_path):
    development, observability = switch_profiles(tmp_path)

    device = MagicMock()
    device.read_event.side_effect = [
        (15, True),        # Solicita troca.
        (1, True),         # Pressão antiga acumulada.
        (1, False),
        None,              # Fim da limpeza.
        (15, False),       # Liberação da tecla de troca.
        KeyboardInterrupt(),
    ]

    with (
        patch("vision02.cli.Vision02") as device_class,
        patch("vision02.cli.Vision02Controller") as controller_class,
    ):
        device_class.return_value.__enter__.return_value = device

        main([
            "profile",
            "run",
            str(development),
            "--with",
            str(observability),
        ])

    controller = controller_class.return_value

    assert not any(
        call.args == (1, True)
        for call in controller.handle_event.call_args_list
    )

    controller.activate.assert_called_once()


def test_switch_key_waits_for_release(tmp_path):
    development, observability = switch_profiles(tmp_path)

    device = MagicMock()
    device.read_event.side_effect = [
        (15, True),        # Primeira troca.
        None,              # Fim da limpeza.
        (15, True),        # Repetição sem liberação.
        (15, False),       # Agora liberou.
        KeyboardInterrupt(),
    ]

    with (
        patch("vision02.cli.Vision02") as device_class,
        patch("vision02.cli.Vision02Controller") as controller_class,
    ):
        device_class.return_value.__enter__.return_value = device

        main([
            "profile",
            "run",
            str(development),
            "--with",
            str(observability),
        ])

    controller = controller_class.return_value

    # O segundo pressionamento não pode provocar nova troca.
    controller.activate.assert_called_once()


def test_drain_limit_prevents_unsafe_activation(tmp_path):
    development, observability = switch_profiles(tmp_path)

    device = MagicMock()
    device.read_event.side_effect = (
        [(15, True)]
        + [(1, True)] * 256
    )

    with (
        patch("vision02.cli.Vision02") as device_class,
        patch("vision02.cli.Vision02Controller") as controller_class,
    ):
        device_class.return_value.__enter__.return_value = device

        with pytest.raises(RuntimeError, match="Limite de eventos"):
            main([
                "profile",
                "run",
                str(development),
                "--with",
                str(observability),
            ])

    controller = controller_class.return_value

    controller.suspend.assert_called_once()
    controller.activate.assert_not_called()
    controller.stop.assert_called_once()
