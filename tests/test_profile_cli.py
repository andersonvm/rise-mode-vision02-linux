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

    device.set_image.assert_called_once_with(
        physical_key_to_display_id(1),
        image.resolve(),
        skip_unchanged=True,
    )


def test_existing_mapping_command_without_usb(capsys):
    with patch("vision02.cli.Vision02") as device:
        main(["mapping"])

    output = capsys.readouterr().out
    assert "ID do display" in output
    device.assert_not_called()
