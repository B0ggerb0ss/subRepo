#!/usr/bin/env bash
set -euo pipefail

SPACE_REPO="${1:-${HF_SPACE_REPO:-}}"
HF_TOKEN="${HF_TOKEN:-}"
SKIP_CHECKS="${SKIP_CHECKS:-0}"

if [[ -z "$SPACE_REPO" ]]; then
  echo "Usage: bash deploy_to_hf.sh <username/space-name>" >&2
  exit 1
fi

if [[ -z "$HF_TOKEN" ]]; then
  echo "Set HF_TOKEN before deploying." >&2
  exit 1
fi

if [[ "$SKIP_CHECKS" != "1" ]]; then
  bash run_tests.sh unit
  python scripts/run_all_gates.py
fi

git push "https://oauth2:${HF_TOKEN}@huggingface.co/spaces/${SPACE_REPO}" HEAD:main
