#!/usr/bin/env bash
# dev.sh — run ticktap_wiki with automatic reload (uvicorn --reload)
#
# Usage:
#   ./dev.sh
#   WIKI_PORT=9090 ./dev.sh
#
# Then open http://localhost:8080  (not http://0.0.0.0:8080)
#
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

exec .venv/bin/uvicorn ticktap_wiki:app \
    --reload \
    --log-level info \
    --host "${WIKI_HOST:-0.0.0.0}" \
    --port "${WIKI_PORT:-8080}"
