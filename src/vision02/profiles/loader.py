"""Carregamento e validação de perfis YAML."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .models import Action, KeyAppearance, KeyConfig, Profile


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

    if action_type == "obs":
        from vision02.obs_control import OBS_OPERATIONS
        _fields(data, {"type", "operation", "slot", "input"}, context)
        operation = data.get("operation")
        if not isinstance(operation, str) or operation not in OBS_OPERATIONS:
            raise ProfileValidationError(f"{context}.operation: comando OBS inválido")
        slot = data.get("slot")
        if operation == "scene_slot":
            if type(slot) is not int or not 1 <= slot <= 3:
                raise ProfileValidationError(f"{context}.slot deve ser 1, 2 ou 3")
        elif slot is not None:
            raise ProfileValidationError(f"{context}.slot só é permitido em scene_slot")
        source = data.get("input")
        if source is not None:
            if operation not in ("toggle_mic", "toggle_desktop"):
                raise ProfileValidationError(f"{context}.input só é permitido para áudio")
            source = _text(source, f"{context}.input")
            if len(source) > 128:
                raise ProfileValidationError(f"{context}.input muito longo")
        return Action(type="obs", obs_operation=operation, obs_slot=slot, obs_source=source)

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




_APPEARANCE_DEFAULTS = {
    "background": "#080C16", "text": None, "font_family": "sans",
    "font_size": 18, "font_weight": "bold", "text_color": "#F5F7FA",
    "horizontal": "center", "vertical": "center", "offset_x": 0, "offset_y": 0,
    "image_fit": "cover", "show_text": True,
}
_APPEARANCE_ENUMS = {
    "font_family": {"sans", "serif", "mono"},
    "font_weight": {"regular", "bold"},
    "horizontal": {"left", "center", "right"},
    "vertical": {"top", "center", "bottom"},
    "image_fit": {"cover", "contain", "stretch"},
}


def parse_appearance(value: dict | None) -> KeyAppearance | None:
    """Valida os campos opcionais sem converter números/booleans implicitamente."""
    if value is None:
        return None
    data = _mapping(value, "appearance")
    _fields(data, set(_APPEARANCE_DEFAULTS), "appearance")
    result = dict(_APPEARANCE_DEFAULTS)
    result.update(data)
    for color in ("background", "text_color"):
        if not isinstance(result[color], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", result[color]):
            raise ProfileValidationError(f"appearance.{color} deve ser #RRGGBB")
    if result["text"] is not None and (not isinstance(result["text"], str) or len(result["text"]) > 120):
        raise ProfileValidationError("appearance.text deve ter até 120 caracteres")
    for field, allowed in _APPEARANCE_ENUMS.items():
        if not isinstance(result[field], str) or result[field] not in allowed:
            raise ProfileValidationError(f"appearance.{field}: escolha entre {', '.join(sorted(allowed))}")
    if type(result["font_size"]) is not int or not 8 <= result["font_size"] <= 36:
        raise ProfileValidationError("appearance.font_size deve estar entre 8 e 36")
    for field in ("offset_x", "offset_y"):
        if type(result[field]) is not int or not -40 <= result[field] <= 40:
            raise ProfileValidationError(f"appearance.{field} deve estar entre -40 e 40")
    if type(result["show_text"]) is not bool:
        raise ProfileValidationError("appearance.show_text deve ser booleano")
    return KeyAppearance(**result)


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
            {"label", "image", "action", "appearance"},
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
            appearance=parse_appearance(config.get("appearance")),
        )

    return Profile(
        name=name,
        version=version,
        keys=keys,
        source=path,
    )
