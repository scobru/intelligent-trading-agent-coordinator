#!/usr/bin/env bash
set -e

echo "========================================================"
echo " Starting Intelligent Trading Agent - Master Coordinator"
echo "========================================================"

# 1. Avvia Web Dashboard su porta 3000 (o $PORT)
DASHBOARD_PORT="${PORT:-${DASHBOARD_PORT:-3000}}"
echo "[1/3] Avvio Web Dashboard su porta ${DASHBOARD_PORT}..."
python dashboard.py &
DASHBOARD_PID=$!

# 2. Cleanup all'uscita
cleanup() {
    echo "Arresto servizi in background..."
    kill $DASHBOARD_PID 2>/dev/null || true
    [ -n "$COORD_PID" ] && kill $COORD_PID 2>/dev/null || true
    exit 0
}
trap cleanup SIGTERM SIGINT

# 3. Attesa avvio dashboard
sleep 2

# 4. Avvia loop periodico del Coordinator in primo piano
echo "[2/3] Avvio ciclo continuo dell'Orchestratore..."
python coordinator.py &
COORD_PID=$!

echo "[3/3] Coordinator e Dashboard attivi con successo!"
wait $COORD_PID
