#!/usr/bin/env bash
set -e

echo "========================================================"
echo " Starting Intelligent Trading Agent - Master Coordinator"
echo "========================================================"

# Assicura unbuffered per Python e visualizzazione immediata dei log
export PYTHONUNBUFFERED=1

# 1. Avvia Web Dashboard su porta 3000 (o $PORT)
DASHBOARD_PORT="${PORT:-${DASHBOARD_PORT:-3000}}"
echo "[1/3] Avvio Web Dashboard su porta ${DASHBOARD_PORT}..."
python -u dashboard.py &
DASHBOARD_PID=$!

# 2. Cleanup all'uscita
cleanup() {
    echo "Arresto dashboard in background..."
    kill $DASHBOARD_PID 2>/dev/null || true
    exit 0
}
trap cleanup SIGTERM SIGINT

# 3. Attesa avvio dashboard
sleep 2

# 4. Loop periodico del Coordinator con gestione errori
INTERVAL="${COORDINATOR_INTERVAL_SECONDS:-900}"
echo "[2/3] Avvio ciclo dell'Orchestratore (intervallo: ${INTERVAL}s)..."

while true; do
    echo ""
    echo "⏰ [$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Avvio ciclo Coordinator..."
    python -u coordinator.py --once || echo "⚠️ Warning: ciclo coordinator terminato con errore, riprovo al prossimo intervallo."
    echo "💤 In attesa per ${INTERVAL} secondi prima del prossimo ciclo..."
    sleep "${INTERVAL}" &
    wait $!
done
