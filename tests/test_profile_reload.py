"""Reload transacional sem acessar dispositivo USB/HID."""
from pathlib import Path
from unittest.mock import Mock

import pytest

from vision02.profiles import ProfileManager, ProfileValidationError
from vision02.profile_reload import FatalReloadError, reload_profiles


def create_files(tmp_path: Path, *, label: str = "Terminal") -> tuple[Path, Path]:
    one = tmp_path / "dev.yaml"
    two = tmp_path / "obs.yaml"
    one.write_text(
        "version: 1\nname: Desenvolvimento\nkeys:\n"
        f"  1:\n    label: {label}\n    action:\n"
        "      type: command\n      argv: ['true']\n"
        "  15:\n    label: Observar\n    action:\n"
        "      type: profile\n      target: Observabilidade\n",
        encoding="utf-8",
    )
    two.write_text(
        "version: 1\nname: Observabilidade\nkeys:\n"
        "  15:\n    label: Desenvolv.\n    action:\n"
        "      type: profile\n      target: Desenvolvimento\n",
        encoding="utf-8",
    )
    return one, two


def setup(tmp_path):
    paths = create_files(tmp_path)
    current = ProfileManager()
    current.load_many(paths)
    controller = Mock()
    controller.wait_idle.return_value = True
    device = Mock()
    drain = Mock()
    return paths, current, controller, device, drain


def test_valid_reload_preserves_active_and_updates_mapping(tmp_path):
    paths, current, controller, device, drain = setup(tmp_path)
    current.switch("Observabilidade")
    fresh = reload_profiles(current, paths, controller, device, drain)
    assert fresh is not current
    assert fresh.active_name == "Observabilidade"
    assert current.active_name == "Observabilidade"
    assert device.set_image.call_count == 15
    assert device.set_image.call_args_list[-1].args[0] == 5
    controller.suspend.assert_called_once()
    controller.wait_idle.assert_called_once()
    drain.assert_called_once()
    controller.activate.assert_called_once_with(fresh.active)


def test_reload_reads_updated_label_without_mutating_old_manager(tmp_path):
    paths, old, controller, device, drain = setup(tmp_path)
    create_files(tmp_path, label="Grafana")
    fresh = reload_profiles(old, paths, controller, device, drain)
    assert old.active.keys[1].label == "Terminal"
    assert fresh.active.keys[1].label == "Grafana"


def test_invalid_yaml_does_not_touch_hid_or_controller(tmp_path):
    paths, old, controller, device, drain = setup(tmp_path)
    paths[0].write_text("version: 1\nname: Desenvolvimento\nkeys: [invalid]\n")
    with pytest.raises(ProfileValidationError):
        reload_profiles(old, paths, controller, device, drain)
    controller.suspend.assert_not_called()
    device.set_image.assert_not_called()
    assert old.active_name == "Desenvolvimento"


def test_missing_active_profile_rejected_before_transmission(tmp_path):
    paths, old, controller, device, drain = setup(tmp_path)
    old.switch("Observabilidade")
    paths[0].write_text("version: 1\nname: Desenvolvimento\nkeys: {}\n")
    paths[1].write_text("version: 1\nname: Outro\nkeys: {}\n")
    with pytest.raises(ValueError, match="ausente"):
        reload_profiles(old, paths, controller, device, drain)
    controller.suspend.assert_not_called()
    device.set_image.assert_not_called()


def test_busy_queue_resumes_without_any_hid_write(tmp_path):
    paths, old, controller, device, drain = setup(tmp_path)
    controller.wait_idle.return_value = False
    with pytest.raises(TimeoutError, match="Ações pendentes"):
        reload_profiles(old, paths, controller, device, drain)
    controller.resume.assert_called_once()
    controller.activate.assert_not_called()
    device.set_image.assert_not_called()


def test_wait_idle_exception_resumes_controller(tmp_path):
    paths, old, controller, device, drain = setup(tmp_path)
    controller.wait_idle.side_effect = RuntimeError("fila indisponível")
    with pytest.raises(RuntimeError, match="fila indisponível"):
        reload_profiles(old, paths, controller, device, drain)
    controller.resume.assert_called_once()
    device.set_image.assert_not_called()


def test_hid_error_does_not_reactivate_controller(tmp_path):
    paths, old, controller, device, drain = setup(tmp_path)
    device.set_image.side_effect = OSError("USB disconnected")
    with pytest.raises(FatalReloadError, match="recuperação USB"):
        reload_profiles(old, paths, controller, device, drain)
    controller.activate.assert_not_called()
    controller.resume.assert_not_called()
    assert old.active.keys[1].label == "Terminal"


def test_event_drain_error_is_fatal(tmp_path):
    paths, old, controller, device, drain = setup(tmp_path)
    drain.side_effect = RuntimeError("eventos antigos")
    with pytest.raises(FatalReloadError):
        reload_profiles(old, paths, controller, device, drain)
    controller.activate.assert_not_called()
    controller.resume.assert_not_called()


def test_backend_ipc_rejects_arguments_for_reload():
    from vision02.control_ipc import _validate_request
    assert _validate_request({"command": "reload"}) == ("reload", None)
    with pytest.raises(ValueError):
        _validate_request({"command": "reload", "target": "Outro"})


def test_cli_exposes_reload_command():
    from vision02.cli import build_parser
    args = build_parser().parse_args(["control", "reload"])
    assert args.control_action == "reload"
