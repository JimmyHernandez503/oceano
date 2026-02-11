#!/usr/bin/env bash
set -euo pipefail

HOST="${UVICORN_HOST:-0.0.0.0}"
PORT="${UVICORN_PORT:-7860}"
WORKERS="${UVICORN_WORKERS:-1}"

# Si hay GPU, NO uses N procesos peleando por VRAM
if command -v nvidia-smi >/dev/null 2>&1 || [[ -e /dev/nvidia0 ]]; then
  MAXGPU="${UVICORN_WORKERS_GPU_MAX:-1}"
  if [[ "$WORKERS" -gt "$MAXGPU" ]]; then
    WORKERS="$MAXGPU"
  fi
  export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
  export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
fi

# ✅ CLAVE: si te pasan un comando (ej: python3 -m app.ingest ...), ejecútalo y ya.
if [[ $# -gt 0 ]]; then
  exec "$@"
fi

LIMIT_CONC="${UVICORN_LIMIT_CONCURRENCY:-32}"
BACKLOG="${UVICORN_BACKLOG:-2048}"
KEEPALIVE="${UVICORN_TIMEOUT_KEEPALIVE:-5}"

exec python3 -m uvicorn app.main:app \
  --host "$HOST" --port "$PORT" \
  --log-level info \
  --workers "$WORKERS" \
  --limit-concurrency "$LIMIT_CONC" \
  --backlog "$BACKLOG" \
  --timeout-keep-alive "$KEEPALIVE"
