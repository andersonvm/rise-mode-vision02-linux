"""Criação segura de perfis OBS especializados; não abre HID nem modifica OBS.

Perfis gerados: Controle, Cenas (até 14 por página) e Áudio (até 12 fontes).
Não sobrescreve perfis pessoais existentes. Criação protegida por lock do catálogo.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable
import os
import tempfile

import yaml

from .profile_catalog import ProfileCatalog

CONTROL = 'OBS — Controle'
SCENES = 'OBS — Cenas'
AUDIO = 'OBS — Áudio'
BUNDLE = (CONTROL, SCENES, AUDIO)
FILES = {CONTROL: 'obs-controle.yaml', SCENES: 'obs-cenas.yaml', AUDIO: 'obs-audio.yaml'}


def _names(values: Iterable[str], maximum: int, label: str) -> list[str]:
    if not isinstance(values, (list, tuple)) or len(values) > maximum:
        raise ValueError(f'{label}: máximo de {maximum} itens')
    names = []
    for value in values:
        if not isinstance(value, str) or not value or value != value.strip() or len(value) > 128 or any(ord(c) < 32 for c in value):
            raise ValueError(f'{label}: nome inválido')
        if value in names:
            raise ValueError(f'{label}: nome duplicado: {value}')
        names.append(value)
    return names


def _key(label: str, typ: str, **kwargs) -> dict:
    return {'label': label[:70], 'action': {'type': typ, **kwargs}}


def _profile(name: str, keys: dict[int, dict]) -> dict:
    return {'version': 1, 'name': name, 'keys': keys}


def build_bundle(scenes: list[str], inputs: list[str], *, legacy_present: bool = True) -> dict[str, dict]:
    """Apenas dados YAML. Nenhum comando é enviado ao OBS."""
    scenes = _names(scenes, 14, 'Cenas')
    inputs = _names(inputs, 12, 'Áudio')
    controls = {
        1: _key('Gravar', 'obs', operation='toggle_record'),
        2: _key('Pausar', 'obs', operation='toggle_pause'),
        3: _key('Ao vivo', 'obs', operation='toggle_stream'),
        4: _key('Microfone', 'obs', operation='toggle_mic'),
        5: _key('Desktop', 'obs', operation='toggle_desktop'),
        6: _key('Cam virtual', 'obs', operation='toggle_virtualcam'),
        7: _key('Cena +', 'obs', operation='next_scene'),
        8: _key('Cena -', 'obs', operation='previous_scene'),
        9: _key('Replay', 'obs', operation='save_replay'),
        10: _key('Captura', 'obs', operation='screenshot'),
        11: _key('Estado', 'obs', operation='refresh'),
        12: _key('Cenas', 'profile', target=SCENES),
        13: _key('Áudio', 'profile', target=AUDIO),
        15: _key('Sistema', 'profile', target='Sistema'),
    }
    if legacy_present:
        controls[14] = _key('OBS antigo', 'profile', target='OBS Studio')
    scenes_keys = {
        i: _key(scene, 'obs', operation='scene_name', scene=scene)
        for i, scene in enumerate(scenes, 1)
    }
    scenes_keys[15] = _key('Controle', 'profile', target=CONTROL)
    audio_keys = {
        i: _key(name, 'obs', operation='toggle_mic', input=name)
        for i, name in enumerate(inputs, 1)
    }
    audio_keys.update({
        13: _key('Cenas', 'profile', target=SCENES),
        14: _key('Controle', 'profile', target=CONTROL),
        15: _key('Sistema', 'profile', target='Sistema'),
    })
    return {
        CONTROL: _profile(CONTROL, controls),
        SCENES: _profile(SCENES, scenes_keys),
        AUDIO: _profile(AUDIO, audio_keys),
    }


def preview(catalog: ProfileCatalog | None = None) -> dict:
    catalog = catalog or ProfileCatalog()
    return catalog.snapshot()


def _exclusive_write(path: Path, payload: bytes) -> None:
    """Publica um YAML completo sem sobrescrever outro arquivo concorrente."""
    fd, filename = tempfile.mkstemp(prefix='.vision02-obs-', suffix='.tmp', dir=path.parent)
    tmp = Path(filename)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(tmp, 0o600)
        # hard-link falha se destino existir; os.replace sobrescreveria um YAML.
        os.link(tmp, path, follow_symlinks=False)
    finally:
        tmp.unlink(missing_ok=True)


def create_bundle(scenes: list[str], inputs: list[str], expected_version: str, *, catalog: ProfileCatalog | None = None) -> dict:
    """Cria três arquivos sem sobrescrita e valida o conjunto inteiro sob lock.

    Se ocorrer falha na gravação, remove apenas arquivos criados por esta chamada.
    """
    catalog = catalog or ProfileCatalog()
    if not isinstance(expected_version, str) or len(expected_version) != 64:
        raise ValueError('Versão esperada do catálogo ausente')
    with catalog._locked():
        old = catalog._raw()
        if expected_version != catalog._version(old):
            raise RuntimeError('Catálogo alterado no disco; atualize a janela antes de criar os perfis')
        if not old:
            raise ValueError('Catálogo vazio: instale o perfil Sistema antes de criar os perfis OBS')
        names = catalog._validate(old)
        if 'Sistema' not in names:
            raise ValueError('O perfil Sistema é necessário para a navegação')
        conflicts = set(names) & set(BUNDLE)
        if conflicts:
            raise ValueError('Perfis já existem; não serão sobrescritos: ' + ', '.join(sorted(conflicts)))
        data = build_bundle(scenes, inputs, legacy_present='OBS Studio' in names)
        new = {}
        for profile_name in BUNDLE:
            file = catalog.root / FILES[profile_name]
            if file.exists() or file.is_symlink():
                raise ValueError(f'Arquivo já existente: {file.name}')
            new[file] = yaml.safe_dump(data[profile_name], sort_keys=False, allow_unicode=True).encode('utf-8')
        catalog._validate({**old, **new})
        written = []
        try:
            for path, content in new.items():
                if path.exists() or path.is_symlink():
                    raise ValueError('Arquivo apareceu durante a criação: ' + str(path))
                _exclusive_write(path, content)
                written.append(path)
        except BaseException:
            for file in reversed(written):
                file.unlink(missing_ok=True)
            raise
        return {'ok': True, 'files': [str(p) for p in new], 'names': list(BUNDLE),
                'scenes': len(scenes), 'inputs': len(inputs)}
