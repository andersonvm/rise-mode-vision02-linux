"""Testes da interface CLI do controle local, sem USB."""
import json
from unittest.mock import patch

import pytest

from vision02.cli import main, build_parser


def test_control_cli_status_prints_json(capsys):
    with patch("vision02.cli.ipc_request", return_value={"ok": True, "active": "Desenvolvimento"}) as req:
        main(["control", "status"])
    req.assert_called_once_with("status", None)
    assert json.loads(capsys.readouterr().out)["active"] == "Desenvolvimento"


def test_control_cli_switch_only_passes_target(capsys):
    with patch("vision02.cli.ipc_request", return_value={"ok": True, "active": "Observabilidade"}) as req:
        main(["control", "switch", "Observabilidade"])
    req.assert_called_once_with("switch", "Observabilidade")
    assert json.loads(capsys.readouterr().out)["ok"]


def test_control_cli_errors_exit_nonzero():
    with patch("vision02.cli.ipc_request", return_value={"ok": False, "error": "perfil ausente"}):
        with pytest.raises(SystemExit) as exc:
            main(["control", "switch", "Inexistente"])
    assert exc.value.code == 1


def test_control_cli_disconnected_exit_nonzero():
    with patch("vision02.cli.ipc_request", side_effect=ConnectionError("ausente")):
        with pytest.raises(SystemExit) as exc:
            main(["control", "status"])
    assert exc.value.code == 2


def test_profile_run_accepts_ipc_flag():
    args = build_parser().parse_args(["profile", "run", "dev.yaml", "--with", "obs.yaml", "--ipc"])
    assert args.ipc
    assert args.other_paths[0].name == "obs.yaml"
