#!/usr/bin/env bash
set -euo pipefail

# Synapse Quest Runner Wrapper (Deterministic Receipt Capture)
# Version: v1.5
# Last Updated: 2026-03-09
#
# Purpose:
# - Ensure audit receipts are captured DURING execution (not fabricated after).
# - Create/resolve the correct audit bundle path deterministically from the quest filename.
# - Append command outputs into 06_TESTS.txt (CMD/RC lines).
# - Record changed files into 06_CHANGED_FILES.txt at finalize.
# - Run synapse_governance_guard.py validate at finalize.
#
# Defaults are subject-driven; override via env vars as needed.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNAPSE_ROOT="${SYNAPSE_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
SUBJECT="${SUBJECT:-}"
DATA_ROOT="${DATA_ROOT:-}"
ENGINE_ROOT="${ENGINE_ROOT:-}"
GUARD="${GUARD:-$SYNAPSE_ROOT/runtime/tools/synapse_governance_guard.py}"
SNAPSHOT_WRITER="${SNAPSHOT_WRITER:-$SYNAPSE_ROOT/runtime/tools/synapse_snapshot_writer.py}"
SELECTION_METHOD=""
SOURCE_DETAIL=""
SUBJECT_CONTEXT_READY="NO"
RUNTIME_DIR=""
WAVE_FILE=""

_resolve_subject_context() {
  local args
  args=(resolve-subject --shell)
  if [[ -n "${SUBJECT:-}" ]]; then
    args+=(--subject "$SUBJECT")
  fi
  if [[ -n "${DATA_ROOT:-}" ]]; then
    args+=(--data-root "$DATA_ROOT")
  fi
  if [[ -n "${ENGINE_ROOT:-}" ]]; then
    args+=(--engine-root "$ENGINE_ROOT")
  fi

  local out
  if ! out="$(python3 "$SYNAPSE_ROOT/runtime/synapse.py" "${args[@]}" 2>&1)"; then
    echo "BLOCKED: subject resolution failed." >&2
    echo "$out" >&2
    echo "Hint: run 'python3 $SYNAPSE_ROOT/runtime/synapse.py focus' first." >&2
    exit 2
  fi

  while IFS='=' read -r k v; do
    case "$k" in
      SUBJECT) SUBJECT="$v" ;;
      DATA_ROOT) DATA_ROOT="$v" ;;
      ENGINE_ROOT) ENGINE_ROOT="$v" ;;
      SELECTION_METHOD) SELECTION_METHOD="$v" ;;
      SOURCE_DETAIL) SOURCE_DETAIL="$v" ;;
    esac
  done <<< "$out"

  RUNTIME_DIR="$DATA_ROOT/.governance_runtime"
  WAVE_FILE="$RUNTIME_DIR/quest_wave_receipts.tsv"
  SUBJECT_CONTEXT_READY="YES"
}

ensure_subject_context() {
  if [[ "$SUBJECT_CONTEXT_READY" == "YES" ]]; then
    return 0
  fi
  _resolve_subject_context
}

require_explicit_subject_source() {
  local reason="$1"
  if [[ "$SELECTION_METHOD" != "flag" && "$SELECTION_METHOD" != "lockfile" ]]; then
    echo "BLOCKED: $reason requires explicit subject source (flag or lockfile)." >&2
    echo "Current subject source: selection_method=$SELECTION_METHOD source_detail=$SOURCE_DETAIL" >&2
    echo "Run: python3 $SYNAPSE_ROOT/runtime/synapse.py focus" >&2
    return 2
  fi
  return 0
}

enforce_elastic_gate() {
  local risk="$1"
  local action="$2"
  local out
  if ! out="$(python3 "$SYNAPSE_ROOT/runtime/synapse.py" enforce --risk "$risk" --tool "synapse_quest_run.sh" --action "$action" 2>&1)"; then
    echo "$out" >&2
    return 2
  fi
  if [[ -n "$out" ]]; then
    echo "$out" >&2
  fi
  return 0
}

slugify() {
  echo "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/_/g; s/^_+|_+$//g'
}

find_quest_file() {
  local qid="$1"
  local p
  p=$(ls "$DATA_ROOT/Quest Board/Accepted/${qid}__"*.txt 2>/dev/null | head -n 1 || true)
  echo "$p"
}

