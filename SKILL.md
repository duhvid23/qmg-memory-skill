---
name: qmg-memory
description: Persistent cross-session memory using quantum-memory-graph with pickle storage. Also loads graphify codebase knowledge graphs into memory so the agent can recall code structure (files, clusters, hub functions, dependencies) across sessions.
tags:
  - memory
  - persistent
  - quantum-memory-graph
  - cross-session
  - long-term-memory
  - graphify
  - codebase-map
related_skills:
  - graphify
---

# Quantum Memory Graph

Store and recall long-term agent memories using quantum-memory-graph with **persistent pickle storage**.

## When to use
- Remember decisions, preferences, architecture choices, debugging lessons, API quirks
- Cross-session memory that connects related facts (graph-based, not just key-value)
- Survives across `execute_code` calls, Hermes restarts, and profile switches
- Recall the structure of a codebase mapped by graphify ("which file handles X?", "what calls Y?")

## Store and recall
Run Python:
```python
import os
from pathlib import Path
from quantum_memory_graph import MemoryGraph, store, recall

def qmg_path() -> Path:
    if os.environ.get("QMG_PATH"):
        return Path(os.environ["QMG_PATH"]).expanduser()
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / "hermes" / "qmg" / "memory_graph.pkl"
    return Path.home() / ".hermes" / "qmg" / "memory_graph.pkl"

PERSIST_PATH = qmg_path()
PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)

# Load once per execute_code session
graph = MemoryGraph.load(str(PERSIST_PATH)) if PERSIST_PATH.exists() else MemoryGraph()

# Store, then save
store("Decision: use Anchor 0.30 for all new Solana programs — avoids IDL drift", graph=graph)
graph.save(str(PERSIST_PATH))

# recall() returns a dict; the hits are in result["memories"]
result = recall("Anchor version decision", K=5, graph=graph)
for m in result["memories"]:
    print(f"{m['relevance']:.2f}  {m['text']}")
```

## Codebase memory with graphify
[graphify](https://github.com/Graphify-Labs/graphify) parses a repo into a knowledge graph (`graphify-out/graph.json`).
`scripts/graphify_to_qmg.py` condenses that graph into recallable memories:

| Kind | One per | Contains |
|------|---------|----------|
| overview | project | size, most depended-on files, largest clusters, top hubs |
| file | source file | module docstring, symbols defined, files it depends on / is used by, external imports |
| cluster | graphify community | files spanned, key symbols |
| hub | top-N most connected symbol | location, docstring, callers, callees |
| symbol | every callable (only with `--symbols`) | same as hub |

Steps (code mapping is local tree-sitter, no LLM, no API cost):
```bash
graphify update path/to/repo          # writes path/to/repo/graphify-out/graph.json
python scripts/graphify_to_qmg.py path/to/repo/graphify-out/graph.json --project myrepo
```

Then recall code structure like any other memory:
```python
result = recall("where is escrow release handled", K=5, graph=graph)
```

Every imported memory starts with `[graphify:<project>]` and has `source="graphify:<project>"`.
- Re-running the import **replaces** that project's previous memories (no stale structure). Your own memories are never touched.
- `--dry-run` prints what would be stored without loading the model or touching the pickle.
- `--remove` deletes only that project's imported memories.
- `--hubs N` (default 25), `--symbols` (all callables, large), `--max-memories` (default 3000 safety cap).
- `--test-query "..."` runs a recall right after import to check quality.
- The pickle is backed up to `memory_graph.pkl.bak` and written atomically on every import.

Re-sync after significant code changes (or wire `graphify update` + the import into a git hook).

## Persistence details
- Storage: `%USERPROFILE%\AppData\Local\hermes\qmg\memory_graph.pkl` (Windows) or `~/.hermes/qmg/memory_graph.pkl` (Linux/macOS); override with `QMG_PATH`
- Load once per `execute_code` session; reuse the same `graph` instance for multiple operations
- Call `graph.save(...)` after storing; `store()` itself does not write to disk
- The `graph` parameter is optional in `store()`/`recall()`; if omitted, an ephemeral in-memory graph is used
- Pickle files execute code when loaded: only load memory files you created
