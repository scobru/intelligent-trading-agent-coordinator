"""
Punto di ingresso principale per il ciclo del Master Coordinator.
Allineato alla struttura standard di tutti i bot fratelli (main.py).
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from coordinator import Coordinator

def main():
    print("==================================================================", flush=True)
    print("🚀 AVVIO CICLO COORDINATORE MASTER (Base L2)", flush=True)
    print("==================================================================", flush=True)
    coord = Coordinator()
    coord.run_cycle()
    print("✅ CICLO COORDINATORE MASTER COMPLETATO CON SUCCESSO.", flush=True)

if __name__ == "__main__":
    main()
