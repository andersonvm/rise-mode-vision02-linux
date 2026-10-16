"""Formulário de edição rápida: conversão pura, sem escrita ou execução de ações.

O armazenamento é delegado ao backend consolidado do editor de teclas.
"""
from __future__ import annotations

import shlex

KINDS = ('none', 'command', 'url', 'script', 'hotkey', 'profile', 'obs')
HINTS = {
    'none': 'Sem ação: salvar remove a configuração desta tecla.',
    'command': 'Campo 1: programa e argumentos (ex.: gnome-terminal --wait).',
    'url': 'Campo 1: endereço https://…',
    'script': 'Campo 1: caminho do script | 2: bash/python | 3: argumentos.',
    'hotkey': 'Campo 1: teclas separadas por vírgula (ex.: Ctrl, Shift, T).',
    'profile': 'Campo 1: nome exato do perfil de destino.',
    'obs': 'Campo 1: operação | 2: cena | 3: entrada de áudio | 4: slot (1–3).',
}


def key_to_form(edited: dict) -> dict:
    if not isinstance(edited, dict):
        raise ValueError('Configuração de tecla inválida')
    action = edited.get('action') or {'type': 'none'}
    if not isinstance(action, dict):
        raise ValueError('Ação inválida')
    kind = action.get('type', 'none')
    if kind not in KINDS:
        raise ValueError('Tipo de ação não suportado pelo painel rápido')
    fields = ['', '', '', '']
    if kind == 'command':
        fields[0] = shlex.join(action.get('argv') or [])
    elif kind == 'url':
        fields[0] = action.get('url') or ''
    elif kind == 'hotkey':
        fields[0] = ', '.join(action.get('keys') or [])
    elif kind == 'profile':
        fields[0] = action.get('target') or ''
    elif kind == 'script':
        fields[0] = action.get('path') or ''
        fields[1] = action.get('interpreter') or ''
        fields[2] = shlex.join(action.get('args') or [])
    elif kind == 'obs':
        fields[0] = action.get('operation') or ''
        fields[1] = action.get('scene') or ''
        fields[2] = action.get('input') or ''
        fields[3] = str(action['slot']) if action.get('slot') is not None else ''
    return {
        'label': edited.get('label') or '',
        'image': edited.get('image') or '',
        'kind': kind, 'fields': fields,
        'appearance': edited.get('appearance'),
        'visual_text': (edited.get('appearance') or {}).get('text') or '',
    }


def form_to_key(form: dict) -> dict:
    if not isinstance(form, dict):
        raise ValueError('Formulário inválido')
    label, image, kind = form.get('label'), form.get('image'), form.get('kind')
    if not isinstance(label, str) or not isinstance(image, str) or kind not in KINDS:
        raise ValueError('Campos do formulário inválidos')
    fields = form.get('fields')
    if not isinstance(fields, list) or len(fields) != 4 or not all(isinstance(v, str) for v in fields):
        raise ValueError('Campos da ação inválidos')
    a, b, c, d = (v.strip() for v in fields)
    if kind == 'none':
        action = {'type': 'none'}
    elif kind == 'command':
        action = {'type': kind, 'argv': shlex.split(a)}
    elif kind == 'url':
        action = {'type': kind, 'url': a}
    elif kind == 'hotkey':
        action = {'type': kind, 'keys': [s.strip() for s in a.split(',') if s.strip()]}
    elif kind == 'profile':
        action = {'type': kind, 'target': a}
    elif kind == 'script':
        action = {'type': kind, 'path': a, 'interpreter': b, 'args': shlex.split(c)}
    else:
        action = {'type': 'obs', 'operation': a}
        if b:
            action['scene'] = b
        if c:
            action['input'] = c
        if d:
            if not d.isdecimal():
                raise ValueError('Slot OBS deve ser um número inteiro')
            action['slot'] = int(d)
    # Atualiza apenas o texto sobreposto; preserva cores, fontes e deslocamentos.
    appearance = form.get('appearance')
    visual_text = form.get('visual_text', '')
    if not isinstance(visual_text, str):
        raise ValueError('Texto visual deve ser uma string')
    if len(visual_text) > 120:
        raise ValueError('Texto visual deve ter até 120 caracteres')
    if appearance is not None and not isinstance(appearance, dict):
        raise ValueError('Aparência inválida')
    if visual_text:
        appearance = dict(appearance or {})
        appearance['text'] = visual_text
        appearance['show_text'] = True
    elif appearance is not None and appearance.get('text') is not None:
        appearance = dict(appearance)
        appearance['text'] = None  # sem texto personalizado: usa o rótulo
    return {'label': label, 'image': image, 'action': action, 'appearance': appearance}
