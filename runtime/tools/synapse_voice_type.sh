#!/usr/bin/env bash
set -euo pipefail

# WSL-only helper: dictation via Windows SpeechRecognition + optional typing.
# Usage:
#   bash runtime/tools/synapse_voice_type.sh --type --enter
#   bash runtime/tools/synapse_voice_type.sh --print
#
# Notes:
# - Focus the target window (e.g., Windows Terminal) before running with --type.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNAPSE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PS1_PATH="$SYNAPSE_ROOT/runtime/tools/synapse_voice_type.ps1"

if ! grep -qi microsoft /proc/version 2>/dev/null; then
  echo "BLOCKED: this helper targets WSL (uses powershell.exe + Windows microphone)." >&2
  exit 2
fi

if ! command -v powershell.exe >/dev/null 2>&1; then
  echo "BLOCKED: powershell.exe not found (required for Windows dictation)." >&2
  exit 2
fi

TYPE="NO"
ENTER="NO"
CULTURE="en-US"
SILENCE=5
END_MS=800

while [[ $# -gt 0 ]]; do
  case "$1" in
    --type) TYPE="YES"; shift ;;
    --enter) ENTER="YES"; shift ;;
    --print) TYPE="NO"; ENTER="NO"; shift ;;
    --culture) CULTURE="${2:-}"; shift 2 ;;
    --silence) SILENCE="${2:-}"; shift 2 ;;
    --end-ms) END_MS="${2:-}"; shift 2 ;;
    -h|--help)
      echo "synapse_voice_type.sh [--type] [--enter] [--print] [--culture en-US] [--silence N] [--end-ms MS]" >&2
      exit 0
      ;;
    *)
      echo "FAIL: unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

WIN_PS1="$(wslpath -w "$PS1_PATH")"

ARGS=(-NoProfile -ExecutionPolicy Bypass -File "$WIN_PS1" -Culture "$CULTURE" -InitialSilenceTimeoutSeconds "$SILENCE" -EndSilenceTimeoutMilliseconds "$END_MS")
if [[ "$TYPE" == "YES" ]]; then
  ARGS+=(-TypeToActiveWindow)
fi
if [[ "$ENTER" == "YES" ]]; then
  ARGS+=(-PressEnter)
fi

powershell.exe "${ARGS[@]}"

