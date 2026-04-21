#!/usr/bin/env bash
# Backward-compatible wrapper. Prefer scripts/run_v100_local.sh.

set -euo pipefail
cd "$(dirname "$0")"

exec bash run_v100_local.sh "$@"
