"""Prévia local v7: renderizações com visibilidade independente.

Usa o renderizador de aparência existente sem alterar render_key/render_profile,
sem gravação de YAML e sem comunicação com o hardware.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PIL import Image

from .profiles.models import KeyAppearance
from .rendering import render_appearance

VISIBILITY_MODES = ('both', 'image', 'text', 'none')


def visibility_mode(show_image: bool, show_text: bool) -> str:
    if type(show_image) is not bool or type(show_text) is not bool:
        raise ValueError('A visibilidade deve ser booleana')
    return ('both' if show_image and show_text else
            'image' if show_image else
            'text' if show_text else 'none')


def render_preview_views(label: str, image: Path | None,
                         style: KeyAppearance) -> dict[str, Image.Image]:
    """Retorna 4 variantes RGB *idênticas* ao pipeline LCD em cada modo.

    Cada variante é calculada separadamente pelo pipeline existente; isto
    evita diferenças de antialiasing na prévia composta e preserva os pixels
    do modo `both` exatamente iguais à renderização do equipamento.
    """
    if not isinstance(label, str) or not isinstance(style, KeyAppearance):
        raise ValueError('Aparência da prévia inválida')
    if image is not None and not isinstance(image, Path):
        raise ValueError('Caminho de imagem inválido')
    no_text = replace(style, show_text=False)
    return {
        'both': render_appearance(label, image, style),
        'image': render_appearance(label, image, no_text),
        'text': render_appearance(label, None, style),
        'none': render_appearance(label, None, no_text),
    }


def render_rgba_components(label: str, image: Path | None,
                           style: KeyAppearance) -> dict[str, Image.Image]:
    """Separa fundo opaco, imagem RGBA e texto RGBA para edição local.

    Não modifica ``render_appearance`` nem é usado na transmissão ao LCD.
    Os modos visíveis do editor usam ``render_preview_views`` para conservar
    a paridade exata com o renderizador legada inclusive antialiasing.
    """
    from PIL import ImageDraw, ImageOps
    from .rendering import (_appearance_font, _wrap, _line_height, _width,
                            LCD_SIZE)

    if not isinstance(label, str) or not isinstance(style, KeyAppearance):
        raise ValueError('Aparência da prévia inválida')
    if image is not None and not isinstance(image, Path):
        raise ValueError('Caminho de imagem inválido')

    result = {
        'background': Image.new('RGBA', LCD_SIZE, style.background),
        'image': Image.new('RGBA', LCD_SIZE, (0, 0, 0, 0)),
        'text': Image.new('RGBA', LCD_SIZE, (0, 0, 0, 0)),
    }
    if image is not None:
        with Image.open(image) as source:
            source = ImageOps.exif_transpose(source).convert('RGBA')
            if style.image_fit == 'cover':
                overlay = ImageOps.fit(source, LCD_SIZE,
                                       method=Image.Resampling.LANCZOS)
            elif style.image_fit == 'contain':
                overlay = source.copy()
                overlay.thumbnail(LCD_SIZE, Image.Resampling.LANCZOS)
                centered = Image.new('RGBA', LCD_SIZE, (0, 0, 0, 0))
                centered.alpha_composite(overlay,
                    ((100 - overlay.width) // 2, (100 - overlay.height) // 2))
                overlay = centered
            else:
                overlay = source.resize(LCD_SIZE, Image.Resampling.LANCZOS)
        if (style.image_x, style.image_y, style.image_scale) != (0, 0, 100):
            if style.image_scale != 100:
                side = max(1, round(100 * style.image_scale / 100))
                overlay = overlay.resize((side, side), Image.Resampling.LANCZOS)
            position = ((100 - overlay.width) // 2 + style.image_x,
                        (100 - overlay.height) // 2 + style.image_y)
        else:
            position = (0, 0)
        result['image'].alpha_composite(overlay, position)

    caption = label if style.text is None else style.text
    if style.show_text and caption.strip():
        draw = ImageDraw.Draw(result['text'])
        maximum = 92
        for size in range(style.font_size, 7, -1):
            font = _appearance_font(style, size)
            lines = _wrap(draw, caption, font, maximum)
            line_height = _line_height(draw, font)
            if len(lines) * line_height <= maximum:
                break
        else:
            font = _appearance_font(style, 8)
            lines = _wrap(draw, caption, font, maximum)
            line_height = _line_height(draw, font)
        max_lines = max(1, maximum // line_height)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            while lines[-1] and _width(draw, lines[-1] + '…', font) > maximum:
                lines[-1] = lines[-1][:-1]
            lines[-1] += '…'
        text_height = len(lines) * line_height
        if style.vertical == 'top':
            y = 4
        elif style.vertical == 'bottom':
            y = 96 - text_height
        else:
            y = (100 - text_height) / 2
        y += style.offset_y
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            width = bbox[2] - bbox[0]
            if style.horizontal == 'left':
                x = 4
            elif style.horizontal == 'right':
                x = 96 - width
            else:
                x = (100 - width) / 2
            x += style.offset_x
            draw.text((x - bbox[0], y - bbox[1]), line,
                      font=font, fill=style.text_color)
            y += line_height
    return result
