#!/usr/bin/env bash
set -euo pipefail

# Legacy shim: canonical wrapper is synapse_quest_run.sh.
# Keep this file only to prevent hard failures from stale references.
exec /home/notsolikely/Synapse_OS/governance/tools/synapse_quest_run.sh "$@"
