#!/bin/bash
set -u

echo "========================================================"
echo "Starting Master Coordinator on Docker"
echo "========================================================"

INTERVAL="${COORDINATOR_INTERVAL_SECONDS:-900}"

echo "[1/2] Starting Web Dashboard..."
python -u dashboard.py &

echo "[2/2] Starting coordinator loop (interval: ${INTERVAL}s)..."
if [ "${PAPER_TRADING:-false}" = "true" ]; then
    echo "📝 PAPER attivo: portafoglio virtuale."
elif [ "${DRY_RUN:-true}" = "true" ]; then
    echo "🧪 DRY-RUN attivo: nessuna transazione verra' firmata."
fi
echo ""

while true; do
    echo "⏰ [$(date -u +%Y-%m-%dT%H:%M:%SZ)] Running coordinator cycle..."
    python -u main.py || echo "⚠️ Warning: ciclo coordinator terminato con errore, riprovo tra ${INTERVAL}s"
    echo "💤 Sleeping for ${INTERVAL} seconds until next cycle..."
    sleep "${INTERVAL}"
done
