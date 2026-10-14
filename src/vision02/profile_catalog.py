"""Catálogo pessoal e preferências da Vision 02; nunca abre USB/HID.

Todas as mutações usam lock, validação do conjunto, backup e substituição atômica
por arquivo. O conjunto é restaurado em caso de erro; não há atomicidade
multi-arquivo contra desligamento abrupto (o backup permanece para recuperação).
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata

import yaml

from .profiles import ProfileManager, validate_profile_targets, load_profile
from .user_profiles import config_profile_dir


MAX_PROFILES = 64


def _config_root() -> Path:
    return config_profile_dir().parent


def _state_root() -> Path:
    return Path(os.environ.get('XDG_STATE_HOME') or (Path.home() / '.local/state')).expanduser() / 'vision02'


def _check_name(name: str) -> str:
    if not isinstance(name, str) or not 1 <= len(name) <= 80 or not name.strip() == name:
        raise ValueError('Nome do perfil deve ter entre 1 e 80 caracteres, sem espaços nas extremidades')
    if any(ord(ch) < 32 or ch in '/\\' for ch in name):
        raise ValueError('Nome do perfil contém caracteres inválidos')
    return name


def _slug(name: str) -> str:
    plain = unicodedata.normalize('NFKD', name)
    ascii_name = plain.encode('ascii', 'ignore').decode('ascii').lower()
    stem = re.sub(r'[^a-z0-9]+', '-', ascii_name).strip('-')[:60]
    return stem or 'perfil'


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError(f'Caminho simbólico não permitido: {path}')
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.vision02-', suffix='.tmp')
    tmp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _load_json(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError('Arquivo de configuração não pode ser symlink')
    if not path.exists():
        return {}
    result = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(result, dict):
        raise ValueError(f'Configuração inválida: {path}')
    return result


def read_settings() -> dict:
    data = _load_json(_config_root() / 'settings.json')
    startup = data.get('startup_profile')
    restore = data.get('restore_last', True)
    if startup is not None:
        _check_name(startup)
    if not isinstance(restore, bool):
        raise ValueError('restore_last deve ser booleano')
    return {'startup_profile': startup, 'restore_last': restore}


def read_last_active() -> str | None:
    data = _load_json(_state_root() / 'last-profile.json')
    value = data.get('active')
    if value is None:
        return None
    return _check_name(value)


def write_last_active(name: str) -> None:
    _atomic_write(_state_root() / 'last-profile.json', json.dumps({'active': _check_name(name)}, ensure_ascii=False).encode('utf-8'))


def choose_initial(names: tuple[str, ...] | list[str]) -> str:
    if not names:
        raise ValueError('Nenhum perfil disponível')
    settings = read_settings()
    if settings['restore_last']:
        candidate = read_last_active()
        if candidate in names:
            return candidate
    if settings['startup_profile'] in names:
        return settings['startup_profile']
    return names[0]


class ProfileCatalog:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else config_profile_dir()

    def paths(self) -> tuple[Path, ...]:
        if not self.root.is_dir():
            return ()
        entries = tuple(sorted(self.root.glob('*.yaml')))
        if len(entries) > MAX_PROFILES:
            raise ValueError(f'Limite de {MAX_PROFILES} perfis excedido')
        for path in entries:
            if path.is_symlink() or not path.is_file():
                raise ValueError(f'YAML deve ser arquivo regular: {path}')
        return entries

    def _raw(self) -> dict[Path, bytes]:
        return {path: path.read_bytes() for path in self.paths()}

    @staticmethod
    def _version(data: dict[Path, bytes]) -> str:
        digest = hashlib.sha256()
        for path, content in sorted(data.items()):
            digest.update(path.name.encode('utf-8') + b'\0')
            digest.update(hashlib.sha256(content).digest())
        return digest.hexdigest()

    def _validate(self, candidate: dict[Path, bytes]) -> tuple[str, ...]:
        if not 1 <= len(candidate) <= MAX_PROFILES:
            raise ValueError('É necessário manter entre 1 e 64 perfis')
        temps = []
        manager = ProfileManager()
        try:
            for path, content in sorted(candidate.items()):
                if path.parent != self.root or path.suffix != '.yaml':
                    raise ValueError('Caminho de perfil fora do catálogo')
                fd, name = tempfile.mkstemp(prefix='.vision02-check-', suffix='.tmp', dir=self.root)
                tmp = Path(name)
                temps.append(tmp)
                with os.fdopen(fd, 'wb') as file:
                    file.write(content)
                manager.register(load_profile(tmp))
            validate_profile_targets(manager)
            return manager.list_profiles()
        finally:
            for tmp in temps:
                tmp.unlink(missing_ok=True)

    def snapshot(self) -> dict:
        raw = self._raw()
        names = self._validate(raw) if raw else ()
        info = []
        for path in self.paths():
            profile = load_profile(path)
            info.append({'name': profile.name, 'file': path.name, 'keys': len(profile.keys)})
        return {'profiles': info, 'version': self._version(raw), 'settings': read_settings()}

    @contextmanager
    def _locked(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink():
            raise ValueError('Diretório de perfis não pode ser symlink')
        lock = self.root / '.catalog.lock'
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _mutate(self, expected: str, kind: str, name: str, *, target: str | None = None, active: str | None = None) -> dict:
        _check_name(name)
        if target is not None:
            _check_name(target)
        with self._locked():
            old = self._raw()
            if expected != self._version(old):
                raise RuntimeError('Catálogo alterado no disco. Atualize a janela antes de salvar.')
            if old:
                self._validate(old)
            data = {p: yaml.safe_load(content) for p, content in old.items()}
            initial_data = copy.deepcopy(data)
            by_name = {item['name']: path for path, item in data.items()}
            if len(by_name) != len(data):
                raise ValueError('Nomes duplicados no catálogo')
            if kind in ('create', 'duplicate'):
                if name in by_name:
                    raise ValueError(f'Já existe um perfil chamado {name}')
                filename = self.root / (_slug(name) + '.yaml')
                if filename in data:
                    raise ValueError(f'Arquivo {filename.name} já existe')
                if kind == 'duplicate':
                    if target not in by_name:
                        raise ValueError('Perfil de origem inexistente')
                    source = dict(data[by_name[target]])
                    source['name'] = name
                    data[filename] = source
                else:
                    data[filename] = {'version': 1, 'name': name, 'keys': {}}
            elif kind == 'rename':
                if name not in by_name:
                    raise ValueError('Perfil a renomear não encontrado')
                if target in by_name or target is None:
                    raise ValueError('Novo nome indisponível')
                if active == name:
                    raise ValueError('Ative outro perfil antes de renomear o perfil em uso')
                data[by_name[name]]['name'] = target
                for profile in data.values():
                    for key in profile.get('keys', {}).values():
                        action = key.get('action', {})
                        if action.get('type') == 'profile' and action.get('target') == name:
                            action['target'] = target
            elif kind == 'delete':
                if name not in by_name:
                    raise ValueError('Perfil a excluir não encontrado')
                if active == name:
                    raise ValueError('Ative outro perfil antes de excluir o perfil em uso')
                for profile_name, item in ((p['name'], p) for p in data.values()):
                    if profile_name == name:
                        continue
                    for key in item.get('keys', {}).values():
                        act = key.get('action', {})
                        if act.get('type') == 'profile' and act.get('target') == name:
                            raise ValueError(f'Exclusão bloqueada: {profile_name} referencia {name}')
                del data[by_name[name]]
            else:
                raise ValueError('Operação desconhecida')
            candidate = {
                p: old[p] if p in old and initial_data[p] == item
                else yaml.safe_dump(item, allow_unicode=True, sort_keys=False).encode('utf-8')
                for p, item in data.items()
            }
            names = self._validate(candidate)
            backups = _state_root() / 'profile-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backups.mkdir(parents=True, exist_ok=False, mode=0o700)
            for path, content in old.items():
                _atomic_write(backups / path.name, content)
            try:
                if self._raw() != old:
                    raise RuntimeError("Catálogo modificado por outro editor durante a operação")
                for path, content in candidate.items():
                    if old.get(path) != content:
                        _atomic_write(path, content)
                for path in old.keys() - candidate.keys():
                    path.unlink()
            except BaseException:
                for path, content in old.items():
                    _atomic_write(path, content)
                for path in candidate.keys() - old.keys():
                    path.unlink(missing_ok=True)
                raise
            # Preferências são corrigidas após a mutação principal.
            try:
                setting = read_settings()
                if kind == 'rename' and setting['startup_profile'] == name:
                    self.set_startup(target)
                elif kind == 'delete' and setting['startup_profile'] == name:
                    self.set_startup(names[0])
                if kind == 'rename' and read_last_active() == name:
                    write_last_active(target)
                elif kind == 'delete' and read_last_active() == name:
                    write_last_active(names[0])
            except Exception as exc:
                raise RuntimeError(f'Perfis alterados, mas a preferência não pôde ser atualizada: {exc}') from exc
            return {'ok': True, 'profiles': list(names), 'backup': str(backups), 'version': self._version(self._raw())}

    def create(self, name: str, expected: str) -> dict:
        return self._mutate(expected, 'create', name)

    def duplicate(self, source: str, new_name: str, expected: str) -> dict:
        return self._mutate(expected, 'duplicate', new_name, target=source)

    def rename(self, old_name: str, new_name: str, expected: str, *, active: str | None = None) -> dict:
        return self._mutate(expected, 'rename', old_name, target=new_name, active=active)

    def delete(self, name: str, expected: str, *, active: str | None = None) -> dict:
        return self._mutate(expected, 'delete', name, active=active)

    @staticmethod
    def set_startup(name: str, *, restore_last: bool | None = None) -> dict:
        _check_name(name)
        settings = read_settings()
        settings['startup_profile'] = name
        if restore_last is not None:
            if not isinstance(restore_last, bool):
                raise ValueError('restore_last deve ser booleano')
            settings['restore_last'] = restore_last
        _atomic_write(_config_root() / 'settings.json', json.dumps({'version': 1, **settings}, ensure_ascii=False, indent=2).encode('utf-8'))
        return settings
