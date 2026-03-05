# require_r2_confirmation.sh

Purpose: hard Consent Gate enforcement for R2 steps.

This script **fails fast** unless a valid confirmation artifact exists on disk and permits the requested capabilities.

## Typical usage patterns

### Network egress for dependency installs only (NO tokens)
```bash
Ashby_Data/tools/require_r2_confirmation.sh \
  --confirmations-dir "/home/notsolikely/Ashby_Data/confirmations" \
  --confirm-file "CONFIRM_R2__DUNGEON_6__2026-03-01__network_deps_only.txt" \
  --need-egress YES --need-tokens NO --need-model-downloads NO
```

### Token-backed tests allowed (YES tokens)
```bash
Ashby_Data/tools/require_r2_confirmation.sh \
  --confirmations-dir "/home/notsolikely/Ashby_Data/confirmations" \
  --confirm-file "CONFIRM_R2__DUNGEON_6__2026-03-01__token_tests_allowed.txt" \
  --need-egress YES --need-tokens YES --need-model-downloads NO
```

## Integrating into synapse_quest_run.sh (recommended)

Add a **mandatory preflight** in synapse_quest_run.sh before any step that could require R2:
- pip install / uv / poetry
- curl/wget
- external API calls (Gemini/OpenAI/etc)
- directory moves/deletes

Example snippet:
```bash
# Before networked step:
Ashby_Data/tools/require_r2_confirmation.sh \
  --confirmations-dir "$ASHBY_DATA/confirmations" \
  --confirm-file "$R2_CONFIRM_FILE" \
  --need-egress YES --need-tokens "$NEED_TOKENS" --need-model-downloads NO
```

Where `R2_CONFIRM_FILE` and `NEED_TOKENS` are set per Quest / per step.
