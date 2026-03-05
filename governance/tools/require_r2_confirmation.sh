#!/usr/bin/env bash
set -euo pipefail

# require_r2_confirmation.sh
# Governance-level hard Consent Gate for R2 actions.
#
# This belongs in Synapse/governance/tools (UNIVERSAL layer),
# not subject Data.

CONF_DIR=""
CONF_FILE=""
NEED_EGRESS="NO"
NEED_TOKENS="NO"
NEED_MODELS="NO"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --confirmations-dir) CONF_DIR="$2"; shift 2;;
    --confirm-file) CONF_FILE="$2"; shift 2;;
    --need-egress) NEED_EGRESS="$2"; shift 2;;
    --need-tokens) NEED_TOKENS="$2"; shift 2;;
    --need-model-downloads) NEED_MODELS="$2"; shift 2;;
    *) echo "Unknown arg: $1" >&2; exit 2;;
  esac
done

if [[ -z "$CONF_DIR" || -z "$CONF_FILE" ]]; then
  echo "ERROR: --confirmations-dir and --confirm-file required" >&2
  exit 2
fi

PATH_F="$CONF_DIR/$CONF_FILE"
if [[ ! -f "$PATH_F" ]]; then
  echo "R2 BLOCKED: confirmation file missing: $PATH_F" >&2
  exit 2
fi

if ! grep -qx "CONFIRM: YES" "$PATH_F"; then
  echo "R2 BLOCKED: confirmation missing exact 'CONFIRM: YES'" >&2
  exit 2
fi

ALLOW_EGRESS="$(grep -E '^ALLOW_NETWORK_EGRESS:' "$PATH_F" | awk '{print $2}' || true)"
ALLOW_TOKENS="$(grep -E '^ALLOW_REAL_TOKENS:' "$PATH_F" | awk '{print $2}' || true)"
ALLOW_MODELS="$(grep -E '^ALLOW_MODEL_DOWNLOADS:' "$PATH_F" | awk '{print $2}' || true)"

ALLOW_EGRESS="${ALLOW_EGRESS:-NO}"
ALLOW_TOKENS="${ALLOW_TOKENS:-NO}"
ALLOW_MODELS="${ALLOW_MODELS:-NO}"

need_yes() { [[ "${1^^}" == "YES" ]]; }
allowed_yes() { [[ "${1^^}" == "YES" ]]; }

if need_yes "$NEED_EGRESS" && ! allowed_yes "$ALLOW_EGRESS"; then
  echo "R2 BLOCKED: network egress not permitted" >&2
  exit 3
fi

if need_yes "$NEED_TOKENS" && ! allowed_yes "$ALLOW_TOKENS"; then
  echo "R2 BLOCKED: real tokens not permitted" >&2
  exit 3
fi

if need_yes "$NEED_MODELS" && ! allowed_yes "$ALLOW_MODELS"; then
  echo "R2 BLOCKED: model downloads not permitted" >&2
  exit 3
fi

echo "R2 CONFIRMATION OK: $PATH_F"
exit 0
