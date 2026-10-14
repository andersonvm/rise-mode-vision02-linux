"""Biblioteca de ícones pessoais Vision 02 (offline, sem HID ou IPC).

Importações são normalizadas como PNG RGB 100x100, deduplicadas por conteúdo
final e gravadas no XDG_DATA_HOME com permissões restritas.
"""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import re
import tempfile
import unicodedata
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

SIZE = (100, 100)
MAX_SOURCE_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 20_000_000
FILENAME = re.compile(r"^[a-f0-9]{20}-[a-z0-9][a-z0-9-]{0,47}\.png$")


def icon_directory() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    data_home = Path(base).expanduser() if base else Path.home() / ".local" / "share"
    return data_home / "vision02" / "assets" / "icons"


def _directory(path: Path, *, create: bool) -> Path:
    if not path.is_absolute():
        raise ValueError("Diretório da biblioteca deve ser absoluto")
    # Rejeita links simbólicos em qualquer componente que já exista.
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError(f"Diretório com link simbólico: {component}")
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        # O diretório dos ícones é privado mesmo se já existia.
        path.chmod(0o700)
    if path.exists() and not path.is_dir():
        raise ValueError("O caminho da biblioteca não é um diretório")
    return path


def _slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return (cleaned or "icone")[:45].rstrip("-")


def list_icons(root: Path | None = None) -> list[dict]:
    directory = _directory(Path(root) if root is not None else icon_directory(), create=False)
    if not directory.exists():
        return []
    icons = []
    for path in sorted(directory.iterdir()):
        if not FILENAME.fullmatch(path.name) or path.is_symlink() or not path.is_file():
            continue
        icons.append({
            "name": path.stem.split("-", 1)[1].replace("-", " ").title(),
            "path": str(path),
            "id": path.name[:20],
        })
    return icons


def import_icon(source: Path, *, root: Path | None = None) -> dict:
    source = Path(source).expanduser()
    if source.is_symlink() or not source.is_file():
        raise ValueError("Imagem inválida ou link simbólico")
    if not 0 < source.stat().st_size <= MAX_SOURCE_BYTES:
        raise ValueError("Imagem deve ter no máximo 15 MiB")
    if source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Formato aceito: PNG, JPEG ou WEBP")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as original:
                if original.width * original.height > MAX_PIXELS:
                    raise ValueError("Imagem excede 20 megapixels")
                if original.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ValueError("Formato real de imagem não permitido")
                # EXIF Orientation é aplicado antes de redimensionar.
                frame = ImageOps.exif_transpose(original)
                if frame.mode in {"RGBA", "LA"} or "transparency" in frame.info:
                    rgba = frame.convert("RGBA")
                    base = Image.new("RGBA", rgba.size, (8, 12, 22, 255))
                    base.alpha_composite(rgba)
                    frame = base.convert("RGB")
                else:
                    frame = frame.convert("RGB")
                normalized = ImageOps.fit(frame, SIZE, method=Image.Resampling.LANCZOS)
                stream = io.BytesIO()
                normalized.save(stream, format="PNG", optimize=True)
                data = stream.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError(f"Não foi possível processar a imagem: {exc}") from exc

    digest = hashlib.sha256(data).hexdigest()[:20]
    dest_dir = _directory(Path(root) if root is not None else icon_directory(), create=True)
    # Conteúdo idêntico é reutilizado sem duplicar arquivos.
    for current in dest_dir.glob(f"{digest}-*.png"):
        if current.is_symlink() or not current.is_file() or not FILENAME.fullmatch(current.name):
            raise ValueError("Entrada inválida na biblioteca")
        if current.read_bytes() == data:
            return {"name": current.stem.split("-", 1)[1].replace("-", " ").title(),
                    "path": str(current), "id": digest, "imported": False}
    filename = f"{digest}-{_slug(source.stem)}.png"
    dest = dest_dir / filename
    if dest.exists() or dest.is_symlink():
        raise ValueError("Conflito de nome na biblioteca")
    fd, temporary = tempfile.mkstemp(prefix=".vision02-icon-", suffix=".png", dir=dest_dir)
    try:
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        # Hard link atômico com O_EXCL implícito: nunca sobrescreve um destino.
        os.link(temporary, dest)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {"name": source.stem, "path": str(dest), "id": digest, "imported": True}
