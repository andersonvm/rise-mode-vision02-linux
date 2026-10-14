"""Testes do renderizador sem acesso à Vision 02."""

from pathlib import Path

import pytest
from PIL import Image, ImageChops

from vision02.profiles.models import Action, KeyConfig, Profile
from vision02.rendering import (
    BACKGROUND,
    LCD_SIZE,
    render_empty,
    render_key,
    render_label,
    render_profile,
)


def make_key(key_id, label, image=None):
    return KeyConfig(
        key_id=key_id,
        label=label,
        image=image,
        action=Action(type="command", argv=("echo",)),
    )


def test_empty_display():
    image = render_empty()

    assert image.size == LCD_SIZE
    assert image.mode == "RGB"
    assert set(image.get_flattened_data()) == {BACKGROUND}


def test_label_dimensions():
    image = render_label("Terminal")

    assert image.size == (100, 100)
    assert image.mode == "RGB"


def test_label_is_visible():
    label = render_label("Terminal")
    empty = render_empty()

    assert ImageChops.difference(label, empty).getbbox() is not None


@pytest.mark.parametrize(
    "label",
    [
        "Terminal",
        "Visual Studio Code",
        "Observabilidade",
        "Supercalifragilisticexpialidocious",
        "Árvore\nMétricas",
        "Aplicação de desenvolvimento extremamente longa",
    ],
)
def test_long_labels(label):
    image = render_label(label)

    assert image.size == LCD_SIZE


def test_different_labels():
    first = render_label("Terminal")
    second = render_label("GitHub")

    assert ImageChops.difference(first, second).getbbox() is not None


def test_empty_label_rejected():
    with pytest.raises(ValueError):
        render_label("   ")


def test_key_without_custom_image():
    result = render_key(make_key(1, "Terminal"))

    assert isinstance(result, Image.Image)


def test_custom_image_preserved(tmp_path):
    image = tmp_path / "icone.png"
    image.write_bytes(b"imagem-simulada")

    result = render_key(make_key(1, "Terminal", image))

    assert isinstance(result, Path)
    assert result == image


def test_unconfigured_key():
    result = render_key(None)

    assert isinstance(result, Image.Image)
    assert set(result.get_flattened_data()) == {BACKGROUND}


def test_profile_contains_15_keys():
    profile = Profile(
        name="Teste",
        keys={
            1: make_key(1, "Terminal"),
            3: make_key(3, "GitHub"),
        },
    )

    result = render_profile(profile)

    assert list(result) == list(range(1, 16))
    assert all(
        isinstance(value, (Image.Image, Path))
        for value in result.values()
    )


def test_unconfigured_displays_are_empty():
    profile = Profile(
        name="Teste",
        keys={1: make_key(1, "Terminal")},
    )

    result = render_profile(profile)

    assert set(result[2].get_flattened_data()) == {BACKGROUND}
    assert set(result[15].get_flattened_data()) == {BACKGROUND}
