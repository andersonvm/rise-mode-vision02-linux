"""Backend do editor GTK da Vision 02. Executado pelo Python da .venv.

Nunca acessa USB, HID nem o socket IPC. Não executa ações configuradas.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from datetime import datetime, timezone

import yaml
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision02.profiles import Action, KeyConfig, load_profile
from vision02.profiles.loader import parse_appearance
from vision02.icon_library import list_icons, import_icon
from vision02.user_profiles import default_profile_paths
from vision02.rendering import render_profile, render_key
from vision02.studio_preview_layers_v7 import render_preview_views, render_rgba_components
from vision02.protocol import physical_key_to_display_id

DEFAULT_PROFILES = (
    "examples/profiles/desenvolvimento-switch.yaml",
    "examples/profiles/observabilidade.yaml",
)


def allowed_profiles(project: Path, paths=None) -> dict[str, Path]:
    if paths is None:
        paths = default_profile_paths(project)
    profiles = {}
    for rel in paths:
        raw_path = project / rel
        if raw_path.is_symlink():
            raise ValueError(f"Perfil não pode ser link simbólico: {raw_path}")
        path = raw_path.resolve()
        # O carregador atual valida também a existência de scripts e imagens.
        profile = load_profile(path)
        if profile.name in profiles:
            raise ValueError(f"Nome de perfil duplicado: {profile.name}")
        profiles[profile.name] = path
    return profiles


def _resolve_profile(project: Path, name: str, paths=None) -> Path:
    profiles = allowed_profiles(project, paths)
    if name not in profiles:
        raise ValueError(f"Perfil não permitido: {name!r}")
    return profiles[name]


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _action_dict(action) -> dict:
    result = {"type": action.type}
    if action.type == "command":
        result["argv"] = list(action.argv)
    elif action.type == "url":
        result["url"] = action.url
    elif action.type == "script":
        result.update(path=str(action.script_path), interpreter=action.interpreter, args=list(action.argv))
    elif action.type == "hotkey":
        result["keys"] = list(action.keys)
    elif action.type == "profile":
        result["target"] = action.target
    elif action.type == "obs":
        result["operation"] = action.obs_operation
        if action.obs_slot is not None:
            result["slot"] = action.obs_slot
        if action.obs_source is not None:
            result["input"] = action.obs_source
        if action.obs_scene is not None:
            result["scene"] = action.obs_scene
    return result


def inspect_profile(project: Path, name: str, paths=None) -> dict:
    path = _resolve_profile(project, name, paths)
    profile = load_profile(path)
    raw = path.read_bytes()
    keys = {}
    for key_id in range(1, 16):
        cfg = profile.keys.get(key_id)
        keys[str(key_id)] = (
            {"label": cfg.label, "image": str(cfg.image) if cfg.image else "", "action": _action_dict(cfg.action), "appearance": vars(cfg.appearance) if cfg.appearance is not None else None}
            if cfg else {"label": "", "image": "", "action": {"type": "none"}, "appearance": None}
        )
    return {"name": name, "path": str(path), "sha256": _sha(raw), "keys": keys}


def _action_payload(action: dict, other_profiles: set[str]) -> dict | None:
    if not isinstance(action, dict):
        raise ValueError("Ação deve ser um objeto")
    kind = action.get("type")
    if kind == "none":
        return None
    if kind == "command":
        result = {"type": kind, "argv": action.get("argv")}
    elif kind == "url":
        result = {"type": kind, "url": action.get("url")}
    elif kind == "script":
        result = {"type": kind, "path": action.get("path"),
                  "interpreter": action.get("interpreter"), "args": action.get("args", [])}
    elif kind == "hotkey":
        result = {"type": kind, "keys": action.get("keys")}
    elif kind == "obs":
        result = {"type": kind, "operation": action.get("operation")}
        if action.get("slot") is not None:
            result["slot"] = action["slot"]
        if action.get("input"):
            result["input"] = action["input"]
        if action.get("scene"):
            result["scene"] = action["scene"]
    elif kind == "profile":
        target = action.get("target")
        if target not in other_profiles:
            raise ValueError(f"Perfil de destino não está disponível: {target!r}")
        result = {"type": kind, "target": target}
    else:
        raise ValueError(f"Tipo de ação desconhecido: {kind!r}")
    return result


def _new_yaml(original: bytes, key_id: int, edited: dict, profile_names: set[str]) -> bytes:
    # load_profile() já valida rejeição de chaves duplicadas e campos desconhecidos.
    data = yaml.safe_load(original)
    if not isinstance(data, dict) or not isinstance(data.get("keys"), dict):
        raise ValueError("Estrutura YAML inválida")
    if type(key_id) is not int or not 1 <= key_id <= 15:
        raise ValueError("Tecla física deve estar entre 1 e 15")
    action = _action_payload(edited.get("action", {}), profile_names)
    if action is None:
        data["keys"].pop(key_id, None)
    else:
        label = edited.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("Rótulo obrigatório para uma tecla configurada")
        image = edited.get("image", "")
        if not isinstance(image, str):
            raise ValueError("Caminho da imagem deve ser texto")
        cfg = {"label": label.strip(), "action": action}
        if image.strip():
            cfg["image"] = image.strip()
        if "appearance" in edited:
            appearance = parse_appearance(edited["appearance"])
            if appearance is not None:
                cfg["appearance"] = vars(appearance)
        elif "appearance" in data["keys"].get(key_id, {}):
            cfg["appearance"] = data["keys"][key_id]["appearance"]
        data["keys"][key_id] = cfg
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=90).encode("utf-8")


def _candidate(project: Path, name: str, key_id: int, edited: dict,
               expected: str, paths=None) -> tuple[Path, bytes, bytes]:
    path = _resolve_profile(project, name, paths)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Arquivo do perfil não pode ser link simbólico")
    current = path.read_bytes()
    if expected != _sha(current):
        raise RuntimeError("O perfil mudou no disco. Recarregue o editor antes de salvar.")
    payload = _new_yaml(current, key_id, edited, set(allowed_profiles(project, paths)))
    return path, current, payload


def _validate_at_same_location(path: Path, payload: bytes):
    # Um arquivo temporário no mesmo diretório preserva caminhos relativos de imagens/scripts.
    fd, temp_name = tempfile.mkstemp(prefix=".vision02-editor-", suffix=".yaml", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        profile = load_profile(temp)
        for cfg in profile.keys.values():
            if cfg.image is not None:
                with Image.open(cfg.image) as picture:
                    picture.verify()
        return temp, profile
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def _preview_root() -> Path:
    home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    path = home / "vision02" / "editor"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def preview_key(project: Path, name: str, key_id: int, edited: dict,
                expected: str, paths=None) -> dict:
    path, _, payload = _candidate(project, name, key_id, edited, expected, paths)
    temp, profile = _validate_at_same_location(path, payload)
    try:
        digest = _sha(payload)[:20]
        folder = _preview_root() / digest
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        previews = {}
        for physical, image in render_profile(profile).items():
            target = folder / f"tecla-{physical:02d}.png"
            if isinstance(image, Path):
                with Image.open(image) as picture:
                    final = picture.convert("RGB").resize((100, 100))
            else:
                final = image.convert("RGB")
                if final.size != (100, 100):
                    final = final.resize((100, 100))
            final.save(target, format="PNG")
            previews[str(physical)] = {
                "image": str(target),
                "display_id": physical_key_to_display_id(physical),
            }
        # Variantes locais SOMENTE da tecla em edição e SOMENTE da aparência
        # personalizada. Os 15 PNGs tradicionais permanecem intactos.
        layers = {}
        selected = profile.keys.get(key_id)
        if selected is not None and selected.appearance is not None:
            for mode, picture in render_preview_views(
                selected.label, selected.image, selected.appearance
            ).items():
                target = folder / f"tecla-{key_id:02d}-v7-{mode}.png"
                picture.save(target, format="PNG")
                layers[mode] = str(target)
        components = {}
        if selected is not None and selected.appearance is not None:
            for name, picture in render_rgba_components(
                selected.label, selected.image, selected.appearance
            ).items():
                target = folder / f"tecla-{key_id:02d}-v7-rgba-{name}.png"
                picture.save(target, format="PNG")
                components[name] = str(target)
        return {"ok": True, "previews": previews, "layers": layers,
                "components": components}
    finally:
        temp.unlink(missing_ok=True)


def save_key(project: Path, name: str, key_id: int, edited: dict,
             expected: str, paths=None,
             backup_dir: Path | None = None) -> dict:
    path, original, payload = _candidate(project, name, key_id, edited, expected, paths)
    temp, _ = _validate_at_same_location(path, payload)
    try:
        # Verificação final de concorrência antes de substituir o arquivo.
        if path.read_bytes() != original:
            raise RuntimeError("O perfil mudou durante a gravação. Nenhum dado foi substituído.")
        storage = backup_dir or (Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
                                 / "vision02" / "editor-backups")
        storage.mkdir(parents=True, exist_ok=True, mode=0o700)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = storage / f"{path.stem}-{stamp}-{_sha(original)[:12]}.yaml"
        with backup.open("xb") as dest:
            dest.write(original)
        os.chmod(temp, path.stat().st_mode & 0o777)
        os.replace(temp, path)
        temp = None
        return {"ok": True, "path": str(path), "backup": str(backup), "sha256": _sha(payload)}
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)




def preview_appearance(project: Path, name: str, edited: dict, paths=None) -> dict:
    """Prévia de aparência independente de ações/YAML, sem acesso a HID."""
    path = _resolve_profile(project, name, paths)
    label = edited.get("label", "")
    if not isinstance(label, str):
        raise ValueError("Rótulo deve ser texto")
    image = edited.get("image", "")
    if not isinstance(image, str):
        raise ValueError("Imagem deve ser texto")
    source = None
    if image.strip():
        source = Path(image.strip()).expanduser()
        if not source.is_absolute():
            source = path.parent / source
        source = source.resolve()
        if not source.is_file():
            raise ValueError(f"Imagem não encontrada: {source}")
    style = parse_appearance(edited.get("appearance"))
    if not label.strip() and style is None:
        from vision02.rendering import render_empty
        result = render_empty()
    else:
        config = KeyConfig(key_id=1, label=label or " ", action=Action(type="command", argv=("true",)),
                           image=source, appearance=style)
        rendered = render_key(config)
        if isinstance(rendered, Path):
            with Image.open(rendered) as picture:
                result = ImageOps.fit(ImageOps.exif_transpose(picture).convert("RGB"), (100, 100),
                                      method=Image.Resampling.LANCZOS)
        else:
            result = rendered
    digest = _sha(json.dumps(edited, ensure_ascii=False, sort_keys=True).encode())[:20]
    if source is not None:
        digest += f"-{source.stat().st_mtime_ns:x}"
    target = _preview_root() / f"appearance-{digest}.png"
    result.convert("RGB").save(target, format="PNG")
    return {"ok": True, "image": str(target)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Backend YAML da GUI Vision 02; não acessa HID")
    parser.add_argument("--project", type=Path, default=ROOT)
    parser.add_argument("--command", required=True, choices=("list", "inspect", "preview", "save", "style-preview", "icons-list", "icons-import"))
    parser.add_argument("--profile")
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            result = {"ok": True, "profiles": list(allowed_profiles(args.project))}
        elif args.command == "icons-list":
            result = {"ok": True, "icons": list_icons()}
        elif args.command == "icons-import":
            request = json.load(sys.stdin)
            source = request.get("source")
            if not isinstance(source, str) or not source.strip():
                raise ValueError("Informe o arquivo de imagem")
            result = {"ok": True, "icon": import_icon(Path(source))}
        else:
            if not args.profile:
                raise ValueError("Informe --profile")
            if args.command == "inspect":
                result = {"ok": True, "profile": inspect_profile(args.project, args.profile)}
            elif args.command == "style-preview":
                result = preview_appearance(args.project, args.profile, json.load(sys.stdin))
            else:
                request = json.load(sys.stdin)
                key_id = request["key_id"]
                edited = request["edited"]
                expected = request["sha256"]
                if args.command == "preview":
                    result = preview_key(args.project, args.profile, key_id, edited, expected)
                else:
                    result = save_key(args.project, args.profile, key_id, edited, expected)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, yaml.YAMLError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
