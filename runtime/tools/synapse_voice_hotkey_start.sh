#!/usr/bin/env bash
set -euo pipefail

# Starts synapse_voice_hotkey.ps1 as a detached hidden Windows PowerShell process.
#
# Usage:
#   bash runtime/tools/synapse_voice_hotkey_start.sh
#
# Stop:
#   Press Ctrl+Alt+Q (default ExitHotkey)
#
# Mode:
#   VOICE_MODE=push   (default) press Ctrl+Alt+Space, speak one phrase, it types it
#   VOICE_MODE=toggle press Ctrl+Alt+Space to arm/disarm; when armed it types phrases

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNAPSE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PS1_PATH="$SYNAPSE_ROOT/runtime/tools/synapse_voice_hotkey.ps1"

if ! grep -qi microsoft /proc/version 2>/dev/null; then
  echo "BLOCKED: this helper targets WSL (uses powershell.exe + Windows microphone)." >&2
  exit 2
fi

if ! command -v powershell.exe >/dev/null 2>&1; then
  echo "BLOCKED: powershell.exe not found." >&2
  exit 2
fi

WIN_PS1="$(wslpath -w "$PS1_PATH")"
MODE="${VOICE_MODE:-push}"

# Detached launch; leaves no running WSL process.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "\
  \$args = @(
    '-NoProfile',
    '-ExecutionPolicy','Bypass',
    '-File', '$WIN_PS1',
    '-Mode', '$MODE',
    '-PressEnter'
  );
  Start-Process -WindowStyle Hidden -FilePath powershell.exe -ArgumentList \$args | Out-Null
"

echo "OK: voice hotkey started (mode=$MODE). Hotkey=CTRL+ALT+SPACE Exit=CTRL+ALT+Q" >&2

