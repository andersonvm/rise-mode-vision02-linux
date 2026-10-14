#!/usr/bin/env bash
set -euo pipefail
if ! command -v notify-send >/dev/null 2>&1; then
    echo 'notify-send não está instalado' >&2
    exit 1
fi
notify-send 'Rise Mode Vision 02' "${1:-Ação executada}"