parse_date_from_filename() {
  local base="$1"
  # Prefer explicit filename suffix ...__YYYY-MM-DD.txt.
  # Fallback to local current date when quest files do not embed date.
  local d
  d=$(echo "$base" | sed -nE 's/.*__([0-9]{4}-[0-9]{2}-[0-9]{2})\.txt$/\1/p')
  if [ -z "$d" ]; then
    d="$(date +%F)"
  fi
  echo "$d"
}

slug_from_filename() {
  local base="$1"
  # base is the quest filename (basename), with or without trailing date token.
  # Extract middle title chunk between quest id prefix and optional date suffix.
  local mid
  mid=$(echo "$base" | sed -E 's/^(QUEST_[0-9]{3}|SIDE-QUEST_[0-9]{3})__//; s/__([0-9]{4}-[0-9]{2}-[0-9]{2})$//; s/\.txt$//')
  slugify "$mid"
}

bundle_path() {
  local qid="$1"; local date="$2"; local slug="$3"
  echo "$DATA_ROOT/Audits/Execution/${qid}__${date}__${slug}"
}

ensure_bundle() {
  local qid="$1"; local qfile="$2"; local date="$3"; local slug="$4"
  local b
  b=$(bundle_path "$qid" "$date" "$slug")
  if [ ! -d "$b" ]; then
    local guard_out
    guard_out=$(python3 "$GUARD" --data-root "$DATA_ROOT" --subject "$SUBJECT" init-bundle --quest-id "$qid" --slug "$slug" --date "$date")
    b=$(echo "$guard_out" | tail -n 1 | tr -d '\r' | sed -E 's/^OK: initialized[[:space:]]+//')
  fi
  echo "$b"
}

ensure_tests_header() {
  local tests="$1"
  if [ -f "$tests" ] && grep -q "PLACEHOLDER" "$tests"; then
    {
      echo "## Command Receipt Log"
      echo "WRAPPER: synapse_quest_run.sh"
      echo "ENGINE_ROOT: $ENGINE_ROOT"
      echo "DATA_ROOT: $DATA_ROOT"
      echo "WRAPPER_VALIDATE_MARKER: YES"
      echo "---"
    } > "$tests"
  fi
}

ensure_validate_marker() {
  local tests="$1"
  if [ ! -f "$tests" ]; then
    return 0
  fi
  if ! grep -Eq '^WRAPPER_VALIDATE_MARKER:[[:space:]]*YES[[:space:]]*$' "$tests"; then
    echo "WRAPPER_VALIDATE_MARKER: YES" >> "$tests"
  fi
}

_wrapper_sha256() {
  local wrapper_path="$SCRIPT_DIR/synapse_quest_run.sh"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$wrapper_path" | awk '{print $1}'
    return 0
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$wrapper_path" | awk '{print $1}'
    return 0
  fi
  python3 - "$wrapper_path" <<'PY'
import hashlib
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
print(hashlib.sha256(path.read_bytes()).hexdigest())
PY
}

_commands_count() {
  local tests="$1"
  local count
  count="$(grep -Ec '^[[:space:]]*CMD:[[:space:]]' "$tests" || true)"
  echo "$count" | tr -d ' '
}

write_wrapper_proof() {
  local bundle="$1"
  local tests="$2"
  local out="$bundle/06_WRAPPER_PROOF.json"
  local wrapper_path="$SCRIPT_DIR/synapse_quest_run.sh"
  local wrapper_sha
  local commands_count
  local bundle_real

  wrapper_sha="$(_wrapper_sha256)"
  commands_count="$(_commands_count "$tests")"
  bundle_real="$(cd "$bundle" && pwd)"

  python3 - "$out" "$wrapper_path" "$wrapper_sha" "$commands_count" "$bundle_real" <<'PY'
import json
import pathlib
import sys

out = pathlib.Path(sys.argv[1])
payload = {
    "schema_version": 1,
    "wrapper": "synapse_quest_run.sh",
    "wrapper_path": str(pathlib.Path(sys.argv[2]).resolve()),
    "wrapper_sha256": sys.argv[3],
    "commands_count": int(sys.argv[4]),
    "bundle_path": str(pathlib.Path(sys.argv[5]).resolve()),
}
out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

run_cmd() {
  local tests="$1"; shift
  local cmd="$*"
  ensure_tests_header "$tests"
  ensure_validate_marker "$tests"

  echo "CMD: $cmd" | tee -a "$tests"
  ( cd "$ENGINE_ROOT" && bash -lc "$cmd" ) 2>&1 | tee -a "$tests"
  local rc=${PIPESTATUS[0]}
  echo "RC: $rc" | tee -a "$tests"
  return "$rc"
}

python_check() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "BLOCKED: python3 not found in active environment. Activate your environment."
    return 1
  fi
  if ! python3 -c "import sys; print(sys.executable)" >/dev/null 2>&1; then
    echo "BLOCKED: python3 is not usable in active environment. Activate your environment."
    return 1
  fi
  return 0
}

