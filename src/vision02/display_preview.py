"""Espelho somente-leitura do último quadro enviado a cada LCD.

O processo USB/HID é o único produtor. Os arquivos são PNG já orientados para
visualização, reconstruídos do JPEG efetivamente codificado para transmissão.
O IPC publica apenas caminhos privados, nunca os bytes no socket de controle.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import stat
import tempfile

from PIL import Image

from .display import encode_image
from .protocol import DISPLAY_COUNT, physical_key_to_display_id


DISPLAY_TO_KEY = {
    physical_key_to_display_id(key): key for key in range(1, DISPLAY_COUNT + 1)
}


def preview_root() -> Path:
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if not runtime:
        raise RuntimeError('XDG_RUNTIME_DIR ausente; prévia dinâmica indisponível')
    return Path(runtime) / 'vision02' / 'display-preview'


class DisplayPreview:
    """Estado publicado depois de uma transmissão HID concluída com sucesso."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else preview_root()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise PermissionError('Diretório de prévias inválido')
        self.root.chmod(0o700)
        self.revision = 0
        self._hashes: dict[int, bytes] = {}
        self._failed = False
        # Não expor quadros obsoletos de uma sessão anterior.
        for key in range(1, DISPLAY_COUNT + 1):
            path = self.root / f'key-{key:02d}.png'
            if path.is_symlink():
                raise PermissionError('Prévia não pode ser link simbólico')
            path.unlink(missing_ok=True)

    def record(self, display_id: int, source, *, quality: int = 90, subsampling: int = 0) -> None:
        """Chamada APÓS set_image() retornar sem exceção, pela thread HID."""
        physical_key = DISPLAY_TO_KEY[display_id]
        wire_jpeg = encode_image(source, quality=quality, subsampling=subsampling)
        # O firmware exibe o JPEG girado 180º: desfazer para a GUI.
        with Image.open(BytesIO(wire_jpeg)) as decoded:
            upright = decoded.convert('RGB').transpose(Image.Transpose.ROTATE_180)
            output = BytesIO()
            upright.save(output, format='PNG')
        png = output.getvalue()
        digest = sha256(png).digest()
        destination = self.root / f'key-{physical_key:02d}.png'
        if self._hashes.get(physical_key) == digest and destination.is_file():
            return
        fd, temporary = tempfile.mkstemp(prefix='.vision02-frame-', dir=self.root)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(png)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self._hashes[physical_key] = digest
        self.revision += 1

    def unavailable(self) -> None:
        """Não retornar imagens antigas se uma captura falhar."""
        self._failed = True

    def manifest(self, active: str) -> dict:
        if self._failed:
            return {'active': active, 'available': False, 'revision': self.revision, 'images': {}}
        images = {
            str(key): str(self.root / f'key-{key:02d}.png')
            for key in sorted(self._hashes)
            if (self.root / f'key-{key:02d}.png').is_file()
        }
        return {
            'active': active,
            'available': len(images) == DISPLAY_COUNT,
            'revision': self.revision,
            'images': images,
        }


class MirroredDevice:
    """Delegação sem segunda conexão USB ou mudança no driver."""

    def __init__(self, device, preview: DisplayPreview):
        self._device = device
        self.preview = preview

    def __getattr__(self, name):
        return getattr(self._device, name)

    def set_images_batch(self, sources, *, quality=90, subsampling=0):
        # Publicar os quadros apenas após o STP final do lote.
        result = self._device.set_images_batch(
            sources, quality=quality, subsampling=subsampling,
        )
        try:
            for display_id, source in sorted(sources.items()):
                self.preview.record(
                    display_id, source, quality=quality, subsampling=subsampling,
                )
        except Exception as exc:
            self.preview.unavailable()
            print(f'[Vision02] Espelho dos LCDs indisponível: {exc}', flush=True)
        return result

    def set_image(self, display_id, source, *, quality=90, subsampling=0, skip_unchanged=False):
        # A falha HID deve continuar sendo propagada ao supervisor.
        result = self._device.set_image(
            display_id, source, quality=quality, subsampling=subsampling,
            skip_unchanged=skip_unchanged,
        )
        try:
            self.preview.record(display_id, source, quality=quality, subsampling=subsampling)
        except Exception as exc:  # Falha na prévia jamais deve derrubar o controlador HID.
            self.preview.unavailable()
            print(f'[Vision02] Espelho dos LCDs indisponível: {exc}', flush=True)
        return result
