"""Visual editor for OBS scene/audio key layouts; no device or OBS writes.

Uses a catalog-wide lock/version and validates ALL profiles before replacing one
YAML, with an exact backup and atomic replacement. Audio mixer calls are separate.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path

import yaml

from .obs_profile_bundle import SCENES, AUDIO
from .profile_catalog import ProfileCatalog, _atomic_write, _state_root

LIMITS = {SCENES: 14, AUDIO: 12}


def _validate_map(profile: str, mapping: dict) -> dict[int, str | None]:
    if profile not in LIMITS:
        raise ValueError('Somente os perfis OBS — Cenas e OBS — Áudio são editáveis aqui')
    limit = LIMITS[profile]
    if not isinstance(mapping, dict) or set(mapping) != {str(i) for i in range(1, limit + 1)}:
        raise ValueError('O layout deve incluir todas as posições editáveis')
    parsed = {}
    names = set()
    for i in range(1, limit + 1):
        value = mapping[str(i)]
        if value is not None:
            if not isinstance(value, str) or not value or value != value.strip() or len(value) > 128 or any(ord(char) < 32 for char in value):
                raise ValueError(f'Nome inválido na tecla {i:02d}')
            if value in names:
                raise ValueError(f'Fonte/cena duplicada: {value}')
            names.add(value)
        parsed[i] = value
    return parsed


def _lookup(raw: dict[Path, bytes], profile: str) -> tuple[Path, dict]:
    found = []
    for path, value in raw.items():
        doc = yaml.safe_load(value)
        if isinstance(doc, dict) and doc.get('name') == profile:
            found.append((path, doc))
    if len(found) != 1:
        raise ValueError(f'Perfil não encontrado ou duplicado: {profile}')
    return found[0]


def inspect_layout(profile: str, *, catalog: ProfileCatalog | None = None) -> dict:
    if profile not in LIMITS:
        raise ValueError('Perfil não configurável neste editor')
    catalog = catalog or ProfileCatalog()
    raw = catalog._raw()
    catalog._validate(raw)
    path, doc = _lookup(raw, profile)
    entries = {}
    for i in range(1, LIMITS[profile] + 1):
        conf = doc.get('keys', {}).get(i, {})
        action = conf.get('action') or {}
        name = None
        if profile == SCENES and action.get('type') == 'obs' and action.get('operation') == 'scene_name':
            name = action.get('scene')
        if profile == AUDIO and action.get('type') == 'obs' and action.get('operation') in ('toggle_mic', 'toggle_desktop'):
            name = action.get('input')
        entries[str(i)] = name
    return {'ok': True, 'profile': profile, 'file': path.name,
            'version': catalog._version(raw), 'entries': entries,
            'limit': LIMITS[profile]}


def save_layout(profile: str, mapping: dict, version: str, *, catalog: ProfileCatalog | None = None) -> dict:
    entries = _validate_map(profile, mapping)
    if not isinstance(version, str) or len(version) != 64:
        raise ValueError('Versão do catálogo obrigatória')
    catalog = catalog or ProfileCatalog()
    with catalog._locked():
        original = catalog._raw()
        if catalog._version(original) != version:
            raise RuntimeError('Outro editor alterou os perfis; recarregue antes de salvar')
        catalog._validate(original)
        path, doc = _lookup(original, profile)
        existing = doc.setdefault('keys', {})
        if not isinstance(existing, dict):
            raise ValueError('Teclas inválidas no perfil')
        for i, name in entries.items():
            if name is None:
                existing.pop(i, None)
                continue
            old_key = existing.get(i, {})
            if not isinstance(old_key, dict):
                raise ValueError(f'Tecla {i:02d} inválida')
            key = dict(old_key)
            key['label'] = name[:70]
            if profile == SCENES:
                key['action'] = {'type': 'obs', 'operation': 'scene_name', 'scene': name}
            else:
                key['action'] = {'type': 'obs', 'operation': 'toggle_mic', 'input': name}
            existing[i] = key
        # Navigation and all other profiles are untouched.
        replacement = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=100).encode('utf-8')
        if replacement == original[path]:
            return {'ok': True, 'unchanged': True, 'version': version}
        candidate = {**original, path: replacement}
        catalog._validate(candidate)  # Entire catalog, including cross-profile references.
        if path.read_bytes() != original[path] or catalog._raw() != original:
            raise RuntimeError('Arquivo alterado durante a edição; nada foi salvo')
        backup_dir = _state_root() / 'editor-backups'
        backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = backup_dir / f'{path.stem}-visual-{stamp}-{hashlib.sha256(original[path]).hexdigest()[:12]}.yaml'
        with backup.open('xb') as fp:
            os.fchmod(fp.fileno(), 0o600)
            fp.write(original[path])
            fp.flush()
            os.fsync(fp.fileno())
        try:
            _atomic_write(path, replacement)
        except BaseException:
            _atomic_write(path, original[path])
            raise
        return {'ok': True, 'backup': str(backup), 'path': str(path),
                'version': catalog._version({**original, path: replacement}),
                'count': sum(value is not None for value in entries.values())}