maybe_check_deps() {
  # Lightweight import preflight based on command string
  local cmd="$1"
  local mods=()

  case "$cmd" in
    *pytest*) mods+=("pytest") ;;
  esac
  case "$cmd" in
    *httpx*) mods+=("httpx") ;;
  esac
  case "$cmd" in
    *pydantic*) mods+=("pydantic") ;;
  esac
  case "$cmd" in
    *fastapi*) mods+=("fastapi") ;;
  esac

  if [ "${#mods[@]}" -eq 0 ]; then
    return 0
  fi

  local m
  for m in "${mods[@]}"; do
    if ! python3 -c "import ${m}" >/dev/null 2>&1; then
      echo "BLOCKED: missing dependency '${m}'. Activate your environment or install dependencies (may require R2 consent)."
      return 1
    fi
  done
  return 0
}

mark_blocked() {
  local bundle="$1"
  local reason="$2"
  local cmd="$3"
  local out="$bundle/00_SUMMARY.md"
  {
    echo ""
    echo "## BLOCKED"
    echo "- REASON: $reason"
    echo "- COMMAND: $cmd"
    echo "- STATUS: BLOCKED"
    echo "- RECEIPT: 06_TESTS.txt"
  } >> "$out"
}

maybe_require_r2() {
  # Heuristic R2 preflight for network/destructive steps executed via this wrapper.
  # If triggered, requires env var R2_CONFIRM_FILE and validates toggles against confirmation artifact.
  local cmd="$1"

  local need_r2="NO"
  local need_egress="NO"
  local need_tokens="${NEED_TOKENS:-NO}"
  local need_models="${NEED_MODEL_DOWNLOADS:-NO}"

  # Network-ish triggers (package pulls / registry / remote fetch)
  if echo "$cmd" | grep -Eqi '(^|[[:space:]])(pip[[:space:]]+install|pip3[[:space:]]+install|uv[[:space:]]+pip|poetry[[:space:]]+add|poetry[[:space:]]+install|curl[[:space:]]|wget[[:space:]]|git[[:space:]]+(clone|fetch|pull)|npm[[:space:]]+install|pnpm[[:space:]]+install|yarn[[:space:]]+add)'; then
    need_r2="YES"
    need_egress="YES"
  fi

  # Explicit URL mention is treated as egress risk (non-localhost)
  if echo "$cmd" | grep -Eqi 'https?://'; then
    if ! echo "$cmd" | grep -Eqi 'https?://(localhost|127\.0\.0\.1)'; then
      need_r2="YES"
      need_egress="YES"
    fi
  fi

  # Destructive ops triggers
  if echo "$cmd" | grep -Eqi '(^|[[:space:]])(rm[[:space:]]+-rf|rm[[:space:]]+-r|rm[[:space:]]|mv[[:space:]]|rmdir[[:space:]]|git[[:space:]]+rm)'; then
    need_r2="YES"
  fi

  if [[ "$need_r2" != "YES" ]]; then
    return 0
  fi

  if ! enforce_elastic_gate "R2" "r2_command_preflight"; then
    return 2
  fi

  if ! require_explicit_subject_source "R2-gated command"; then
    return 2
  fi

  if [[ -z "${R2_CONFIRM_FILE:-}" ]]; then
    echo "R2 BLOCKED: command matches R2 trigger heuristic but R2_CONFIRM_FILE is not set." >&2
    echo "Set: export R2_CONFIRM_FILE='CONFIRM_R2__...txt' (must exist in $DATA_ROOT/confirmations)" >&2
    return 2
  fi

  local gate_dir
  gate_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  local gate="$gate_dir/require_r2_confirmation.sh"
  if [[ ! -x "$gate" ]]; then
    echo "R2 BLOCKED: missing gate tool at $gate (install require_r2_confirmation.sh in same tools dir)" >&2
    return 2
  fi

  "$gate" \
    --confirmations-dir "$DATA_ROOT/confirmations" \
    --confirm-file "$R2_CONFIRM_FILE" \
    --need-egress "$need_egress" \
    --need-tokens "$need_tokens" \
    --need-model-downloads "$need_models"
}

