# Contributing to Synapse

Thanks for taking an interest in Synapse.

This project is open to builders, tinkerers, and people exploring AI-assisted engineering in public. Useful contributions are not limited to big code changes. Bug reports, docs improvements, tooling polish, runtime hardening, governance suggestions, and clarity fixes all count.

You do not need to already know the whole system to contribute. You do need to orient yourself before changing core behavior.

## Before you contribute

Start by reading the repo with intent:
- read [`README.md`](README.md)
- figure out whether you are touching `governance/`, `runtime/`, `docs/`, or integration examples
- open [`EXECUTOR.md`](EXECUTOR.md) if your change affects governed execution behavior
- do not guess your way through core runtime or governance behavior

Synapse is governance-first. That means changes should preserve continuity, traceability, and legibility instead of just adding more motion.

## Good first places to start

If you want a useful place to begin, these are good targets:
- documentation clarity
- README and docs improvements
- bug reports with clear reproduction steps
- runtime/tooling polish
- wrapper hardening
- verification and test coverage improvements
- integration notes and examples
- small quality-of-life fixes that improve readability or reduce ambiguity

## How to propose changes

For larger changes, start with the problem.

Good proposals explain:
- what is broken, rough, missing, or unclear
- why it matters
- what part of the system it touches
- how it affects governance, runtime behavior, or continuity expectations

Practical guidance:
- open an issue for significant changes before doing a large patch
- small fixes can be proposed directly, but clarity still matters
- if a change affects system behavior, explain how you verified it
- if a change affects governance or contracts, explain the downstream impact

## Contribution principles

These are the standards that matter here:
- preserve continuity
- prefer clear diffs over sprawling mystery edits
- keep architecture legible
- do not create god files or random dumping grounds
- do not casually weaken execution or governance guarantees
- respect existing project direction instead of bolting on disconnected features
- do not oversell unimplemented features in docs
- evidence beats vibes

Synapse is trying to preserve not just what exists, but why it exists and where it is headed. Contributions should strengthen that, not muddy it.

## Governance-aware changes

Not every part of the repo carries the same weight.

### Docs and content polish
These are usually the easiest changes to contribute. Clarity matters a lot here, especially in onboarding, routing, and public explanation.

### Runtime and tooling changes
Changes in `runtime/` and wrappers affect how governed work actually happens. Be explicit about behavior changes, failure modes, and verification.

### Governance, law, and contract changes
Changes in `governance/`, [`EXECUTOR.md`](EXECUTOR.md), or repo-wide execution expectations deserve extra care. These shape operator behavior, continuity rules, and what the system claims to guarantee. If you are changing those surfaces, explain the intent clearly and do not treat them like casual wording tweaks.

## Verification expectations

Keep this practical.

- if you change behavior, say how you verified it
- include commands and results where relevant
- do not claim something is fixed without receipts
- docs-only changes can stay lightweight, but they should still be accurate
- runtime and tooling changes should come with meaningful validation

If the change is small, the verification can be small. If the change affects behavior, the receipts should scale with the risk.

## Collaboration style

The project should stay direct, constructive, and technically serious.

That means:
- be clear
- be honest
- challenge ideas with reasons
- keep jargon under control
- do not turn disagreement into theater
- do not be hostile for sport
- clarity beats politeness theater

Strong technical pushback is welcome. Empty posture is not.

## Community and discussion

If you want to talk through ideas, report issues, or coordinate on larger changes:
- Discord community: Synapse Guild
- Discord username: notsolikely
- X handle: @_notsolikely
- X name: Peter J. Reynolds / notsolikely
- Email: notsolikelynotsolikely@gmail.com

You are welcome to:
- join the Discord
- open an issue
- discuss large changes before implementing them
- collaborate in the open

## License and attribution

By contributing to this repository, you are contributing under the repository's license terms.

Please preserve existing copyright, license, and notice text where required. If you add or move material that depends on those notices, keep them intact.
