"""Argumentos seguros para abrir um perfil e tecla no editor existente."""
from __future__ import annotations

import argparse


def editor_args(profile: str, key_id: int) -> list[str]:
    if not isinstance(profile, str) or not 1 <= len(profile) <= 128 or profile.strip() != profile:
        raise ValueError("Nome de perfil inválido")
    if type(key_id) is not int or not 1 <= key_id <= 15:
        raise ValueError("Tecla física deve estar entre 1 e 15")
    return ['--profile', profile, '--key', str(key_id)]


def parse_editor_target(argv: list[str]) -> tuple[str | None, int]:
    parser = argparse.ArgumentParser(prog='vision02-editor', exit_on_error=False)
    parser.add_argument('--profile')
    parser.add_argument('--key', type=int, default=1)
    try:
        args = parser.parse_args(argv)
    except (argparse.ArgumentError, SystemExit) as exc:
        raise ValueError('Argumentos inválidos para o editor') from exc
    if args.profile is not None:
        editor_args(args.profile, args.key)
    elif type(args.key) is not int or not 1 <= args.key <= 15:
        raise ValueError('Tecla física deve estar entre 1 e 15')
    return args.profile, args.key
