"""Codificação de imagens para os LCDs 100x100, com rotação validada."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from PIL import Image, ImageOps


def encode_image(source: str | Path | Image.Image, *, quality: int = 90, subsampling: int = 0) -> bytes:
    if not 1 <= quality <= 100:
        raise ValueError("quality deve estar entre 1 e 100")
    if subsampling not in (0, 1, 2):
        raise ValueError("subsampling deve ser 0, 1 ou 2")
    if isinstance(source, Image.Image):
        image = source.copy()
    else:
        with Image.open(source) as file_image:
            image = ImageOps.exif_transpose(file_image).copy()
    image = ImageOps.fit(image.convert("RGB"), (100, 100), method=Image.Resampling.LANCZOS)
    image = image.transpose(Image.Transpose.ROTATE_180)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality, subsampling=subsampling)
    data = buffer.getvalue()
    if len(data) > 65535:
        raise ValueError("JPEG excede campo de 16 bits; reduza a qualidade")
    return data


def numbered_image(number: int) -> Image.Image:
    from PIL import ImageDraw, ImageFont
    image = Image.new("RGB", (100, 100), (8, 12, 22))
    draw = ImageDraw.Draw(image)
    draw.rectangle((3, 3, 96, 96), outline=(0, 200, 255), width=3)
    draw.rectangle((7, 7, 19, 19), fill=(255, 45, 45))
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 42)
    except OSError:
        font = ImageFont.load_default()
    label = f"{number:02d}"
    box = draw.textbbox((0, 0), label, font=font)
    draw.text(((100-(box[2]-box[0]))/2-box[0], (100-(box[3]-box[1]))/2-box[1]), label, font=font, fill="white")
    return image
