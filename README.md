# Synapse

*Repo-local governed continuity for autonomous executors.*

Synapse is intended to become a repo-local governed continuity kernel for autonomous executors.
Today it is implemented as a cooperative runtime plus governance corpus for AI-assisted engineering.
It is built for the layer that normal repos usually lose: story, rationale, intent, current truth, accepted work, proof, and direction over time.

A repo usually tells you what code exists.
It usually does not tell you:
- why the code became that way
- what the system is trying to become
- which parts are canonical versus provisional
- what was verified versus guessed
- what work is ambient, what is proposed, and what is officially accepted
- how to resume correctly without re-explaining the whole project to the next agent

That is the gap Synapse is trying to close.

Synapse does not try to replace your agent, your runtime, or your persona.
It governs execution, continuity, proof, and handoff.

Bring your own agent.
Bring your own runtime.
Bring your own persona.
Synapse adds governed continuity.

This Synapse is **not** Matrix Synapse, Azure Synapse, or a generic "agent framework" wrapper.
This repo is specifically about governed execution, continuity artifacts, audits, subject focus, resumable state, and durable project memory for real engineering work.

## Status

Synapse is still a work in progress.
It is real, usable, and already doing important runtime work, but it is not finished.
The architecture is still being hardened.
The automation layer is still being expanded.
The docs and operator surfaces are still catching up to what the runtime can actually do.

So the honest status is:
- real
- active
- evolving
- not final

## The core problem

Agents can read code.
That does **not** mean they understand the project.

If you hand a repo to a fresh agent, it can inspect files, tests, configs, and structure.
What it usually cannot infer correctly is the project story:
- what the team decided
- what direction the system is heading in
- what was intentionally minimal versus unfinished
- what work is currently active
- which constraints are binding
- what was attempted and why
- where execution is legally allowed versus still exploratory

That missing story is where projects drift.
People re-explain the same vision over and over.
Agents repeat work, miss intent, misread partial implementations, and treat scaffolding like finished architecture.

Synapse exists to make that story durable inside the repo-local project memory itself.

## What Synapse is

Synapse is:
- a repo-local governed continuity kernel
- an agent-agnostic execution governance layer
- a runtime plus governance corpus that turns project law into operational behavior
- a system for preserving project memory beyond chat memory
- a way to keep canon, provisional work, active execution, and proof distinct
- infrastructure for making handoff and resumption fast and truthful

### What Synapse is not

Synapse is **not**:
- a language model
- a chat client
- a replacement for testing or review
- a magic autonomous system that "just knows" the right thing
- a reason to skip architecture, proof, or explicit decisions
- a generic todo app with fantasy names slapped on top

It governs execution and continuity.
It does not replace engineering judgment.

## The model

### 1. Subject-centered work

Synapse organizes work around a **Subject**.
A subject has:
- a code/runtime side (`<Subject>_Engine`)
- a state/canon side (`<Subject>_Data`)

That separation matters.
It stops project memory, proof, canon, and continuity artifacts from being buried inside random chat history or mixed into code arbitrarily.

### 2. Repo-local sidecar truth

Each subject has a canonical sidecar under:
- `<Subject>_Data/.synapse/`

That sidecar holds fast-moving continuity state such as:
- `STATE.yaml`
- `MANIFOLD.yaml`
- `ACTIVE_RUN.yaml`
- `REHYDRATE.md`
- `VISION.md`
- daily ledgers for decisions, discoveries, and disclosures
- proposal/candidate state

This is where Synapse keeps the project's live memory.

### 3. Event spine + derived state

Phase 1 now includes a repo-local event spine under:
- `<Subject>_Data/.synapse/EVENTS/YYYY-MM-DD.jsonl`

This is append-only runtime truth for meaningful mutations.
It is not canon.
It is the raw spine that lets Synapse move toward reducer-owned continuity instead of a pile of unrelated direct writes.

Current architecture split:
- raw events: `.synapse/EVENTS/`
- derived working state: `STATE.yaml`, `MANIFOLD.yaml`, `REHYDRATE.md`
- executor-owned execution focus: `ACTIVE_RUN.yaml`
- canon: Quest Board, Audits, Codex, Build Manual, Guild Orders, Snapshots, Talent Tree

That split is the center of gravity.

### 4. Canon versus provisional truth

Synapse keeps these distinct on purpose:
- ambient/inferred work
- proposal/candidate state
- formalized canonical artifacts
- accepted governed execution

