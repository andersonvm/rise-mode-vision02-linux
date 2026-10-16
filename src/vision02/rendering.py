"""Renderização visual de perfis para os LCDs 100x100."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .profiles.models import KeyAppearance, KeyConfig, Profile


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




_FONTS = {
    "sans": ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    "serif": ("DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf"),
    "mono": ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf"),
}


def _appearance_font(style: KeyAppearance, size: int):
    names = _FONTS[style.font_family]
    filename = names[1 if style.font_weight == "bold" else 0]
    try:
        return ImageFont.truetype(filename, size)
    except OSError:
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except OSError:
            return ImageFont.load_default()


def _appearance_background(image_path: Path | None, style: KeyAppearance) -> Image.Image:
    color = style.background
    background = Image.new("RGB", LCD_SIZE, color)
    if image_path is None:
        return background
    with Image.open(image_path) as source:
        source = ImageOps.exif_transpose(source).convert("RGBA")
        if style.image_fit == "cover":
            overlay = ImageOps.fit(source, LCD_SIZE, method=Image.Resampling.LANCZOS)
        elif style.image_fit == "contain":
            overlay = source.copy()
            overlay.thumbnail(LCD_SIZE, Image.Resampling.LANCZOS)
            centered = Image.new("RGBA", LCD_SIZE, (0, 0, 0, 0))
            centered.alpha_composite(overlay, ((100 - overlay.width)//2, (100 - overlay.height)//2))
            overlay = centered
        else:
            overlay = source.resize(LCD_SIZE, Image.Resampling.LANCZOS)
    # In legacy configurations (x=y=0 and scale=100), retain the exact
    # original raster pipeline: no additional resampling or quantization.
    if (style.image_x, style.image_y, style.image_scale) != (0, 0, 100):
        if style.image_scale != 100:
            side = max(1, round(100 * style.image_scale / 100))
            overlay = overlay.resize((side, side), Image.Resampling.LANCZOS)
        # alpha_composite(destination) crops images at the LCD boundary;
        # source proportions and transparency are preserved by Pillow.
        xy = ((100 - overlay.width) // 2 + style.image_x,
              (100 - overlay.height) // 2 + style.image_y)
    else:
        xy = (0, 0)
    composed = background.convert("RGBA")
    composed.alpha_composite(overlay, xy)
    return composed.convert("RGB")


def render_appearance(label: str, image: Path | None, style: KeyAppearance) -> Image.Image:
    """Renderiza fundo + texto usando exatamente o pipeline usado no LCD."""
    output = _appearance_background(image, style)
    text = label if style.text is None else style.text
    if not style.show_text or not text.strip():
        return output
    draw = ImageDraw.Draw(output)
    maximum = 92
    for size in range(style.font_size, 7, -1):
        font = _appearance_font(style, size)
        lines = _wrap(draw, text, font, maximum)
        lineheight = _line_height(draw, font)
        if len(lines) * lineheight <= maximum:
            break
    else:
        font = _appearance_font(style, 8)
        lines = _wrap(draw, text, font, maximum)
        lineheight = _line_height(draw, font)
    cap = max(1, maximum // lineheight)
    if len(lines) > cap:
        lines = lines[:cap]
        while lines[-1] and _width(draw, lines[-1] + "…", font) > maximum:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    height = len(lines) * lineheight
    if style.vertical == "top":
        y = 4
    elif style.vertical == "bottom":
        y = 96 - height
    else:
        y = (100 - height) / 2
    y += style.offset_y
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        width = bbox[2] - bbox[0]
        if style.horizontal == "left":
            x = 4
        elif style.horizontal == "right":
            x = 96 - width
        else:
            x = (100 - width) / 2
        x += style.offset_x
        draw.text((x - bbox[0], y - bbox[1]), line, font=font, fill=style.text_color)
        y += lineheight
    return output


def render_key(config: KeyConfig | None) -> Image.Image | Path:
    """Seleciona imagem personalizada ou gera o rótulo."""

    if config is None:
        return render_empty()

    if config.appearance is not None:
        return render_appearance(config.label, config.image, config.appearance)

    if config.image is not None:
        return config.image

    return render_label(config.label)


def render_profile(profile: Profile) -> dict[int, Image.Image | Path]:
    """Renderiza as 15 teclas usando identificadores físicos."""

    return {
        key_id: render_key(profile.keys.get(key_id))
        for key_id in range(1, 16)
    }
