# Example Subject (Minimal Teaching Skeleton)

This is an intentionally small example to show what a **Subject** looks like when using Synapse.
It is not a real project. It is not full governance. It is just a minimal teaching artifact.

The point is to make the split and the flow visible:

```
Subject_Data  -> continuity, decisions, snapshots, governed artifacts
Subject_Engine -> implementation code and runtime assets
```

## What to look at first

- `ExampleSubject_Data/README.md` — what belongs in Subject_Data
- `ExampleSubject_Engine/README.md` — what belongs in Subject_Engine
- `ExampleSubject_Engine/src/main.py` — a tiny example engine artifact
- `ExampleSubject_Data/Snapshots/EXAMPLE_SNAPSHOT.md` — a tiny snapshot example
- `ExampleSubject_Data/Quest Board/EXAMPLE_QUEST.md` — a tiny quest example
- `ExampleSubject_Data/Guild Orders/EXAMPLE_GUILD_ORDER.md` — a tiny order example
- `ExampleSubject_Data/Codex/README.md` — a tiny codex placeholder

## Diagram

```
Human / Agent / Runtime
          |
          v
   Synapse Governance
          |
          v
 ExampleSubject_Data + ExampleSubject_Engine
```

If this example feels too minimal, that is by design. It is only meant to make the structure tangible.
