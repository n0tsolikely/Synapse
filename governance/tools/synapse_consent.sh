#!/usr/bin/env bash
set -euo pipefail

# synapse_consent.sh
# One-command Consent Gate helper for non-coders:
# - creates valid CONFIRM_R2 artifacts with sane toggles
# - uses America/Toronto as canonical timezone for date stamps
#
# Usage:
#   synapse_consent.sh deps-only [--scope DUNGEON_6]
#   synapse_consent.sh token-tests [--scope DUNGEON_6]
#   synapse_consent.sh schema-change --quest-id QUEST_154 [--scope DUNGEON_6]
#
# Environment:
#   DATA_ROOT (default $HOME/Ashby_Data)

export TZ="${TZ:-America/Toronto}"

DATA_ROOT="${DATA_ROOT:-$HOME/Ashby_Data}"
CONF_DIR="$DATA_ROOT/confirmations"
TODAY="$(date +%F)"

die() { echo "FAIL: $*" >&2; exit 2; }

usage() {
  cat <<'EOF'
synapse_consent.sh — Consent Gate helper (America/Toronto)

Commands:
  deps-only      Allow network egress for dependency installs ONLY (NO tokens, NO model downloads)
  token-tests    Allow network egress + real tokens for tests (NO model downloads)
  schema-change  Allow schema/state evolution for a specific quest (NO network, NO tokens, NO model downloads)

Options:
  --scope <SCOPE>       Default: DUNGEON_6
  --quest-id <QUEST_###> Required for schema-change

Examples:
  synapse_consent.sh deps-only --scope DUNGEON_6
  synapse_consent.sh token-tests --scope DUNGEON_6
  synapse_consent.sh schema-change --quest-id QUEST_154 --scope DUNGEON_6
EOF
}

confirm_write() {
  local path="$1"
  local content="$2"

  mkdir -p "$CONF_DIR"

  echo "ABOUT TO WRITE:"
  echo "  $path"
  echo ""
  echo "CONTENT:"
  echo "----------------------------------------"
  echo "$content"
  echo "----------------------------------------"
  echo ""
  read -r -p "Type YES to confirm: " ans
  if [[ "${ans:-}" != "YES" ]]; then
    echo "ABORTED: no file written."
    exit 3
  fi

  printf "%s\n" "$content" > "$path"
  echo "WROTE: $path"
}

cmd="${1:-}"
shift || true

scope="DUNGEON_6"
quest_id=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scope) scope="$2"; shift 2;;
    --quest-id) quest_id="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) die "unknown arg: $1";;
  esac
done

case "$cmd" in
  deps-only)
    fname="CONFIRM_R2__${scope}__${TODAY}__network_deps_only.txt"
    path="$CONF_DIR/$fname"
    content=$'CONFIRM: YES\nALLOW_NETWORK_EGRESS: YES\nALLOW_REAL_TOKENS: NO\nALLOW_MODEL_DOWNLOADS: NO\nEND'
    confirm_write "$path" "$content"
    ;;
  token-tests)
    fname="CONFIRM_R2__${scope}__${TODAY}__token_tests_allowed.txt"
    path="$CONF_DIR/$fname"
    content=$'CONFIRM: YES\nALLOW_NETWORK_EGRESS: YES\nALLOW_REAL_TOKENS: YES\nALLOW_MODEL_DOWNLOADS: NO\nEND'
    confirm_write "$path" "$content"
    ;;
  schema-change)
    [[ -n "$quest_id" ]] || die "schema-change requires --quest-id QUEST_###"
    fname="CONFIRM_R2__${quest_id}__${TODAY}__schema_state_change.txt"
    path="$CONF_DIR/$fname"
    content=$'CONFIRM: YES\nALLOW_NETWORK_EGRESS: NO\nALLOW_REAL_TOKENS: NO\nALLOW_MODEL_DOWNLOADS: NO\nEND'
    confirm_write "$path" "$content"
    ;;
  *)
    usage
    exit 2
    ;;
esac
