# Synapse

*Agent-agnostic governance for AI-assisted engineering, execution, and continuity.*

Synapse is a public governance layer for projects that use AI to think, plan, and ship work.
It does not try to replace your agent, your runtime, or your persona. It governs how work is resumed, verified, recorded, and continued over time.

Bring your own agent.
Bring your own persona.
Synapse adds governance.

This Synapse is **not** Matrix Synapse, Azure Synapse, or another generic agent framework. This repo is specifically about governed execution, continuity artifacts, subject focus, receipts, audits, and drift handling for real project work.

## What Synapse does

Synapse exists to preserve more than files.
It tries to preserve intent.

A repo can usually tell you what exists. It usually cannot tell you:
- why it became that way
- what decisions shaped it
- what direction it was supposed to keep moving in
- which changes were verified and which were guessed

Synapse is built to help with that.

It gives humans and AI a governed trail of:
- subject focus
- decisions and snapshots
- execution receipts
- audit bundles
- drift warnings
- canonical routing for governed operations

The goal is not bureaucracy.
The goal is continuity without constant babysitting.

## Why it exists

AI can produce useful code and plans faster than many people can fully track.
That speed is useful, but it creates real failure modes:
- session memory disappears
- design decisions get forgotten
- capabilities get added and then lost from memory
- architecture drifts quietly
- repos fill up with disconnected work
- new sessions or new collaborators have to guess what matters

Synapse exists because project continuity is a real engineering problem.
It is trying to preserve project memory beyond chat memory: not just current state, but design continuity, decision continuity, execution history, and direction.

Long term, good governance should feel almost invisible.
It should sit in the background, preserve the road behind the project, and make it easier for the next session, next agent, or next collaborator to continue in the right direction without re-learning everything from scratch.

## What Synapse is

Synapse is:
- an agent-agnostic governance layer
- a continuity system for subject-based project work
- a runtime + governance repo that defines how governed operations happen
- a way to make project history more inspectable, resumable, and durable
- something meant to be explored, used, challenged, and improved in public

### What Synapse is not

Synapse is **not**:
- a language model
- a chat app
- a replacement for testing or review
- an autonomous framework that magically knows what to do
- a generic workflow buzzword wrapper
- a reason to skip architecture or design decisions

It governs execution and continuity.
It does not replace engineering judgment.

## Core ideas

### Subject focus
Synapse work happens around a **Subject**. The runtime resolves the active subject context before governed subject work begins, so engine/data roots and continuity artifacts are tied to the right project instead of guessed from vibes.

### Continuity artifacts
Synapse uses durable artifacts such as snapshots, audits, quest state, codex material, and subject data roots to preserve more than the latest chat. The aim is to keep not just the current location, but the trail of reasoning and execution that got there.

### Execution gates
Not every action should be treated the same. Synapse distinguishes between low-risk work, governed execution, and higher-risk operations that require stronger receipts or explicit consent.

### Governance drift handling
Governance changes over time too. Synapse tracks drift so an executor can see when the rules changed and acknowledge that state before claiming governed execution under stale assumptions.

### Canonical executor contract
Repo shims stay small. The canonical execution contract lives in [`EXECUTOR.md`](EXECUTOR.md), so different tools can point to one contract instead of maintaining separate competing instruction sets.

### Agent and persona compatibility
Synapse governs execution, not identity. If your runtime already has its own persona, identity, or tool model, keep it. Synapse can optionally layer governance-specific behavior and optional persona examples on top without trying to take over the entire runtime.

### Runtime tools and wrappers
When a governed operation has a canonical Synapse path, use the Synapse runtime tools and wrappers for that operation. That is how subject resolution, receipts, audits, consent, and other governed flows stay consistent.

## Quickstart

Clone the repo and enter it:

```bash
git clone https://github.com/n0tsolikely/Synapse.git
cd Synapse
```

Start session context with the real runtime entry point:

```bash
python3 runtime/synapse.py engage
```

Inspect the CLI surface if you want to see what the runtime supports:

```bash
python3 runtime/synapse.py --help
```

If you are working on Synapse governance itself rather than a subject, the governance-only doctor path is:

```bash
python3 runtime/synapse.py doctor --governance-root governance --no-subject
```

## How to think about it