That matters because a system that collapses all of those together starts lying very fast.

### 5. Explicit gates where truth matters

Synapse is trying to automate continuity, not fake certainty.
So some things remain explicit:
- quest acceptance
- canon promotion
- disclosure blocks
- legality / freeze gates
- execution audits and proof

The goal is automatic continuity with explicit commitment boundaries.

## What Synapse does today

Today Synapse already provides a lot more than the README used to say.

### Ambient continuity capture

Synapse can capture and maintain live project continuity while work happens:
- active run state
- decisions
- discoveries
- disclosures
- verification receipts
- changed-file evidence
- proposal state
- rehydrate surfaces
- continuity pack refresh

The point is to make normal work feel more like normal coding and less like manually writing ritual artifacts all day.

### Ambient quest detection and promotion

Synapse can detect work from deterministic runtime signals and turn that into structured quest state:
- quest candidates
- side-quest candidates
- clustering and deduping of repeated related work
- promotion into BOARD quest artifacts when evidence justifies it

This means the system can see that meaningful work is happening and start structuring it without pretending that everything is already governed execution.

### Explicit governed execution path

Synapse keeps governed execution explicit.
A formalized BOARD quest can move into accepted governed work only through the acceptance gate.
That path validates things like:
- legality under current world state
- required quest fields
- verification plan presence
- audit bundle readiness
- governed execution truth

That explicit downstream gate is one of the most important things Synapse gets right.

### Continuity lifecycle and active rehydration pack

Synapse maintains an active continuity surface with:
- Bootstrap Prompt
- Continuity Lock
- Latest Rehydration Pack
- execution-pack pointer state when applicable
- archive/supersede behavior for stale active artifacts

Continuity refresh is transition-driven, not just a session-end ritual.

### Governance doctor and machine-readable governance inventory

Synapse can inspect governance and runtime state directly:
- `doctor`
- `governance-map`

That means the system is not just prose and vibes. It can reason about its own governance surfaces and validate important invariants.

## Why this matters

Synapse is valuable because it preserves the layer between "code exists" and "the project is understood."

That makes it useful for:
- agent-to-agent handoff
- human-to-agent handoff
- long-running project continuity
- architecture intent preservation
- proof-backed execution
- scope control
- drift reduction
- onboarding new collaborators faster
- reconstructing what actually happened during execution
- generating truthful summaries from repo-local state instead of memory alone

## Use cases

### 1. Agent handoff without story loss

A new agent can read the repo **plus** Synapse and get more than code shape.
It can see:
- current accepted work
- ambient work that is still provisional
- recent decisions
- current rehydrate state
- what is blocked
- what direction the project is moving

That reduces the constant "let me explain the whole project again" tax.

### 2. Long-running autonomous build continuity

For projects built over many sessions, Synapse helps preserve:
- current trajectory
- accumulated reasoning
- proof of execution
- next actions
- why previous work happened

That matters whether the same agent returns tomorrow or a different one takes over next month.

### 3. Auditability and proof

Synapse is built for environments where "it probably worked" is not good enough.
It supports:
- audit bundles
- verification receipts
- governed quest execution
- wrapper-proof validation
- explicit disclosure when truth is incomplete

This is useful for serious engineering work, not just toy task tracking.

### 4. Architecture and product memory

Synapse can preserve the difference between:
- what the system currently is
- what the team intends it to become
- what is canonical
- what is still exploratory

That stops future agents from mistaking a minimal first pass for the finished system.

### 5. Due diligence and narrative surfaces

Synapse does not currently ship a magic narrative generator.
But it is building the missing substrate that makes truthful downstream narrative generation possible.

Because Synapse stores repo-local story, direction, proof, and accepted scope, it can support future outputs like:
- architecture briefs
- execution summaries
- product direction memos
- diligence packets
- capability portfolios
- onboarding briefs

The key is that those outputs can come from durable repo truth instead of someone trying to remember the project from chat.

### 6. Operator confidence and interruption recovery

If a session gets interrupted, a human or agent should not need to reconstruct the world from scratch.
Synapse is explicitly aimed at reducing the cost of interruption and re-entry.

## How Synapse works in practice

### Common runtime surfaces