record_changed_files() {
  local out="$1"
  if command -v git >/dev/null 2>&1 && [ -d "$ENGINE_ROOT/.git" ]; then
    ( cd "$ENGINE_ROOT" && git status --porcelain=v1 | awk '{print $2}' | sort -u ) > "$out" || true
    if [ ! -s "$out" ]; then
      echo "NONE" > "$out"
    fi
  else
    echo "NONE" > "$out"
  fi
}

usage() {
  echo "Usage: synapse_quest_run.sh init|cmd|finalize|complete QUEST_ID [command...]" >&2
  echo "Env overrides: DATA_ROOT ENGINE_ROOT SUBJECT GUARD SNAPSHOT_WRITER" >&2
}

ensure_runtime() {
  mkdir -p "$RUNTIME_DIR"
  if [ ! -f "$WAVE_FILE" ]; then
    : > "$WAVE_FILE"
  fi
}

append_wave_receipt() {
  local qid="$1"; local qbase="$2"; local bundle="$3"
  ensure_runtime
  printf "%s\t%s\t%s\t%s\n" "$(_now_iso)" "$qid" "$qbase" "$bundle" >> "$WAVE_FILE"
}

accepted_count() {
  local dir="$DATA_ROOT/Quest Board/Accepted"
  local n
  n=$(find "$dir" -maxdepth 1 -type f \( -name "QUEST_*.txt" -o -name "SIDE-QUEST_*.txt" \) | wc -l | tr -d ' ')
  echo "$n"
}

_quest_title_from_basename() {
  local base="$1"
  echo "$base" | sed -E 's/^(QUEST_[0-9]{3}|SIDE-QUEST_[0-9]{3})__//; s/__([0-9]{4}-[0-9]{2}-[0-9]{2})\.txt$//; s/__+/ — /g'
}

_now_iso() {
  date -Iseconds
}

_write_wave_blocks() {
  local work_file="$1"
  local completed_file="$2"
  local verification_file="$3"
  local resume_file="$4"

  : > "$work_file"
  : > "$completed_file"
  : > "$verification_file"
  : > "$resume_file"

  while IFS=$'\t' read -r ts qid qbase bundle; do
    [ -n "$qid" ] || continue
    local title
    title="$(_quest_title_from_basename "$qbase")"

    {
      echo "- Quest ID + Title: $qid — $title"
      echo "  - Status at end of day: COMPLETED"
      echo "  - Preconditions referenced: quest in Accepted + validated bundle gate before move"
      echo "  - Actions performed: see $bundle/06_TESTS.txt"
      echo "  - Artifacts changed: $bundle/06_CHANGED_FILES.txt"
      echo "  - Completion audit: $bundle/01_COMPLETION_AUDIT.md"
      echo "  - Summary: $bundle/00_SUMMARY.md"
    } >> "$work_file"

    {
      echo "- $qid — $title"
      echo "  - Proof: $bundle"
      echo "  - Completion audit: $bundle/01_COMPLETION_AUDIT.md"
    } >> "$completed_file"

    {
      echo "- $qid"
      if [ -f "$bundle/06_TESTS.txt" ]; then
        echo "  - Command receipts:"
        grep -E '^(CMD:|RC:)' "$bundle/06_TESTS.txt" | tail -n 6 | sed 's/^/    /'
      else
        echo "  - Command receipts: MISSING (expected $bundle/06_TESTS.txt)"
      fi
      echo "  - Completion receipt: $bundle/01_COMPLETION_AUDIT.md"
    } >> "$verification_file"
  done < "$WAVE_FILE"

  {
    echo "- Tomorrow's Control Sync must start by reviewing latest Control Sync + this EOD snapshot."
    echo "- Known blockers: none recorded in completed wave; verify new Accepted queue before execution."
    echo "- Next recommended Quests: accept next board stack per active Guild Orders."
    echo "- Rehydration notes: use Latest Rehydration Pack continuity lock and this EOD for resume anchor."
  } >> "$resume_file"
}

