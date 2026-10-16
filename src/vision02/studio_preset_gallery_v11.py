"""Galeria local de presets v11: miniaturas, pesquisa, categorias e favoritos.

Metadados vivem fora dos manifestos portáveis v10. Não grava perfis YAML.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from io import BytesIO
import fcntl
import json
import os
from pathlib import Path
import tempfile

from PIL import Image, ImageOps

from vision02 import studio_presets_v10 as presets
from vision02.profiles.models import KeyAppearance
from vision02.rendering import render_appearance, render_label

SCHEMA = 1
MAX_METADATA_BYTES = 64 * 1024
MAX_CATEGORY = 32


def metadata_path() -> Path:
    return presets.presets_dir().parent / 'preset-gallery-v11.json'


def _safe_path(path: Path) -> None:
    if path.is_symlink():
        raise ValueError('Arquivo de galeria não pode ser link simbólico')
    if path.exists() and not path.is_file():
        raise ValueError('Arquivo de galeria inválido')


def _category(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('Categoria inválida')
    if any(ord(char) < 32 or char in '/\\' for char in value):
        raise ValueError('Categoria inválida (caracteres não permitidos)')
    value = value.strip()
    if len(value) > MAX_CATEGORY:
        raise ValueError('Categoria inválida (máximo 32 caracteres; sem barras)')
    return value


def _read_meta(path: Path | None = None) -> dict:
    path = metadata_path() if path is None else path
    _safe_path(path)
    if not path.exists():
        return {}
    if path.stat().st_size > MAX_METADATA_BYTES:
        raise ValueError('Metadados da galeria grandes demais')
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Metadados da galeria inválidos') from exc
    if not isinstance(raw, dict) or set(raw) != {'schema', 'entries'} or raw['schema'] != SCHEMA or not isinstance(raw['entries'], dict):
        raise ValueError('Formato da galeria incompatível')
    result = {}
    for ident, entry in raw['entries'].items():
        presets._ident(ident)
        if not isinstance(entry, dict) or set(entry) != {'favorite', 'category'} or type(entry['favorite']) is not bool:
            raise ValueError('Metadados de preset inválidos')
        result[ident] = {'favorite': entry['favorite'], 'category': _category(entry['category'])}
    return result


def _save_meta(path: Path, entries: dict) -> None:
    _safe_path(path)
    raw = (json.dumps({'schema': SCHEMA, 'entries': entries}, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    if len(raw) > MAX_METADATA_BYTES:
        raise ValueError('Biblioteca de metadados excede limite')
    fd, temp = tempfile.mkstemp(prefix='.vision02-gallery-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        _safe_path(path)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


@contextmanager
def _locked():
    path = metadata_path()
    lock = path.with_suffix('.lock')
    _safe_path(lock)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'rb+') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield path
    finally:
        pass


def _existing(ident: str) -> None:
    presets._read(ident)  # verifica JSON + checksum PNG e rejeita symlinks


def update_metadata(ident: str, *, favorite: bool | None = None, category: str | None = None) -> dict:
    _existing(ident)
    if favorite is not None and type(favorite) is not bool:
        raise ValueError('Favorito deve ser booleano')
    if category is not None:
        category = _category(category)
    if favorite is None and category is None:
        raise ValueError('Nenhuma propriedade informada')
    with _locked() as path:
        entries = _read_meta(path)
        item = entries.get(ident, {'favorite': False, 'category': ''}).copy()
        if favorite is not None:
            item['favorite'] = favorite
        if category is not None:
            item['category'] = category
        _existing(ident)
        entries[ident] = item
        _save_meta(path, entries)
    return {'id': ident, **item}


def remove_metadata(ident: str) -> None:
    presets._ident(ident)
    with _locked() as path:
        entries = _read_meta(path)
        if ident in entries:
            del entries[ident]
            _save_meta(path, entries)


def duplicate_preset(ident: str, name: str) -> dict:
    manifest, picture = presets._read(ident)
    # Validar metadados antes de publicar uma cópia, evitando cópia órfã.
    meta = _read_meta().get(ident, {'favorite': False, 'category': ''})
    result = presets._publish(name, manifest['appearance'], picture)
    # Não copiar 'favorite': usuário decide se a variação também é favorita.
    if meta['category']:
        update_metadata(result['id'], category=meta['category'])
    return result


def thumbnail_root() -> Path:
    home = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')).expanduser()
    path = home / 'vision02' / 'preset-gallery-v11'
    for parent in (home, home / 'vision02', path):
        if parent.is_symlink():
            raise ValueError('Cache de miniaturas não pode ser link simbólico')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def _preview_png(manifest: dict, picture: bytes | None) -> bytes:
    # 'Prévia' é um rótulo demonstrativo para presets sem texto próprio.
    style = KeyAppearance(**manifest['appearance']) if manifest['appearance'] is not None else None
    if style is not None:
        if picture:
            # render_appearance usa exatamente o pipeline do LCD.
            # Arquivo temporário evita modificar presets/ativos.
            png = picture
            fd, filename = tempfile.mkstemp(prefix='.vision02-gallery-source-', suffix='.png', dir=thumbnail_root())
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(png)
                rendered = render_appearance('Prévia', Path(filename), style)
            finally:
                Path(filename).unlink(missing_ok=True)
        else:
            rendered = render_appearance('Prévia', None, style)
    elif picture:
        with Image.open(BytesIO(picture)) as source:
            rendered = ImageOps.fit(source.convert('RGB'), (100, 100), method=Image.Resampling.LANCZOS)
    else:
        rendered = render_label('Prévia')
    output = BytesIO()
    rendered.save(output, format='PNG')
    return output.getvalue()


def thumbnail(ident: str, manifest: dict, picture: bytes | None) -> Path:
    content = (json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode('utf-8') + (picture or b''))
    digest = sha256(content).hexdigest()
    path = thumbnail_root() / f'{ident}-{digest[:24]}.png'
    _safe_path(path)
    if not path.is_file():
        data = _preview_png(manifest, picture)
        presets._atomic_new(path, data)
    return path


def gallery_items() -> list[dict]:
    meta = _read_meta()
    results = []
    for file in sorted(presets.presets_dir().glob('*.json')):
        ident = file.stem
        try:
            manifest, picture = presets._read(ident)
            path = thumbnail(ident, manifest, picture)
        except (OSError, ValueError):
            continue
        props = meta.get(ident, {'favorite': False, 'category': ''})
        results.append({'id': ident, 'name': manifest['name'], 'has_image': picture is not None,
                        **props, 'thumbnail': str(path)})
    return sorted(results, key=lambda x: (not x['favorite'], x['name'].casefold(), x['id']))


def filter_items(items: list[dict], query: str = '', favorites_only: bool = False, category: str = '') -> list[dict]:
    if not isinstance(query, str) or type(favorites_only) is not bool:
        raise ValueError('Filtro inválido')
    wanted = query.strip().casefold()
    category = _category(category)
    return [item for item in items if (
        (not favorites_only or item['favorite'])
        and (not category or item['category'] == category)
        and (not wanted or wanted in item['name'].casefold() or wanted in item['category'].casefold())
    )]
