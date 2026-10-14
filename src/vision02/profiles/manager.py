"""Gerenciamento de múltiplos perfis da Vision 02."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterable

from .loader import load_profile
from .models import Profile


class ProfileManagerError(RuntimeError):
    """Erro de gerenciamento de perfis."""


class ProfileManager:
    """Armazena perfis validados e controla o perfil ativo.

    Não executa ações e não acessa o dispositivo USB.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, Profile] = {}
        self._active_name: str | None = None
        self._lock = threading.RLock()

    def register(self, profile: Profile) -> None:
        """Registra um perfil previamente validado."""

        if not isinstance(profile, Profile):
            raise TypeError("profile deve ser uma instância de Profile")

        if not profile.name or not profile.name.strip():
            raise ProfileManagerError(
                "Nome do perfil não pode ser vazio"
            )

        with self._lock:
            if profile.name in self._profiles:
                raise ProfileManagerError(
                    f"Perfil já registrado: {profile.name}"
                )

            self._profiles[profile.name] = profile

            if self._active_name is None:
                self._active_name = profile.name

    def load(self, path: str | Path) -> Profile:
        """Carrega, valida e registra um arquivo YAML."""

        profile = load_profile(path)
        self.register(profile)
        return profile

    def load_many(
        self,
        paths: Iterable[str | Path],
    ) -> tuple[Profile, ...]:
        """Valida todos os arquivos antes de registrar qualquer um."""

        profiles = tuple(load_profile(path) for path in paths)

        names = [profile.name for profile in profiles]

        if len(names) != len(set(names)):
            raise ProfileManagerError(
                "Existem nomes de perfis duplicados"
            )

        with self._lock:
            duplicates = set(names).intersection(self._profiles)

            if duplicates:
                raise ProfileManagerError(
                    "Perfis já registrados: "
                    + ", ".join(sorted(duplicates))
                )

            for profile in profiles:
                self._profiles[profile.name] = profile

            if self._active_name is None and profiles:
                self._active_name = profiles[0].name

        return profiles

    @property
    def active(self) -> Profile:
        """Retorna o perfil atualmente selecionado."""

        with self._lock:
            if self._active_name is None:
                raise ProfileManagerError(
                    "Nenhum perfil ativo"
                )

            return self._profiles[self._active_name]

    @property
    def active_name(self) -> str | None:
        with self._lock:
            return self._active_name

    def list_profiles(self) -> tuple[str, ...]:
        """Lista os perfis registrados."""

        with self._lock:
            return tuple(self._profiles)

    def switch(self, name: str) -> Profile:
        """Seleciona outro perfil já registrado."""

        with self._lock:
            profile = self._profiles.get(name)

            if profile is None:
                raise ProfileManagerError(
                    f"Perfil não encontrado: {name}"
                )

            self._active_name = name
            return profile

    def get(self, name: str) -> Profile:
        """Consulta um perfil sem alterar o perfil ativo."""

        with self._lock:
            profile = self._profiles.get(name)

            if profile is None:
                raise ProfileManagerError(
                    f"Perfil não encontrado: {name}"
                )

            return profile
