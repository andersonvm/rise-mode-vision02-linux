"""Reload de perfis com validação prévia e proprietário HID único.

Chamado somente pela thread responsável pelo controlador USB/HID.
"""
from __future__ import annotations

from pathlib import Path
from collections.abc import Callable, Iterable

from .controller import Vision02Controller
from .device import Vision02
from .profiles import ProfileManager, validate_profile_targets
from .protocol import physical_key_to_display_id
from .rendering import render_profile


class FatalReloadError(RuntimeError):
    """Estado visual pode estar parcial; a CLI deve encerrar para hotplug recuperar."""


def reload_profiles(
    current: ProfileManager,
    paths: Iterable[str | Path],
    controller: Vision02Controller,
    device: Vision02,
    drain_events: Callable[[], None],
    *,
    idle_timeout: float = 5.0,
) -> ProfileManager:
    """Revalida todos os YAML, preserva perfil ativo e sincroniza os LCDs.

    Erros de validação/renderização não modificam a sessão. Se a atualização
    dos LCDs falhar após a suspensão, o controlador não é reativado; a CLI
    deve encerrar o processo e deixar o supervisor criar uma nova sessão.
    """
    candidates = ProfileManager()
    candidates.load_many(tuple(paths))
    validate_profile_targets(candidates)

    active = current.active_name
    if active is None or active not in candidates.list_profiles():
        raise ValueError(
            f"Reload recusado: perfil ativo {active!r} ausente nos YAML. "
            "Selecione outro perfil antes de recarregar."
        )
    candidates.switch(active)
    images = render_profile(candidates.active)

    controller.suspend()
    try:
        idle = controller.wait_idle(timeout=idle_timeout)
    except Exception:
        controller.resume()
        raise
    if not idle:
        controller.resume()
        raise TimeoutError("Ações pendentes impediram o recarregamento")

    # Qualquer falha a partir daqui pode deixar os LCDs inconsistentes.
    # Não reativar ações; o supervisor reiniciará a sessão HID.
    try:
        for key_id, image in images.items():
            device.set_image(
                physical_key_to_display_id(key_id),
                image,
                skip_unchanged=True,
            )
        drain_events()
        controller.activate(candidates.active)
    except Exception as exc:
        raise FatalReloadError(
            "Falha durante reload HID; encerrando controlador para recuperação USB"
        ) from exc

    return candidates
