#!/usr/bin/env bash
# Shell de la pestaña "comandos" (con `iniciar` en el PATH).
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$RAIZ/scripts:$PATH"
cd "$RAIZ"
exec bash --rcfile "$RAIZ/scripts/comandos.rc"
