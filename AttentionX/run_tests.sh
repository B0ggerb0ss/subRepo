#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-all}"

export PYTHONPATH="${PWD}:${PYTHONPATH:-}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/attentionx-mpl}"
export NUMBA_CACHE_DIR="${NUMBA_CACHE_DIR:-/tmp/attentionx-numba}"

mkdir -p "$MPLCONFIGDIR" "$NUMBA_CACHE_DIR"

case "$MODE" in
  unit)
    pytest tests/unit -q
    ;;
  integration)
    pytest tests/integration -q
    ;;
  all)
    pytest tests/unit tests/integration -q
    ;;
  *)
    echo "Usage: bash run_tests.sh [unit|integration|all]" >&2
    exit 1
    ;;
esac
