"""Coordenação de transições visuais entre perfis da Vision 02."""

from __future__ import annotations

from collections.abc import Callable

from .controller import Vision02Controller
from .device import Vision02
from .profiles.manager import ProfileManager
from .protocol import physical_key_to_display_id
from .rendering import render_profile


class ProfileSwitcher:
    """Troca perfis sem reabrir a sessão HID.

    O método switch() deve ser chamado pela thread que coordena
    a leitura HID. Não deve ser chamado pela thread de ações.

    Após uma falha de transmissão ou descarte de eventos,
    o controlador permanece suspenso. A CLI deve encerrar
    a sessão, sem voltar a despachar ações.
    """

    def __init__(
        self,
        manager: ProfileManager,
        controller: Vision02Controller,
        device: Vision02,
        *,
        drain_events: Callable[[], None],
        idle_timeout: float = 5.0,
    ) -> None:
        if idle_timeout < 0:
            raise ValueError("idle_timeout não pode ser negativo")

        self.manager = manager
        self.controller = controller
        self.device = device
        self.drain_events = drain_events
        self.idle_timeout = idle_timeout

    def switch(self, target: str) -> bool:
        """Atualiza os LCDs e ativa um perfil previamente registrado.

        Retorna False quando o destino já é o perfil ativo.
        Retorna True quando a transição foi concluída.

        Falhas após o início da atualização visual deixam
        o controlador suspenso para impedir ações incorretas.
        """
        current = self.manager.active

        if target == current.name:
            return False

        # Validar e preparar antes de alterar qualquer estado.
        new_profile = self.manager.get(target)
        images = render_profile(new_profile)

        self.controller.suspend()

        # Ainda não houve alteração visual; podemos cancelar
        # a transição e retomar o perfil anterior.
        if not self.controller.wait_idle(
            timeout=self.idle_timeout
        ):
            self.controller.resume()
            raise TimeoutError(
                "Ações pendentes impediram a troca de perfil"
            )

        # A partir daqui, uma falha pode deixar os LCDs
        # parcialmente atualizados. Não retomar automaticamente.
        for key_id, image in images.items():
            self.device.set_image(
                physical_key_to_display_id(key_id),
                image,
                skip_unchanged=True,
            )

        # Deve descartar todos os eventos antigos antes de
        # habilitar as ações do novo perfil.
        self.drain_events()

        self.manager.switch(target)
        self.controller.activate(new_profile)

        return True
