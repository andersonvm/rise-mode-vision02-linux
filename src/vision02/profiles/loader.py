"""Carregamento e validação de perfis YAML."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .models import Action, KeyConfig, Profile


class ProfileValidationError(ValueError):
    """Configuração de perfil inválida."""


class _UniqueKeysLoader(yaml.SafeLoader):
    """SafeLoader que rejeita chaves YAML duplicadas."""


def _construct_mapping(loader, node):
    result = {}

    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)

        try:
            duplicate = key in result
        except TypeError as exc:
            raise ProfileValidationError(
                "Chave YAML não pode ser uma estrutura complexa"
            ) from exc

        if duplicate:
            raise ProfileValidationError(
                f"Chave YAML duplicada: {key!r}"
            )

        result[key] = loader.construct_object(value_node, deep=True)

    return result


_UniqueKeysLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _mapping(value, context: str) -> dict:
    if not isinstance(value, dict):
        raise ProfileValidationError(
            f"{context} deve ser um objeto YAML"
        )

    return value


def _fields(data: dict, allowed: set[str], context: str) -> None:
    unknown = set(data) - allowed

    if unknown:
        raise ProfileValidationError(
            f"{context}: campos desconhecidos: "
            f"{', '.join(sorted(map(str, unknown)))}"
        )


def _text(value, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileValidationError(
            f"{context} deve ser uma string não vazia"
        )

    return value


def _action(data: dict, context: str, profile_directory: Path) -> Action:
    data = _mapping(data, context)

    action_type = data.get("type")

    if action_type == "command":
        _fields(data, {"type", "argv"}, context)

        argv = data.get("argv")

        if (
            not isinstance(argv, list)
            or not argv
            or not all(
                isinstance(item, str) and item
                for item in argv
            )
        ):
            raise ProfileValidationError(
                f"{context}.argv deve ser uma lista não vazia "
                "de argumentos string"
            )

        return Action(type="command", argv=tuple(argv))

    if action_type == "url":
        _fields(data, {"type", "url"}, context)

        url = _text(data.get("url"), f"{context}.url")
        parsed = urlsplit(url)

        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ProfileValidationError(
                f"{context}.url deve ser HTTP ou HTTPS válida"
            )

        try:
            parsed.port
        except ValueError as exc:
            raise ProfileValidationError(
                f"{context}.url contém uma porta inválida"
            ) from exc

        return Action(type="url", url=url)

    if action_type == "script":
        _fields(data, {"type", "path", "interpreter", "args"}, context)
        script_name = _text(data.get("path"), f"{context}.path")
        script = Path(script_name).expanduser()
        if not script.is_absolute():
            script = profile_directory / script
        script = script.resolve()
        if not script.is_file():
            raise ProfileValidationError(
                f"{context}.path não encontrado: {script}"
            )
        interpreter = _text(data.get("interpreter"), f"{context}.interpreter")
        if interpreter not in {"bash", "python3"}:
            raise ProfileValidationError(
                f"{context}.interpreter deve ser bash ou python3"
            )
        args = data.get("args", [])
        if not isinstance(args, list) or not all(
            isinstance(arg, str) and bool(arg) for arg in args
        ):
            raise ProfileValidationError(
                f"{context}.args deve ser uma lista de strings não vazias"
            )
        return Action(
            type="script",
            script_path=script,
            interpreter=interpreter,
            argv=tuple(args),
        )

    if action_type == "hotkey":
        _fields(data, {"type", "keys"}, context)
        keys = data.get("keys")
        if (
            not isinstance(keys, list)
            or not 1 <= len(keys) <= 5
            or not all(
                isinstance(key, str)
                and re.fullmatch(r"[A-Za-z0-9_]+", key)
                for key in keys
            )
        ):
            raise ProfileValidationError(
                f"{context}.keys deve conter de 1 a 5 nomes de teclas válidos"
            )
        return Action(type="hotkey", keys=tuple(keys))

    if action_type == "profile":
        _fields(data, {"type", "target"}, context)

        target = _text(
            data.get("target"),
            f"{context}.target",
        )

        return Action(type="profile", target=target)

    raise ProfileValidationError(
        f"{context}.type desconhecido: {action_type!r}"
    )


def load_profile(path: str | Path) -> Profile:
    """Carrega e valida um perfil sem executar ações."""

    path = Path(path).expanduser().resolve()

    try:
        content = path.read_text(encoding="utf-8")
        data = yaml.load(content, Loader=_UniqueKeysLoader)
    except yaml.YAMLError as exc:
        raise ProfileValidationError(
            f"YAML inválido: {exc}"
        ) from exc

    data = _mapping(data, "Perfil")
    _fields(data, {"version", "name", "keys"}, "Perfil")

    version = data.get("version")

    if type(version) is not int or version != 1:
        raise ProfileValidationError(
            "version deve ser exatamente 1"
        )

    name = _text(data.get("name"), "name")

    raw_keys = _mapping(data.get("keys"), "keys")

    if len(raw_keys) > 15:
        raise ProfileValidationError(
            "Um perfil pode conter no máximo 15 teclas"
        )

    keys = {}

    for key_id, config in raw_keys.items():
        if type(key_id) is not int or not 1 <= key_id <= 15:
            raise ProfileValidationError(
                f"Identificador de tecla inválido: {key_id!r}"
            )

        context = f"keys[{key_id}]"
        config = _mapping(config, context)

        _fields(
            config,
            {"label", "image", "action"},
            context,
        )

        label = _text(
            config.get("label"),
            f"{context}.label",
        )

        action = _action(
            config.get("action"),
            f"{context}.action",
            path.parent,
        )

        image = None
        image_value = config.get("image")

        if image_value is not None:
            image_name = _text(
                image_value,
                f"{context}.image",
            )

            image = (path.parent / image_name).resolve()

            if not image.is_file():
                raise ProfileValidationError(
                    f"{context}.image não encontrado: {image}"
                )

        keys[key_id] = KeyConfig(
            key_id=key_id,
            label=label,
            action=action,
            image=image,
        )

    return Profile(
        name=name,
        version=version,
        keys=keys,
        source=path,
    )
