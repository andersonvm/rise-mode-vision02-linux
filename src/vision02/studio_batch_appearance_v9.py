"""Cópia de aparência entre teclas existentes, sem copiar ações ou rótulos.

Operação pura: recebe YAML validado pelo backend, devolve novos bytes YAML.
Não executa ações, não chama IPC e não acessa dispositivos.
"""
from __future__ import annotations

from copy import deepcopy

import yaml


def batch_targets(source_key: int, targets: list[int]) -> tuple[int, ...]:
    """Valida seleção explícita de destinos (1..15, sem duplicação/origem)."""
    if type(source_key) is not int or not 1 <= source_key <= 15:
        raise ValueError('Tecla de origem inválida')
    if not isinstance(targets, list) or not 1 <= len(targets) <= 14:
        raise ValueError('Selecione de uma a 14 teclas de destino')
    if any(type(key) is not int or not 1 <= key <= 15 for key in targets):
        raise ValueError('Número de tecla de destino inválido')
    if len(targets) != len(set(targets)) or source_key in targets:
        raise ValueError('A origem não pode ser destino e os destinos não podem repetir')
    return tuple(sorted(targets))


def copy_saved_appearance(original: bytes, source_key: int, targets: list[int]) -> bytes:
    """Transfere apenas image/appearance. Preserva action, label e demais campos.

    Apenas teclas existentes e configuradas são elegíveis. Isto impede
    inventar ações ou sobrescrever teclas não configuradas acidentalmente.
    """
    keys_to_change = batch_targets(source_key, targets)
    try:
        data = yaml.safe_load(original)
    except yaml.YAMLError as exc:
        raise ValueError('YAML inválido') from exc
    if not isinstance(data, dict) or not isinstance(data.get('keys'), dict):
        raise ValueError('Estrutura YAML inválida')
    keys = data['keys']
    source = keys.get(source_key)
    if not isinstance(source, dict) or not isinstance(source.get('action'), dict):
        raise ValueError('A tecla de origem precisa estar configurada no YAML')
    for dest in keys_to_change:
        target = keys.get(dest)
        if not isinstance(target, dict) or not isinstance(target.get('action'), dict):
            raise ValueError(f'Tecla {dest:02d} não está configurada no YAML')
    for dest in keys_to_change:
        target = keys[dest]
        for field in ('image', 'appearance'):
            if field in source:
                target[field] = deepcopy(source[field])
            else:
                target.pop(field, None)
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=90).encode('utf-8')