auto_eod_if_wave_finished() {
  local remaining
  remaining="$(accepted_count)"
  if [ "$remaining" != "0" ]; then
    return 0
  fi
  if [ ! -s "$WAVE_FILE" ]; then
    return 0
  fi
  if [ "${REQUIRE_EOD_ON_EMPTY_ACCEPTED:-YES}" != "YES" ]; then
    return 0
  fi
  if ! enforce_elastic_gate "R2" "auto_eod_snapshot"; then
    return 5
  fi
  if ! require_explicit_subject_source "automatic EOD snapshot write"; then
    return 5
  fi
  if [ ! -f "$SNAPSHOT_WRITER" ]; then
    echo "BLOCKED: SNAPSHOT_WRITER not found at $SNAPSHOT_WRITER" >&2
    return 5
  fi

  local tmpdir work completed verification resume incomplete bugs raid talent
  tmpdir="$(mktemp -d)"
  work="$tmpdir/work.txt"
  completed="$tmpdir/completed.txt"
  verification="$tmpdir/verification.txt"
  resume="$tmpdir/resume.txt"
  incomplete="$tmpdir/incomplete.txt"
  bugs="$tmpdir/bugs.txt"
  raid="$tmpdir/raid.txt"
  talent="$tmpdir/talent.txt"

  _write_wave_blocks "$work" "$completed" "$verification" "$resume"
  echo "- (none)" > "$incomplete"
  echo "- No additional bugs discovered beyond quest-level logs; see execution bundles for details." > "$bugs"
  echo "- (none)" > "$raid"
  echo "- (none)" > "$talent"

  if ! python3 "$SNAPSHOT_WRITER" \
    --data-root "$DATA_ROOT" \
    --subject "$SUBJECT" \
    eod \
    --topic "Auto EOD: Accepted queue drained after validated quest wave" \
    --work-file "$work" \
    --completed-file "$completed" \
    --incomplete-file "$incomplete" \
    --verification-file "$verification" \
    --bugs-file "$bugs" \
    --raid-file "$raid" \
    --talent-file "$talent" \
    --resume-file "$resume"; then
    echo "BLOCKED: automatic EOD snapshot write failed." >&2
    rm -rf "$tmpdir"
    return 5
  fi

  : > "$WAVE_FILE"
  rm -rf "$tmpdir"
  echo "AUTO_EOD: PASS (Accepted queue empty and detailed EOD written)"
  return 0
}

cmd_init() {
  ensure_subject_context
  enforce_elastic_gate "R1" "init_bundle" || { echo "BLOCKED: elastic gate denied init"; exit 3; }
  python_check || { echo "BLOCKED: python3 unusable"; exit 3; }
  local qid="$1"
  local qfile
  qfile="$(find_quest_file "$qid")"
  [ -n "$qfile" ] || { echo "FAIL: quest not in Accepted: $qid" >&2; exit 2; }

  local base date slug
  base="$(basename "$qfile")"
  date="$(parse_date_from_filename "$base")"
  [ -n "$date" ] || { echo "FAIL: could not parse date from quest filename: $base" >&2; exit 2; }

  slug="$(slug_from_filename "$base")"
  [ -n "$slug" ] || { echo "FAIL: could not derive slug from quest filename: $base" >&2; exit 2; }

  local b
  b="$(ensure_bundle "$qid" "$qfile" "$date" "$slug")"
  echo "OK: bundle $b"
}

