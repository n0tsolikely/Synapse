# LOCK — Snapshots (Types + Ordering)
**Locked:** 2026-01-31 19:20:21 (America/Montreal assumed)

## Canon meaning
Snapshots are continuity artifacts. They preserve state across time.

Snapshot types:
1) Control Sync Snapshot — decisions, scope, alignment state
2) End-of-Day Snapshot — execution receipts (what happened, how, why not)
3) General Snapshot — ad-hoc capture without implying alignment/execution

## Required ordering on rehydration
When resuming a Subject:
1) Review the most recent Control Sync Snapshot (intent + decisions)
2) Then review the most recent End-of-Day Snapshot (execution reality)

This ordering prevents false assumptions.

## Control Sync Snapshot rules
- May list Quest statuses (done/attempted/incomplete)
- Must not be treated as execution proof by itself

## End-of-Day Snapshot rules
- Must contain execution path for incomplete work (why, blockers, what was tried)
- Must support Truth Gate claims with technical context
- Must not “just say incomplete” without explaining why

## General Snapshot rules
- Used to preserve context when neither control sync nor EOD applies

## Do not assume
- Snapshots are not full transcripts
- EOD is not planning; Control Sync is not execution
- Snapshots do not replace audits (receipts)
