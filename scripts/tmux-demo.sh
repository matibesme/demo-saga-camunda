#!/usr/bin/env bash
# Demo completa en tmux, una PESTAÑA por cosa:
#   1 comandos   <- acá se escribe: iniciar feliz | falla-envio | ...
#   2 ordenes · 3 inventario · 4 pagos · 5 envios   (un worker por pestaña)
#   6 camunda    (logs del orquestador)
# Además levanta Camunda (docker compose) si no está corriendo y abre Operate en el navegador.
#
#   scripts/tmux-demo.sh          crea la sesión "saga" y se engancha
#   scripts/tmux-demo.sh stop     cierra la sesión (Camunda sigue corriendo)
#
# Pestañas: Ctrl+b 1..6 · Ctrl+b n / p (siguiente/anterior) · o clic con el mouse en la barra de abajo.
# Salir sin cerrar: Ctrl+b d. Apagar un worker: ir a su pestaña y Ctrl+C. Prenderlo: Enter.
S=saga
cd "$(dirname "$0")/.." || exit 1
RAIZ="$PWD"
[ "$1" = stop ] && { tmux kill-session -t $S 2>/dev/null && echo "sesión cerrada"; exit 0; }
if tmux has-session -t $S 2>/dev/null; then exec tmux attach -t $S; fi

PY="$RAIZ/.venv/bin/python"; [ -x "$PY" ] || PY=python3

# --- Camunda ---
if ! curl -sf http://localhost:9600/actuator/health/status >/dev/null 2>&1; then
  echo "Levantando Camunda (puede tardar ~1 min)..."
  (cd orquestador && docker compose up -d) || { echo "No pude levantar Camunda"; exit 1; }
  until curl -sf http://localhost:9600/actuator/health/status >/dev/null 2>&1; do sleep 2; done
fi
echo "Camunda OK -> Operate: http://localhost:8080/operate (demo / demo)"
(xdg-open http://localhost:8080/operate >/dev/null 2>&1 &) 2>/dev/null

# --- sesión ---
export WORKER_NAME="${WORKER_NAME:-local}"
tmux new-session -d -s $S -n comandos -c "$RAIZ" -x 200 -y 50 "$RAIZ/scripts/pestana-comandos.sh"
tmux set -t $S base-index 1 \; set -t $S mouse on \; set -t $S status-style 'bg=colour24,fg=white' \
  \; set -t $S window-status-current-style 'bg=colour208,fg=black,bold' \; set -t $S status-left-length 30 \
  \; set -t $S status-left ' SAGA  ' \; set -t $S status-right '#[bold]Ctrl+b 1-6 = pestañas '
tmux move-window -t $S:0 -t $S:1 2>/dev/null
for w in "ordenes" "inventario" "pagos" "envios"; do
  tmux new-window -t $S -n "$w" -c "$RAIZ" "$RAIZ/scripts/pestana-worker.sh $w"
done
tmux new-window -t $S -n camunda -c "$RAIZ/orquestador" "docker compose logs -f --tail 20 orchestration"

tmux select-window -t $S:1
exec tmux attach -t $S
