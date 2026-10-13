"""Execução de ações configuradas nos perfis."""

from .executor import ActionExecutionError, execute_action

__all__ = ["ActionExecutionError", "execute_action"]
