"""Renderização visual de perfis para os LCDs 100x100."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .profiles.models import KeyConfig, Profile


LCD_SIZE = (100, 100)
BACKGROUND = (8, 12, 22)
FOREGROUND = (245, 247, 250)
BORDER = (38, 55, 75)

TEXT_WIDTH = 84
TEXT_HEIGHT = 76


def _font(size: int):
    for name in (
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue

    return ImageFont.load_default()


def _width(draw, text, font):
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _wrap(draw, text, font, max_width):
    lines = []

    for paragraph in text.splitlines() or [""]:
        if not paragraph.strip():
            lines.append("")
            continue

        current = ""

        for word in paragraph.split():
            candidate = f"{current} {word}".strip()

            if _width(draw, candidate, font) <= max_width:
                current = candidate
                continue

            if current:
                lines.append(current)
                current = ""

            for char in word:
                candidate = current + char

                if current and _width(draw, candidate, font) > max_width:
                    lines.append(current)
                    current = char
                else:
                    current = candidate

        if current:
            lines.append(current)

    return lines


def _line_height(draw, font):
    box = draw.textbbox((0, 0), "Ágj", font=font)
    return max(1, box[3] - box[1] + 4)


def _layout(draw, label):
    """Prioriza palavras inteiras antes de quebrar caracteres."""

    sizes = (20, 18, 16, 14, 12, 10)

    for size in sizes:
        font = _font(size)
        lines = _wrap(draw, label, font, TEXT_WIDTH)
        line_height = _line_height(draw, font)

        # Não dividir uma palavra que caberia numa fonte menor.
        words = label.split()

        words_fit = all(
            _width(draw, word, font) <= TEXT_WIDTH
            for word in words
        )

        if (
            words_fit
            and len(lines) * line_height <= TEXT_HEIGHT
        ):
            return font, lines, line_height

    # Fallback para palavras excepcionalmente longas.
    font = _font(10)
    lines = _wrap(draw, label, font, TEXT_WIDTH)
    line_height = _line_height(draw, font)

    max_lines = max(1, TEXT_HEIGHT // line_height)

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]

        while last and _width(draw, last + "…", font) > TEXT_WIDTH:
            last = last[:-1]

        lines[-1] = last + "…"

    return font, lines, line_height


def render_label(label: str) -> Image.Image:
    """Gera a imagem de uma tecla com texto centralizado."""

    if not isinstance(label, str) or not label.strip():
        raise ValueError("label deve ser um texto não vazio")

    image = Image.new("RGB", LCD_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (3, 3, 96, 96),
        radius=10,
        outline=BORDER,
        width=2,
    )

    font, lines, line_height = _layout(draw, label.strip())

    y = (100 - len(lines) * line_height) / 2

    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        width = box[2] - box[0]

        x = (100 - width) / 2 - box[0]
        draw.text(
            (x, y - box[1]),
            line,
            font=font,
            fill=FOREGROUND,
        )

        y += line_height

    return image


def render_empty() -> Image.Image:
    """Representa um display sem ação configurada."""
    return Image.new("RGB", LCD_SIZE, BACKGROUND)


def render_key(config: KeyConfig | None) -> Image.Image | Path:
    """Seleciona imagem personalizada ou gera o rótulo."""

    if config is None:
        return render_empty()

    if config.image is not None:
        return config.image

    return render_label(config.label)


def render_profile(profile: Profile) -> dict[int, Image.Image | Path]:
    """Renderiza as 15 teclas usando identificadores físicos."""

    return {
        key_id: render_key(profile.keys.get(key_id))
        for key_id in range(1, 16)
    }
