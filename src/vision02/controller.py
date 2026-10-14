"""Despacho assíncrono de ações associadas às teclas."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable

from vision02.actions import execute_action
from vision02.profiles.models import Action, Profile

logger = logging.getLogger(__name__)


class Vision02Controller:
    """Executa ações fora da thread responsável pela leitura HID."""

    def __init__(
        self,
        profile: Profile,
        *,
        executor: Callable[[Action], None] = execute_action,
        queue_size: int = 64,
    ) -> None:
        if queue_size < 1:
            raise ValueError("queue_size deve ser positivo")

        self.profile = profile
        self.executor = executor

        self._queue: queue.Queue[Action] = queue.Queue(
            maxsize=queue_size
        )

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._suspended = False

    def start(self) -> None:
        """Inicia a thread de execução uma única vez."""
        with self._lock:
            if self._stop_event.is_set():
                raise RuntimeError(
                    "Controlador já encerrado; crie outra instância"
                )

            if self._thread is not None:
                if self._thread.is_alive():
                    return
                raise RuntimeError(
                    "Thread de ações encerrada inesperadamente"
                )

            self._thread = threading.Thread(
                target=self._worker,
                name="vision02-actions",
                daemon=True,
            )
            self._thread.start()

    def handle_event(self, key_id: int, pressed: bool) -> bool:
        """Enfileira pressionamentos somente quando o perfil está ativo."""
        if not pressed:
            return False

        with self._lock:
            if (
                self._suspended
                or self._stop_event.is_set()
                or self._thread is None
                or not self._thread.is_alive()
            ):
                return False

            config = self.profile.keys.get(key_id)

            if config is None:
                return False

            # Trocas de perfil são coordenadas pela CLI.
            # Nunca devem chegar ao executor de comandos.
            if config.action.type == "profile":
                return False

            try:
                self._queue.put_nowait(config.action)
            except queue.Full:
                logger.warning(
                    "Fila cheia: tecla %02d descartada",
                    key_id,
                )
                return False

            return True

    def suspend(self) -> None:
        """Bloqueia novos despachos durante uma transição."""
        with self._lock:
            if (
                self._stop_event.is_set()
                or self._thread is None
                or not self._thread.is_alive()
            ):
                raise RuntimeError("Controlador não está ativo")

            self._suspended = True

    def wait_idle(self, timeout: float = 5.0) -> bool:
        """Aguarda a fila ficar vazia, incluindo ações em execução."""
        if timeout < 0:
            raise ValueError("timeout não pode ser negativo")

        with self._queue.all_tasks_done:
            return self._queue.all_tasks_done.wait_for(
                lambda: self._queue.unfinished_tasks == 0,
                timeout=timeout,
            )

    def activate(self, profile: Profile) -> None:
        """Ativa outro perfil e libera novos despachos atomicamente."""
        if not isinstance(profile, Profile):
            raise TypeError("profile deve ser uma instância de Profile")

        with self._lock:
            if self._stop_event.is_set():
                raise RuntimeError("Controlador encerrado")

            if not self._suspended:
                raise RuntimeError(
                    "É necessário suspender o controlador antes da troca"
                )

            self.profile = profile
            self._suspended = False

    def resume(self) -> None:
        """Cancela uma suspensão sem alterar o perfil ativo."""
        with self._lock:
            if self._stop_event.is_set():
                raise RuntimeError("Controlador encerrado")

            self._suspended = False

    def _worker(self) -> None:
        """Processa ações na ordem de recebimento."""
        while True:
            try:
                action = self._queue.get(timeout=0.05)
            except queue.Empty:
                if self._stop_event.is_set():
                    return
                continue

            try:
                try:
                    self.executor(action)
                except Exception:
                    logger.exception(
                        "Falha ao executar ação configurada"
                    )
            finally:
                self._queue.task_done()

    def stop(self, timeout: float = 5.0) -> None:
        """Encerra após processar as ações previamente aceitas."""
        if timeout < 0:
            raise ValueError("timeout não pode ser negativo")

        with self._lock:
            if self._thread is None:
                self._stop_event.set()
                return

            self._stop_event.set()
            thread = self._thread

        if threading.current_thread() is thread:
            raise RuntimeError(
                "stop() não pode ser chamado pela thread de ações"
            )

        thread.join(timeout=timeout)

        if thread.is_alive():
            raise TimeoutError(
                "Execução de ações não terminou no prazo"
            )
