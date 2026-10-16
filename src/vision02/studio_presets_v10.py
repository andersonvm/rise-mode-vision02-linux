"""Biblioteca de presets de aparência — sem ações, IPC ou acesso HID.

Presets: JSON+PNG em XDG_CONFIG_HOME/vision02/presets.
Imagens aplicadas: assets imutáveis em XDG_DATA_HOME/vision02/preset-assets.
Exportação: ZIP contendo somente preset.json e image.png opcional.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image, ImageOps
import yaml

from vision02.profiles.loader import parse_appearance

FORMAT = 'vision02-appearance-preset/v1'
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_BUNDLE_BYTES = 6 * 1024 * 1024
MAX_PIXELS = 4_000_000
ID_PATTERN = re.compile(r'[a-z0-9][a-z0-9-]{0,59}\Z')


def _directory(env_name: str, fallback: Path, suffix: str) -> Path:
    home = Path(os.environ.get(env_name, str(fallback))).expanduser()
    path = home / 'vision02' / suffix
    for parent in (home, home / 'vision02', path):
        if parent.is_symlink():
            raise ValueError('Diretório de presets não pode ser link simbólico')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def presets_dir() -> Path:
    return _directory('XDG_CONFIG_HOME', Path.home() / '.config', 'presets')


def assets_dir() -> Path:
    return _directory('XDG_DATA_HOME', Path.home() / '.local/share', 'preset-assets')


def _ident(value: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError('Identificador de preset inválido')
    return value


def _name(value: str) -> str:
    if not isinstance(value, str) or not (1 <= len(value.strip()) <= 60):
        raise ValueError('Nome deve conter entre 1 e 60 caracteres')
    name = value.strip()
    if any(ord(c) < 32 or c in '/\\' for c in name):
        raise ValueError('Nome de preset contém caracteres inválidos')
    return name


def _slug(name: str) -> str:
    raw = unicodedata.normalize('NFKD', _name(name)).encode('ascii', 'ignore').decode().lower()
    slug = re.sub('[^a-z0-9]+', '-', raw).strip('-')[:55].rstrip('-')
    if not slug:
        raise ValueError('O nome precisa conter letras ou números')
    return _ident(slug)


def _file_for(ident: str) -> Path:
    return presets_dir() / (_ident(ident) + '.json')


def _png_from_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError('Imagem inexistente, link ou grande demais')
    with Image.open(path) as opened:
        width, height = opened.size
        if not width or not height or width * height > MAX_PIXELS:
            raise ValueError('Dimensões da imagem excedem o limite')
        image = ImageOps.exif_transpose(opened).convert('RGBA')
        out = BytesIO()
        image.save(out, format='PNG')
    raw = out.getvalue()
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError('Imagem PNG excede 5 MiB')
    return raw


def _validate_png(raw: bytes) -> bytes:
    if not isinstance(raw, bytes) or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError('Imagem do preset inválida ou muito grande')
    with Image.open(BytesIO(raw)) as image:
        if image.format != 'PNG' or not image.width or not image.height or image.width * image.height > MAX_PIXELS:
            raise ValueError('Imagem PNG inválida')
        image.load()
    return raw


def _style(raw):
    if raw is None:
        return None
    if not isinstance(raw, dict) or 'action' in raw or 'label' in raw:
        raise ValueError('Aparência inválida')
    style = parse_appearance(raw)
    if style is None:
        raise ValueError('Aparência inválida')
    return vars(style)


def _manifest(name: str, style, image_sha: str | None) -> dict:
    if image_sha is not None and (not isinstance(image_sha, str) or not re.fullmatch('[0-9a-f]{64}', image_sha)):
        raise ValueError('Checksum de imagem inválido')
    return {'format': FORMAT, 'name': _name(name), 'appearance': _style(style),
            'image_sha256': image_sha}


def _json_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')


def _atomic_new(path: Path, raw: bytes) -> None:
    # Publica sem substituir outro preset e sem seguir links simbólicos.
    fd, tmpname = tempfile.mkstemp(prefix='.vision02-preset-', dir=path.parent)
    tmp = Path(tmpname)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o600)
        os.link(tmp, path)  # falha caso destino já exista, inclusive symlink
    finally:
        tmp.unlink(missing_ok=True)


def _atomic_replace(path: Path, raw: bytes) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError('Preset inexistente ou link simbólico')
    fd, tmpname = tempfile.mkstemp(prefix='.vision02-preset-', dir=path.parent)
    tmp = Path(tmpname)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o600)
        if path.is_symlink():
            raise ValueError('Preset passou a ser link simbólico')
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _read(ident: str) -> tuple[dict, bytes | None]:
    path = _file_for(ident)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 12000:
        raise ValueError('Preset inexistente ou arquivo inválido')
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise ValueError('JSON do preset inválido') from exc
    if not isinstance(payload, dict) or set(payload) != {'format', 'name', 'appearance', 'image_sha256'} or payload['format'] != FORMAT:
        raise ValueError('Formato de preset incompatível')
    validated = _manifest(payload['name'], payload['appearance'], payload['image_sha256'])
    image = None
    if validated['image_sha256']:
        img_path = presets_dir() / (ident + '.png')
        if img_path.is_symlink() or not img_path.is_file() or img_path.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError('Imagem do preset indisponível')
        image = _validate_png(img_path.read_bytes())
        if sha256(image).hexdigest() != validated['image_sha256']:
            raise ValueError('Checksum da imagem do preset divergente')
    return validated, image


def list_presets() -> list[dict]:
    result = []
    for path in sorted(presets_dir().glob('*.json')):
        try:
            manifest, image = _read(path.stem)
            result.append({'id': path.stem, 'name': manifest['name'], 'has_image': image is not None})
        except ValueError:
            continue
    return sorted(result, key=lambda p: p['name'].casefold())


def _publish(name: str, appearance, picture: bytes | None) -> dict:
    ident = _slug(name)
    if picture is not None:
        picture = _validate_png(picture)
    manifest = _manifest(name, appearance, sha256(picture).hexdigest() if picture else None)
    image_path = presets_dir() / (ident + '.png')
    if _file_for(ident).exists() or _file_for(ident).is_symlink() or image_path.exists() or image_path.is_symlink():
        raise ValueError('Já existe um preset com esse identificador')
    try:
        if picture:
            _atomic_new(image_path, picture)
        _atomic_new(_file_for(ident), _json_bytes(manifest))
    except BaseException:
        if not _file_for(ident).exists():
            image_path.unlink(missing_ok=True)
        raise
    return {'id': ident, 'name': manifest['name']}


def create_preset(name: str, profile_path: Path, source_key: int, expected_sha: str) -> dict:
    if type(source_key) is not int or not 1 <= source_key <= 15:
        raise ValueError('Tecla de origem inválida')
    if profile_path.is_symlink() or not profile_path.is_file():
        raise ValueError('Perfil inválido')
    raw = profile_path.read_bytes()
    if not isinstance(expected_sha, str) or sha256(raw).hexdigest() != expected_sha:
        raise RuntimeError('O perfil mudou. Recarregue antes de salvar o preset.')
    data = yaml.safe_load(raw)
    key = data.get('keys', {}).get(source_key) if isinstance(data, dict) else None
    if not isinstance(key, dict) or not isinstance(key.get('action'), dict):
        raise ValueError('A origem precisa estar configurada')
    picture = None
    if key.get('image'):
        source = Path(key['image']).expanduser()
        if not source.is_absolute():
            source = profile_path.parent / source
        picture = _png_from_file(source)
    return _publish(name, key.get('appearance'), picture)


def rename_preset(ident: str, name: str) -> dict:
    manifest, _ = _read(ident)
    manifest['name'] = _name(name)
    _atomic_replace(_file_for(ident), _json_bytes(manifest))
    return {'id': ident, 'name': manifest['name']}


def delete_preset(ident: str) -> dict:
    _read(ident)
    # Verificar todos os caminhos antes de apagar qualquer arquivo.
    img = presets_dir() / (ident + '.png')
    if img.is_symlink():
        raise ValueError('Imagem de preset é link simbólico')
    # Ativos aplicados não apontam para este arquivo, e sim para assets imutáveis.
    _file_for(ident).unlink()
    img.unlink(missing_ok=True)
    return {'id': ident}


def _asset(picture: bytes) -> Path:
    digest = sha256(picture).hexdigest()
    path = assets_dir() / (digest + '.png')
    if path.is_symlink():
        raise ValueError('Imagem persistente é link simbólico')
    if path.exists():
        if path.read_bytes() != picture:
            raise ValueError('Imagem persistente possui conteúdo divergente')
    else:
        _atomic_new(path, picture)
    return path


def preset_yaml(original: bytes, manifest: dict, image_path: Path | None, targets: list[int]) -> bytes:
    if not isinstance(targets, list) or not targets or len(targets) > 15 or any(
        type(k) is not int or not 1 <= k <= 15 for k in targets
    ) or len(set(targets)) != len(targets):
        raise ValueError('Selecione de uma a 15 teclas de destino')
    data = yaml.safe_load(original)
    if not isinstance(data, dict) or not isinstance(data.get('keys'), dict):
        raise ValueError('Perfil inválido')
    for key_id in targets:
        key = data['keys'].get(key_id)
        if not isinstance(key, dict) or not isinstance(key.get('action'), dict):
            raise ValueError(f'Tecla {key_id:02d} não configurada')
    for key_id in targets:
        key = data['keys'][key_id]
        if image_path is None:
            key.pop('image', None)
        else:
            key['image'] = str(image_path)
        if manifest['appearance'] is None:
            key.pop('appearance', None)
        else:
            key['appearance'] = deepcopy(manifest['appearance'])
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=90).encode('utf-8')


def apply_preset(ident: str, profile_path: Path, targets: list[int], expected_sha: str,
                 validate, backup_dir: Path | None = None) -> dict:
    """`validate(path, payload)` cria YAML temporário no mesmo diretório e valida renderização."""
    manifest, picture = _read(ident)
    if profile_path.is_symlink() or not profile_path.is_file():
        raise ValueError('Perfil inválido')
    original = profile_path.read_bytes()
    if sha256(original).hexdigest() != expected_sha:
        raise RuntimeError('O perfil mudou no disco; recarregue antes de aplicar.')
    # Validar destinos antes de publicar asset e criar backup.
    draft = preset_yaml(original, manifest, None, targets)
    del draft
    image_path = _asset(picture) if picture is not None else None
    payload = preset_yaml(original, manifest, image_path, targets)
    temp, _ = validate(profile_path, payload)
    try:
        if profile_path.is_symlink() or profile_path.read_bytes() != original:
            raise RuntimeError('O perfil mudou durante a gravação')
        storage = backup_dir or (Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state'))
                                 / 'vision02' / 'editor-backups')
        if storage.is_symlink():
            raise ValueError('Diretório de backup inválido')
        storage.mkdir(parents=True, exist_ok=True, mode=0o700)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = storage / f'{profile_path.stem}-preset-v10-{stamp}-{sha256(original).hexdigest()[:12]}.yaml'
        _atomic_new(backup, original)
        os.chmod(temp, profile_path.stat().st_mode & 0o777)
        os.replace(temp, profile_path)
        temp = None
        return {'ok': True, 'backup': str(backup), 'sha256': sha256(payload).hexdigest(),
                'targets': sorted(targets), 'id': ident}
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def export_preset(ident: str, target: Path) -> dict:
    manifest, picture = _read(ident)
    if target.suffix.lower() != '.zip' or target.is_symlink() or target.exists():
        raise ValueError('Selecione um arquivo ZIP novo para exportar')
    if not target.parent.is_dir():
        raise ValueError('Diretório de exportação inválido')
    fd, tmpname = tempfile.mkstemp(prefix='.vision02-export-', dir=target.parent)
    tmp = Path(tmpname)
    try:
        with os.fdopen(fd, 'wb') as stream:
            with ZipFile(stream, 'w', compression=ZIP_DEFLATED) as archive:
                archive.writestr('preset.json', _json_bytes(manifest))
                if picture:
                    archive.writestr('image.png', picture)
        os.chmod(tmp, 0o600)
        os.link(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return {'path': str(target)}


def import_preset(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BUNDLE_BYTES:
        raise ValueError('Pacote ZIP inválido')
    with ZipFile(path, 'r') as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if names not in (['preset.json'], ['preset.json', 'image.png']):
            raise ValueError('ZIP deve conter somente preset.json e image.png')
        if any(info.file_size > MAX_IMAGE_BYTES or info.is_dir() for info in infos):
            raise ValueError('Arquivo interno muito grande')
        raw = archive.read('preset.json')
        if len(raw) > 12000:
            raise ValueError('Manifesto muito grande')
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {'format', 'name', 'appearance', 'image_sha256'} or payload['format'] != FORMAT:
            raise ValueError('Formato inválido')
        manifest = _manifest(payload['name'], payload['appearance'], payload['image_sha256'])
        picture = _validate_png(archive.read('image.png')) if 'image.png' in names else None
        if bool(picture) != bool(manifest['image_sha256']):
            raise ValueError('Imagem ausente ou inesperada')
        if picture and sha256(picture).hexdigest() != manifest['image_sha256']:
            raise ValueError('Checksum do ZIP divergente')
    return _publish(manifest['name'], manifest['appearance'], picture)


def preview_data(ident: str) -> tuple[dict, Path | None]:
    manifest, picture = _read(ident)
    path = presets_dir() / (ident + '.png') if picture else None
    return manifest, path
