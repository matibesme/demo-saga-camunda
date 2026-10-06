#!/usr/bin/env bash
# Modo respaldo: levanta los 4 workers en esta máquina (cada uno es un proceso separado).
# Ctrl+C los detiene a todos. Para simular "se cae un worker": kill del PID que se imprime.
cd "$(dirname "$0")/.."
PY=".venv/bin/python"; [ -x "$PY" ] || PY=python3
trap 'kill $(jobs -p) 2>/dev/null' EXIT INT TERM
for s in ordenes inventario pagos envios; do
  WORKER_NAME="${WORKER_NAME:-local}" "$PY" "workers/$s/main.py" &
  echo "worker $s -> PID $!"
done
wait
