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
  e2e)
    pytest tests/e2e -q
    ;;
  all)
    pytest tests/unit tests/integration -q
    ;;
  full)
    pytest tests/unit tests/integration tests/e2e -q
    ;;
  *)
    echo "Usage: bash run_tests.sh [unit|integration|e2e|all|full]" >&2
    exit 1
    ;;
esac
