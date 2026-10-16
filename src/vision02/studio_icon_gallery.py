"""Pesquisa e seleção de ícones para a galeria de propriedades do Studio.

Nenhuma escrita, conexão HID ou execução de ação: a lista é fornecida pela
biblioteca já existente e as decisões de salvamento ficam com o editor.
"""
from __future__ import annotations

import unicodedata

MAX_GALLERY_ICONS = 90


def normalized(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError('Texto de pesquisa inválido')
    decomposed = unicodedata.normalize('NFKD', text)
    return ''.join(char for char in decomposed if not unicodedata.combining(char)).casefold().strip()


def filtered_icons(icons: list[dict], search: str = '', *, limit: int = MAX_GALLERY_ICONS) -> list[dict]:
    """Pesquisa estável, sem alterar a biblioteca nem retornar itens inválidos."""
    if not isinstance(icons, list) or not 1 <= limit <= 500:
        raise ValueError('Catálogo ou limite inválido')
    needle = normalized(search)
    found = []
    visited = set()
    for icon in icons:
        if not isinstance(icon, dict):
            continue
        name, path = icon.get('name'), icon.get('path')
        if not isinstance(name, str) or not isinstance(path, str) or not path:
            continue
        if not path.startswith('/') or path in visited:
            continue
        if needle not in normalized(name):
            continue
        visited.add(path)
        found.append(icon)
        if len(found) >= limit:
            break
    return found


def icon_by_path(icons: list[dict], path: str) -> dict | None:
    """Seleciona somente um ícone que conste na resposta da biblioteca."""
    if not isinstance(path, str):
        return None
    for icon in icons:
        if isinstance(icon, dict) and icon.get('path') == path and path.startswith('/'):
            return icon
    return None
