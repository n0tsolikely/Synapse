# Synapse

Synapse is a governance-first execution system for maintaining **deterministic continuity across AI sessions and projects**.

## Example system using Synapse (active build)
Synapse is currently being used as the governance layer to build:
- **Ashby_Engine** (runtime): https://github.com/n0tsolikely/Ashby_Engine
- **Ashby_Data** (canonical state/docs): https://github.com/n0tsolikely/Ashby_Data

It provides a structured framework for turning ideas into governed execution using artifacts such as:

- Codex documentation
- Guild Orders
- Quests
- Snapshots
- Execution audits

These artifacts ensure any AI or human can **resume a project without losing context or introducing drift**.

---

# Purpose

Synapse exists to solve one problem:

**AI sessions forget. Projects rot. Context disappears.**

Synapse prevents that by enforcing:

- Deterministic artifacts instead of chat memory
- Proof-backed execution
- Clear decision records
- Cross-session continuity

---

# 60-Second Quickstart

Clone the repository:

```bash
git clone https://github.com/n0tsolikely/Synapse.git
cd Synapse
````

Inspect the runtime CLI:

```bash
python3 runtime/synapse.py --help
```

Synapse projects operate around a **Subject**, which defines the project workspace and continuity artifacts.

The runtime CLI manages execution, while governance defines the rules.

---

# Start Here (Human Overview)

If you're exploring Synapse as a human, start with the **Guild documentation**.

These explain the philosophy and operating model.

Read these first:

* `governance/The Guild/SYNAPSE_GUILD__THE_GUILD_ITSELF.txt`
* `governance/The Guild/SYNAPSE_GUILD_CANONICAL_MANUAL.txt`
* `governance/The Guild/SYNAPSE_GUILD__QUICK_START.txt`
* `governance/The Guild/SYNAPSE_GUILD__SUBJECT_MODEL.txt`

These documents explain:

* Why Synapse exists
* How the Guild model works
* How projects evolve under governance
* How humans and AI collaborate under the system

---

# Canonical Routing (AI / Operators)

If you are an **AI operator or automated system**, start here instead.

Follow this order:

1. `governance/README.txt`
2. `governance/INDEX.txt`
3. `governance/SYNAPSE_STATE.yaml`

Then follow the `required_read_order` defined inside `SYNAPSE_STATE.yaml`.

These files define:

* governance laws
* system structure
* execution rules
* required artifact flows

---

# What Synapse Is NOT

To avoid confusion:

Synapse is **not**:

* a language model
* a chat interface
* an autonomous agent framework
* a system that magically writes production software
* a replacement for testing or review
* a way to skip design decisions

Synapse is **governance + continuity + execution discipline**.

It is the **spine that keeps humans and AI aligned across sessions**.

---

# Repository Layout

```
Synapse/
├ governance/   → laws, schemas, processes, canonical definitions (inert)
├ runtime/      → runtime CLI and executable tools
└ README.md
```

Key principle:

Governance defines the rules.

Runtime executes them.

Governance itself **does not execute code**.

---

# Roadmap (Near Term)

Planned improvements:

* [ ] Incubation pipeline for discovery and brainstorming artifacts
* [ ] Codex generation scaffolding
* [ ] Drift detection based on git commits
* [ ] Quest execution hardening
* [ ] Improved AI routing through AGENTS.md

If this project is useful to you:

⭐ Star the repository
🧠 Open an issue describing your use case
⚒ Contribute improvements

---

# Status

Synapse is currently in **active early development**.

The governance core is implemented and the runtime layer is evolving.

Expect rapid iteration.

---

# About

Synapse is a governance architecture for AI-driven development.

Instead of relying on session memory or loose documentation, Synapse structures projects using deterministic artifacts that record:

* decisions
* execution
* system state

This makes projects portable across:

* AI models
* sessions
* collaborators
* machines

---

# License

MIT
