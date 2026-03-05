#!/usr/bin/env bash
set -euo pipefail

# Legacy shim: canonical wrapper is synapse_quest_run.sh.
# Keep this file only to prevent hard failures from stale references.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/synapse_quest_run.sh" "$@"