cmd_cmd() {
  ensure_subject_context
  enforce_elastic_gate "R1" "run_command" || { echo "BLOCKED: elastic gate denied command execution"; exit 3; }
  python_check || { echo "BLOCKED: python3 unusable"; exit 3; }
  local qid="$1"; shift
  local cmd_str="$*"
  [ -n "$cmd_str" ] || { echo "FAIL: command required" >&2; exit 2; }

  local qfile
  qfile="$(find_quest_file "$qid")"
  [ -n "$qfile" ] || { echo "FAIL: quest not in Accepted: $qid" >&2; exit 2; }

  local base date slug
  base="$(basename "$qfile")"
  date="$(parse_date_from_filename "$base")"
  slug="$(slug_from_filename "$base")"

  local b tests
  b="$(ensure_bundle "$qid" "$qfile" "$date" "$slug")"
  tests="$b/06_TESTS.txt"

  # R2 Consent Gate heuristic preflight (network/destructive ops)
  if ! maybe_require_r2 "$cmd_str"; then
    echo "BLOCKED: R2 confirmation required (or invalid) for command: $cmd_str" | tee -a "$b/00_SUMMARY.md"
    mark_blocked "$b" "R2_CONFIRMATION_REQUIRED" "$cmd_str"
    exit 3
  fi

  # Dependency preflight (fails fast with actionable message)
  if ! maybe_check_deps "$cmd_str"; then
    echo "BLOCKED: dependency preflight failed. Activate your environment or install dependencies." | tee -a "$b/00_SUMMARY.md"
    mark_blocked "$b" "DEPENDENCY_PREFLIGHT_FAILED" "$cmd_str"
    exit 3
  fi

  if ! run_cmd "$tests" "$cmd_str"; then
    echo "BLOCKED: command failed (see RC above): $cmd_str" | tee -a "$b/00_SUMMARY.md" "$tests"
    mark_blocked "$b" "COMMAND_FAILED" "$cmd_str"
    exit 3
  fi
}

cmd_finalize() {
  ensure_subject_context
  enforce_elastic_gate "R1" "finalize_bundle" || { echo "BLOCKED: elastic gate denied finalize"; exit 3; }
  local qid="$1"

  local qfile
  qfile="$(find_quest_file "$qid")"
  [ -n "$qfile" ] || { echo "FAIL: quest not in Accepted: $qid" >&2; exit 2; }

  local base date slug
  base="$(basename "$qfile")"
  date="$(parse_date_from_filename "$base")"
  slug="$(slug_from_filename "$base")"

  local b tests changed
  b="$(ensure_bundle "$qid" "$qfile" "$date" "$slug")"
  tests="$b/06_TESTS.txt"
  changed="$b/06_CHANGED_FILES.txt"

  ensure_tests_header "$tests"
  ensure_validate_marker "$tests"
  record_changed_files "$changed"
  write_wrapper_proof "$b" "$tests"

  local allow_ooo_flag=""
  if [[ "${ALLOW_OUT_OF_ORDER:-NO}" == "YES" ]]; then
    allow_ooo_flag="--allow-out-of-order"
  fi

  if python3 "$GUARD" --data-root "$DATA_ROOT" --subject "$SUBJECT" validate --quest-id "$qid" --bundle "$b" $allow_ooo_flag 2>&1 | tee -a "$tests"; then
    echo "OK: finalize complete (validation PASS recorded)." | tee -a "$tests"
    echo "ALLOW_COMPLETE: $qid"
  else
    echo "BLOCKED: governance validate failed (see output above)." | tee -a "$b/00_SUMMARY.md" "$tests"
    exit 4
  fi
}

