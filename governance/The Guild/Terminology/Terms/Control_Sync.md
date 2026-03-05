# TERM — Control Sync

## Definition
A Control Sync is a structured alignment mode where Hands and Brains:
- rehydrate state (what is true)
- review continuity artifacts
- make decisions
- declare scope for the current execution window

A Control Sync persists until explicitly ended by the authority role (Brains).

Conversation can be the medium, but Control Sync authority is recorded only in artifacts
(e.g., Snapshots, Guild Orders, Quest state moves).

## Purpose
Prevent drift by ensuring the next actions are bound to:
- the current state of the Subject (Data/Engine)
- the Codex (when frozen)
- declared scope (Guild Orders / accepted Quests)

## When It Applies
- start of each execution session/day (Dailies)
- resume after pause or rehydration
- any time direction/scope must change
- during both Fog of War and Fog Lifted

## Invocation
- Brains can open Control Sync by explicitly stating “Control Sync”.
- If the Subject is unknown or ambiguous, Hands MUST ask for the Subject key/scope before proceeding.

## What It Enables
- scope commitment (what will be done now)
- quest acceptance/rejection/re-scope (when execution is authorized)
- risk / consent decisions
- creation or update of governing artifacts (Guild Orders, Execution Packs) **only when explicitly directed**

## Control Sync Is NOT
- execution
- a place to silently advance workflow state
- a guarantee that anything was built/tested
- permission to ignore Locks or Codex

## End Rule
A Control Sync is closed only when exactly one end-of-Control-Sync Snapshot artifact is written to disk
(per the Snapshots law).

If that Snapshot cannot be written:
- Disclosure Gate triggers
- Control Sync remains OPEN
- execution authority does not advance

## Interactions
- Dailies begins with Control Sync.
- Control Sync outputs constrain Guild Orders, Dungeons, Quests, and Dailies.
- Binding decisions must live in Snapshot artifacts; chat-only decisions are non-authoritative.
