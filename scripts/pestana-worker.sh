#!/usr/bin/env bash
# Corre un worker en una pestaña. Si se detiene (Ctrl+C), con Enter se vuelve a prender.
# Uso: pestana-worker.sh <servicio>
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
PY="$RAIZ/.venv/bin/python"; [ -x "$PY" ] || PY=python3
cd "$RAIZ"
while true; do
  "$PY" "workers/$1/main.py"
  echo; echo ">>> worker $1 APAGADO. Enter = volver a prenderlo"
  read -r
done