cmd_complete() {
  ensure_subject_context
  local qid="$1"
  if ! enforce_elastic_gate "R2" "accepted_to_completed"; then
    exit 5
  fi
  if ! require_explicit_subject_source "quest state transition (Accepted -> Completed)"; then
    exit 5
  fi
  cmd_finalize "$qid"

  local qfile
  qfile="$(find_quest_file "$qid")"
  [ -n "$qfile" ] || { echo "FAIL: quest not in Accepted after finalize: $qid" >&2; exit 2; }

  local completed_dir
  completed_dir="$DATA_ROOT/Quest Board/Completed"
  mkdir -p "$completed_dir"

  local base date slug bundle pre_remaining
  base="$(basename "$qfile")"
  date="$(parse_date_from_filename "$base")"
  slug="$(slug_from_filename "$base")"
  bundle="$(bundle_path "$qid" "$date" "$slug")"
  pre_remaining="$(accepted_count)"

  local tests changed
  tests="$bundle/06_TESTS.txt"
  changed="$bundle/06_CHANGED_FILES.txt"

  local -a complete_args
  complete_args=(
    complete-quest "$qid"
    --subject "$SUBJECT"
    --data-root "$DATA_ROOT"
    --engine-root "$ENGINE_ROOT"
    --json
  )

  local milestone_entry
  while IFS= read -r milestone_entry; do
    [[ -n "$milestone_entry" ]] || continue
    complete_args+=(--milestone-status "$milestone_entry")
  done < <(
    python3 - "$SYNAPSE_ROOT" "$SUBJECT" "$DATA_ROOT" "$qfile" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "runtime"))
from synapse_runtime.quest_acceptance import parse_quest_document
from synapse_runtime.quest_completion import _parse_defined_milestones

subject = sys.argv[2]
data_root = Path(sys.argv[3])
quest_path = Path(sys.argv[4])
doc = parse_quest_document(subject=subject, data_root=data_root, path=quest_path)
for item in _parse_defined_milestones(doc.milestones_raw, doc.objective):
    detail = item["text"].replace(":", " - ")
    print(f"{item['id']}:DONE:{detail}")
PY
  )

  complete_args+=(--check "GOVERNANCE_GUARD:PASS:Validated governed quest bundle")
  complete_args+=(--check "WRAPPER_PROOF:PASS:Wrapper receipts and proof file recorded")
  complete_args+=(--receipt-ref "$tests" --receipt-ref "$changed" --receipt-ref "$bundle/06_WRAPPER_PROOF.json")

  if [ -f "$tests" ]; then
    while IFS= read -r line; do
      [[ -n "$line" ]] || continue
      complete_args+=(--command-run "$line")
    done < <(grep -E '^CMD:[[:space:]]' "$tests" | sed -E 's/^CMD:[[:space:]]*//')
  fi

  if [ -f "$changed" ]; then
    while IFS= read -r line; do
      [[ -n "$line" && "$line" != "NONE" ]] || continue
      complete_args+=(--changed-file "$line")
    done < "$changed"
  fi

  local complete_json
  if ! complete_json="$(python3 "$SYNAPSE_ROOT/runtime/synapse.py" "${complete_args[@]}")"; then
    echo "BLOCKED: quest completion mutation failed." >&2
    echo "$complete_json" >&2
    exit 4
  fi
  echo "$complete_json"

  local final_state active_path
  final_state="$(printf '%s' "$complete_json" | python3 -c 'import json,sys; payload=json.load(sys.stdin); print(payload["completion"]["final_state_decision"])')"
  active_path="$(printf '%s' "$complete_json" | python3 -c 'import json,sys; payload=json.load(sys.stdin); print(payload["completion"]["active_path"])')"

  if [ "$final_state" != "COMPLETED" ]; then
    echo "BLOCKED: quest remains active after completion audit ($final_state)." >&2
    exit 4
  fi

  append_wave_receipt "$qid" "$(basename "$active_path")" "$bundle"
  echo "MOVED_TO_COMPLETED: $(basename "$active_path")"

  # Hard enforcement: when final Accepted quest is completed, EOD snapshot must be written.
  if [ "$pre_remaining" = "1" ]; then
    if ! auto_eod_if_wave_finished; then
      echo "BLOCKED: required EOD snapshot could not be written after completion." >&2
      exit 5
    fi
  fi
}

main() {
  local action="${1:-}"; local qid="${2:-}"
  if [[ "$action" == "-h" || "$action" == "--help" ]]; then
    usage
    exit 0
  fi
  if [ -z "$action" ] || [ -z "$qid" ]; then
    usage
    exit 2
  fi
  case "$action" in
    init) cmd_init "$qid" ;;
    cmd) shift 2; cmd_cmd "$qid" "$@" ;;
    finalize) cmd_finalize "$qid" ;;
    complete) cmd_complete "$qid" ;;
    *) usage; exit 2 ;;
  esac
}

main "$@"
