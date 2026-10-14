"""Testes dos perfis YAML sem acesso ao hardware."""

import pytest

from vision02.profiles import (
    ProfileValidationError,
    load_profile,
)


def write_profile(tmp_path, content):
    path = tmp_path / "profile.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_valid_command_profile(tmp_path):
    path = write_profile(
        tmp_path,
        """
version: 1
name: Desenvolvimento
keys:
  1:
    label: Terminal
    action:
      type: command
      argv: [gnome-terminal]
""",
    )

    profile = load_profile(path)

    assert profile.name == "Desenvolvimento"
    assert profile.keys[1].action.type == "command"
    assert profile.keys[1].action.argv == ("gnome-terminal",)


def test_valid_url_profile(tmp_path):
    path = write_profile(
        tmp_path,
        """
version: 1
name: Web
keys:
  2:
    label: GitHub
    action:
      type: url
      url: https://github.com
""",
    )

    profile = load_profile(path)

    assert profile.keys[2].action.url == "https://github.com"


@pytest.mark.parametrize("key_id", [0, 16, -1, "true"])
def test_invalid_key_id(tmp_path, key_id):
    path = write_profile(
        tmp_path,
        f"""
version: 1
name: Teste
keys:
  {key_id}:
    label: Teste
    action:
      type: command
      argv: [echo]
""",
    )

    with pytest.raises(ProfileValidationError):
        load_profile(path)


def test_duplicate_keys_rejected(tmp_path):
    path = write_profile(
        tmp_path,
        """
version: 1
name: Teste
keys:
  1:
    label: Primeiro
    action:
      type: command
      argv: [echo]
  1:
    label: Segundo
    action:
      type: command
      argv: [echo]
""",
    )

    with pytest.raises(ProfileValidationError, match="duplicada"):
        load_profile(path)


def test_unknown_action_rejected(tmp_path):
    path = write_profile(
        tmp_path,
        """
version: 1
name: Teste
keys:
  1:
    label: Inválida
    action:
      type: shell
      command: echo teste
""",
    )

    with pytest.raises(ProfileValidationError, match="desconhecido"):
        load_profile(path)


def test_empty_argv_rejected(tmp_path):
    path = write_profile(
        tmp_path,
        """
version: 1
name: Teste
keys:
  1:
    label: Vazio
    action:
      type: command
      argv: []
""",
    )

    with pytest.raises(ProfileValidationError):
        load_profile(path)


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "ftp://example.com",
        "https://",
        "http://example.com:invalid",
    ],
)
def test_invalid_url_rejected(tmp_path, url):
    path = write_profile(
        tmp_path,
        f"""
version: 1
name: Teste
keys:
  1:
    label: URL
    action:
      type: url
      url: {url}
""",
    )

    with pytest.raises(ProfileValidationError):
        load_profile(path)


def test_missing_image_rejected(tmp_path):
    path = write_profile(
        tmp_path,
        """
version: 1
name: Teste
keys:
  1:
    label: Ícone
    image: icons/inexistente.png
    action:
      type: command
      argv: [echo]
""",
    )

    with pytest.raises(ProfileValidationError, match="não encontrado"):
        load_profile(path)


def test_existing_image_is_resolved(tmp_path):
    image = tmp_path / "icon.png"
    image.write_bytes(b"imagem-de-teste")

    path = write_profile(
        tmp_path,
        """
version: 1
name: Teste
keys:
  1:
    label: Ícone
    image: icon.png
    action:
      type: command
      argv: [echo]
""",
    )

    profile = load_profile(path)

    assert profile.keys[1].image == image.resolve()


def test_unknown_profile_field_rejected(tmp_path):
    path = write_profile(
        tmp_path,
        """
version: 1
name: Teste
unexpected: true
keys: {}
""",
    )

    with pytest.raises(ProfileValidationError, match="desconhecidos"):
        load_profile(path)


def test_invalid_version_rejected(tmp_path):
    path = write_profile(
        tmp_path,
        """
version: 2
name: Teste
keys: {}
""",
    )

    with pytest.raises(ProfileValidationError, match="version"):
        load_profile(path)


def test_profile_switch_action(tmp_path):
    path = write_profile(
        tmp_path,
        """
version: 1
name: Desenvolvimento
keys:
  15:
    label: Observabilidade
    action:
      type: profile
      target: Observabilidade
""",
    )

    profile = load_profile(path)
    action = profile.keys[15].action

    assert action.type == "profile"
    assert action.target == "Observabilidade"


@pytest.mark.parametrize(
    "target",
    ["", "   "],
)
def test_empty_profile_target_rejected(tmp_path, target):
    path = write_profile(
        tmp_path,
        f"""
version: 1
name: Desenvolvimento
keys:
  15:
    label: Trocar
    action:
      type: profile
      target: "{target}"
""",
    )

    with pytest.raises(ProfileValidationError, match="target"):
        load_profile(path)


def test_unknown_profile_action_field_rejected(tmp_path):
    path = write_profile(
        tmp_path,
        """
version: 1
name: Desenvolvimento
keys:
  15:
    label: Trocar
    action:
      type: profile
      target: Observabilidade
      command: echo
""",
    )

    with pytest.raises(ProfileValidationError, match="desconhecidos"):
        load_profile(path)
