# Synapse Personas

Synapse governs execution, not identity.

If your runtime already has persona or identity files, keep them.
Synapse-managed persona overlays are optional and style-only.
If a persona conflicts with governance, governance wins.

## Selection Order

Synapse resolves an optional persona overlay in this order:

1. `SYNAPSE_PERSONA`
2. `$HOME/.synapse/PERSONA_ACTIVE.txt`
3. `<repo>/.synapse/PERSONA_ACTIVE.txt`
4. `NONE`

Supported values:

- `NONE`
- `DEFAULT`
- `ASH`
- `PATH:<path>`

## What This Changes

Persona changes:

- tone
- style
- pushback flavor
- voice

Persona does not change:

- truth gate
- subject focus
- receipts
- audits
- wrappers
- consent
- drift

## Runtime Compatibility

For OpenClaw-like systems with `SOUL.md`, `USER.md`, `IDENTITY.md`, or similar:

- keep those files
- use Synapse as a governance overlay
- use a Synapse persona only if you want one

For Codex / Claude Code style runtimes:

- keep global or local persona files if desired
- keep repo shims thin
- point governed work to `EXECUTOR.md`

## Examples

- `SYNAPSE_PERSONA=NONE`
- `SYNAPSE_PERSONA=DEFAULT`
- `SYNAPSE_PERSONA=ASH`
- `SYNAPSE_PERSONA=PATH:docs/personas/PERSONA__ASH.md`

Use `python3 runtime/synapse.py persona --shell` to see the resolved overlay.
