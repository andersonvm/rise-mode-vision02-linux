#!/usr/bin/env bash
# Abre OpenBoard sem usar shell dinâmico ou modificações de sistema.
set -euo pipefail
if command -v OpenBoard >/dev/null 2>&1; then exec OpenBoard; fi
if command -v openboard >/dev/null 2>&1; then exec openboard; fi
if command -v flatpak >/dev/null 2>&1 && flatpak info ch.openboard.OpenBoard >/dev/null 2>&1; then
    exec flatpak run ch.openboard.OpenBoard
fi
if command -v notify-send >/dev/null 2>&1; then
    notify-send 'Vision 02 — OpenBoard' 'OpenBoard não encontrado. Instale o aplicativo para usar esta tecla.' || true
fi
printf '%s\n' 'OpenBoard não encontrado.' >&2
exit 127
