# synapse_consent.sh

Goal: make Consent Gate usable for non-coders.

Instead of hand-writing confirmation files, run one command that:
- uses **America/Toronto** date stamps
- prints exactly what will be written
- requires typing **YES** in terminal
- writes a valid `CONFIRM_R2__...` artifact under `<DataRoot>/confirmations/`

This preserves auditability (files exist) without manual file editing.

## Examples

Dependency installs only (no tokens):
```bash
$SYNAPSE_ROOT/governance/tools/synapse_consent.sh deps-only --scope DUNGEON_6
```

Token-backed tests allowed:
```bash
$SYNAPSE_ROOT/governance/tools/synapse_consent.sh token-tests --scope DUNGEON_6
```

Schema/state change for one quest (no network):
```bash
$SYNAPSE_ROOT/governance/tools/synapse_consent.sh schema-change --quest-id QUEST_154 --scope DUNGEON_6
```