```text
Human / Agent / Runtime
          |
          v
   Synapse Governance
          |
          v
 Subject_Engine + Subject_Data
```

Synapse sits between the operator/runtime and the project state.
It helps preserve continuity, constrain governed operations, and leave behind receipts that a future session can actually inspect.

## Where to look first

If you want the shortest useful orientation path, start here:

### For humans
- [`README.md`](README.md)
- [`governance/The Guild/SYNAPSE_GUILD__THE_GUILD_ITSELF.txt`](governance/The%20Guild/SYNAPSE_GUILD__THE_GUILD_ITSELF.txt)
- [`governance/The Guild/SYNAPSE_GUILD_CANONICAL_MANUAL.txt`](governance/The%20Guild/SYNAPSE_GUILD_CANONICAL_MANUAL.txt)
- [`governance/The Guild/SYNAPSE_GUILD__QUICK_START.txt`](governance/The%20Guild/SYNAPSE_GUILD__QUICK_START.txt)
- [`governance/The Guild/SYNAPSE_GUILD__SUBJECT_MODEL.txt`](governance/The%20Guild/SYNAPSE_GUILD__SUBJECT_MODEL.txt)

### For agents / operators
- [`AGENTS.md`](AGENTS.md)
- [`EXECUTOR.md`](EXECUTOR.md)
- [`governance/README.txt`](governance/README.txt)
- [`governance/INDEX.txt`](governance/INDEX.txt)
- [`governance/SYNAPSE_STATE.yaml`](governance/SYNAPSE_STATE.yaml)

### For integrations and optional persona overlays
- [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md)
- [`docs/PERSONAS.md`](docs/PERSONAS.md)

## Example subject (minimal teaching skeleton)

Want a concrete example of what a governed project looks like? Start here:
- `examples/example_subject/README.md`

This is a tiny, intentionally minimal subject that shows the Subject_Data / Subject_Engine split and a few representative continuity artifacts.

## Fast plan to SIDE-QUESTs (draft only)

If you have a short checklist, you can draft tracked SIDE-QUESTs in BOARD state:

```bash
python3 runtime/synapse.py plan-sidequests --item "Do X" --item "Do Y"
```

This creates Quest files on the Quest Board. Acceptance and execution are still governed.

## Repo map

```text
Synapse/
├ governance/   # laws, schemas, processes, canonical definitions
├ runtime/      # CLI and governed tooling
├ docs/         # integration notes and optional persona overlays
├ integrations/ # runtime-specific examples
├ EXECUTOR.md   # canonical executor contract
└ README.md
```

`governance/` defines the rules.
`runtime/` executes the governed paths.
The project is intentionally split so continuity and execution discipline are explicit instead of buried in chat history.

## Active example: building Ashby with Synapse

Synapse is currently being used as the governance layer for an active system build:
- **Ashby_Engine** (runtime): https://github.com/n0tsolikely/Ashby_Engine
- **Ashby_Data** (canonical state/docs): https://github.com/n0tsolikely/Ashby_Data

That pairing is a practical example of the model:
- engine code lives in the engine repo
- canonical state, codex material, snapshots, orders, and audits live in the data repo
- Synapse governs how continuity and execution are handled across the work

## Status

Synapse is in active development.
The governance core is real, the runtime layer is usable, and the project is still being sharpened in public.

This repo is not finished polish. It is live infrastructure being improved while it is used.

## Get involved

If this is interesting to you:
- try it on a real project
- open an issue when something is unclear, rough, or missing
- suggest changes to the governance model
- contribute fixes and improvements
- join the community and compare notes with other builders

Community / contact:
- Discord community: Synapse Guild
- Discord username: notsolikely
- X handle: @_notsolikely
- X name: Peter J. Reynolds / notsolikely
- Email: [notsolikelynotsolikely@gmail.com](mailto:notsolikelynotsolikely@gmail.com)

## Contributing

Contributions, ideas, and issues are welcome.
For project-specific guidance, see [`CONTRIBUTING.md`](CONTRIBUTING.md).
For responsible security reporting, see [`SECURITY.md`](SECURITY.md).
The repo is public on purpose: it is meant to be tested, questioned, and improved.

## License

Synapse includes the Apache License, Version 2.0. See [`LICENSE`](LICENSE).
