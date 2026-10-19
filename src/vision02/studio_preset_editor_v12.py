"""Editor seguro de presets v12: rascunho, prévia e salvamento explícito.

Não abre perfis, não altera ações, não se comunica com o dispositivo.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import fcntl
import os
import tempfile

from vision02 import studio_presets_v10 as presets
from vision02.studio_preset_gallery_v11 import _preview_png, thumbnail_root
from vision02.profiles.models import KeyAppearance


def _checksum(manifest: dict, picture: bytes | None) -> str:
    return sha256(presets._json_bytes(manifest) + (picture or b'')).hexdigest()


def _revision(ident: str, expected: str | None = None) -> tuple[dict, bytes | None, str]:
    manifest, picture = presets._read(ident)
    revision = _checksum(manifest, picture)
    if expected is not None and (not isinstance(expected, str) or expected != revision):
        raise RuntimeError('O preset mudou no disco; recarregue antes de salvar.')
    return manifest, picture, revision


def load_draft(ident: str) -> dict:
    manifest, picture, revision = _revision(ident)
    image_path = str(presets.presets_dir() / (ident + '.png')) if picture else ''
    return {'id': ident, 'name': manifest['name'], 'appearance': manifest['appearance'],
            'image': image_path, 'revision': revision}


def _contents(ident: str, image: str, existing_picture: bytes | None) -> bytes | None:
    if not isinstance(image, str) or len(image) > 4096 or '\x00' in image:
        raise ValueError('Caminho da imagem inválido')
    if not image:
        return None
    original = presets.presets_dir() / (ident + '.png')
    if Path(image) == original:
        if existing_picture is None:
            raise ValueError('Imagem original não está disponível')
        return existing_picture
    return presets._png_from_file(Path(image).expanduser())


def _prepare(ident: str, expected: str, appearance: dict | None, image: str):
    old_manifest, old_picture, revision = _revision(ident, expected)
    style = presets._style(appearance)
    picture = _contents(ident, image, old_picture)
    manifest = presets._manifest(old_manifest['name'], style,
                                 sha256(picture).hexdigest() if picture else None)
    return old_manifest, old_picture, manifest, picture, revision


def _preview_path(manifest: dict, picture: bytes | None) -> Path:
    raw = _preview_png(manifest, picture)
    path = thumbnail_root() / ('editor-v12-' + sha256(raw).hexdigest() + '.png')
    if path.is_symlink():
        raise ValueError('Prévia não pode ser link simbólico')
    if not path.exists():
        presets._atomic_new(path, raw)
    return path


def preview_draft(id: str, revision: str, appearance: dict | None, image: str) -> dict:
    _, _, manifest, picture, _ = _prepare(id, revision, appearance, image)
    return {'id': id, 'image': str(_preview_path(manifest, picture))}


@contextmanager
def _locked():
    path = presets.presets_dir() / '.editor-v12.lock'
    if path.is_symlink():
        raise ValueError('Lock não pode ser link simbólico')
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'rb+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _restore_file(path: Path, original: bytes | None) -> None:
    if original is None:
        if path.is_symlink():
            raise ValueError('Destino tornou-se link simbólico')
        path.unlink(missing_ok=True)
    elif path.exists():
        presets._atomic_replace(path, original)
    else:
        presets._atomic_new(path, original)


def save_draft(id: str, revision: str, appearance: dict | None, image: str,
               *, save_as: str | None = None) -> dict:
    ident = id
    expected = revision
    with _locked():
        old_manifest, old_picture, manifest, picture, revision = _prepare(
            ident, expected, appearance, image)
        if save_as is not None:
            result = presets._publish(save_as, manifest['appearance'], picture)
            result['saved_as'] = True
            result['revision'] = _revision(result['id'])[2]
            return result
        previous_json = presets._json_bytes(old_manifest)
        file_json = presets._file_for(ident)
        file_image = presets.presets_dir() / (ident + '.png')
        if file_json.is_symlink() or file_image.is_symlink():
            raise ValueError('Arquivos de preset não podem ser links simbólicos')
        # v10 utiliza manifest.json + image.png. Não há transação multi-arquivo
        # atômica; em exceções normais restauramos ambos. Mantemos cópia privada.
        backup_root = presets.presets_dir() / '.editor-v12-backups'
        if backup_root.is_symlink():
            raise ValueError('Backup não pode ser link simbólico')
        backup_root.mkdir(mode=0o700, exist_ok=True)
        backup = Path(tempfile.mkdtemp(prefix=ident + '-', dir=backup_root))
        os.chmod(backup, 0o700)
        presets._atomic_new(backup / 'preset.json', previous_json)
        if old_picture is not None:
            presets._atomic_new(backup / 'image.png', old_picture)
        try:
            # Antes de publicar, confirmar que o conteúdo lido ainda corresponde
            # à revisão aprovada (inclusive após a preparação do backup).
            _revision(ident, revision)
            if picture is None:
                file_image.unlink(missing_ok=True)
            elif file_image.exists():
                presets._atomic_replace(file_image, picture)
            else:
                presets._atomic_new(file_image, picture)
            presets._atomic_replace(file_json, presets._json_bytes(manifest))
            validated, valid_image = presets._read(ident)
            if _checksum(validated, valid_image) != _checksum(manifest, picture):
                raise RuntimeError('Verificação do preset salvo falhou')
        except BaseException:
            # Não mascarar erro original caso uma restauração também falhe.
            try:
                _restore_file(file_image, old_picture)
                _restore_file(file_json, previous_json)
            except BaseException as restore_error:
                raise RuntimeError(f'Falha na restauração; backup preservado em {backup}') from restore_error
            raise
        return {'id': ident, 'name': manifest['name'], 'saved_as': False,
                'revision': _checksum(manifest, picture), 'backup': str(backup),
                'image': str(file_image) if picture else ''}