Useful commands in the current runtime include:
- `python3 runtime/synapse.py doctor`
- `python3 runtime/synapse.py governance-map`
- `python3 runtime/synapse.py engage`
- `python3 runtime/synapse.py attach-or-init`
- `python3 runtime/synapse.py session-start`
- `python3 runtime/synapse.py run-start`
- `python3 runtime/synapse.py run-update`
- `python3 runtime/synapse.py session-tick`
- `python3 runtime/synapse.py run-finalize`
- `python3 runtime/synapse.py log-decision`
- `python3 runtime/synapse.py log-disclosure`
- `python3 runtime/synapse.py render-rehydrate`
- `python3 runtime/synapse.py refresh-continuity`
- `python3 runtime/synapse.py formalize`
- `python3 runtime/synapse.py accept-quest`
- `python3 runtime/synapse.py watch`

### Normal work flow

At a high level, the intended shape is:

```text
Work happens
  -> runtime signals are captured
  -> sidecar current state stays updated
  -> quest/candidate structure emerges
  -> canon is formalized when justified
  -> governed execution remains explicit
  -> proof and continuity remain inspectable
```

Or more concretely:

```text
ambient work
  -> candidate / proposal state
  -> BOARD quest or other formalized artifact
  -> ACCEPTED governed quest
  -> audited execution
```

## Quickstart

Clone the repo and enter it:

```bash
git clone https://github.com/n0tsolikely/Synapse.git
cd Synapse
```

If you want the full CLI surface:

```bash
python3 runtime/synapse.py --help
```

If you are working on Synapse governance itself rather than a subject, start here:

```bash
python3 runtime/synapse.py doctor --governance-root governance --no-subject
```

If you are working on a subject and want normal session setup:

```bash
python3 runtime/synapse.py engage
```

For live execution memory on an attached subject:

```bash
python3 runtime/synapse.py session-start --title "Describe the session"
python3 runtime/synapse.py run-update --note "What changed"
python3 runtime/synapse.py render-rehydrate
```

For governed work:
- formalize the right artifact first
- accept quests explicitly through `accept-quest`
- execute through the governed wrappers and audit paths

## Repo shape

```text
Synapse/
├ governance/   # laws, schemas, processes, canonical definitions
├ runtime/      # CLI, reducer/event plumbing, governed tooling
├ docs/         # integration notes and optional persona overlays
├ integrations/ # runtime-specific examples
├ EXECUTOR.md   # canonical executor contract
└ README.md
```

And at the subject level, the important shape is:

```text
<Subject>_Engine/   # code / runtime surface
<Subject>_Data/     # canon, continuity, sidecar, audits, board state
```

## Where to look first

### For humans
- [`README.md`](README.md)
- [`EXECUTOR.md`](EXECUTOR.md)
- [`governance/The Guild/SYNAPSE_GUILD_CANONICAL_MANUAL.txt`](governance/The%20Guild/SYNAPSE_GUILD_CANONICAL_MANUAL.txt)
- [`governance/The Guild/SYNAPSE_GUILD__SUBJECT_MODEL.txt`](governance/The%20Guild/SYNAPSE_GUILD__SUBJECT_MODEL.txt)
- [`governance/README.txt`](governance/README.txt)

### For agents and operators
- [`AGENTS.md`](AGENTS.md)
- [`EXECUTOR.md`](EXECUTOR.md)
- [`governance/INDEX.txt`](governance/INDEX.txt)
- [`governance/SYNAPSE_STATE.yaml`](governance/SYNAPSE_STATE.yaml)
- [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md)

### Example subject skeleton
- `examples/example_subject/README.md`

## Where Synapse is going

The long-term direction is not "more ceremony."
The direction is:
- more automatic continuity
- less manual explanation overhead
- stronger repo-local story preservation
- clearer canon/provisional boundaries
- better reducer-owned derived state
- richer rehydrate and vision synthesis
- eventually making normal coding feel normal while Synapse quietly preserves the road behind the work

The desired end state is roughly this:
- you work normally
- the repo-local story keeps building itself
- accepted execution stays explicit
- proof stays attached to the work
- future agents do not have to start from scratch

That is the point.

## Important honesty note

Synapse is not done.
It is not finished polish.
It is not a complete end-state autonomy platform today.

It is live infrastructure being built toward a stronger autonomous continuity model.
The repo already does real work.
The vision is bigger than the current implementation.
Both of those things are true at the same time.

## Contributing

Contributions, ideas, and issues are welcome.
For project-specific guidance, see [`CONTRIBUTING.md`](CONTRIBUTING.md).
For responsible security reporting, see [`SECURITY.md`](SECURITY.md).

## License

Synapse includes the Apache License, Version 2.0. See [`LICENSE`](LICENSE).
