---
name: qmg-memory
description: Persistent cross-session memory using quantum-memory-graph with pickle storage
tags:
  - memory
  - persistent
  - quantum-memory-graph
  - cross-session
  - long-term-memory
related_skills: []
---

# Quantum Memory Graph

Store and recall long-term agent memories using quantum-memory-graph with **persistent pickle storage**.

## When to use
- Remember decisions, preferences, architecture choices, debugging lessons, API quirks
- Cross-session memory that connects related facts (graph-based, not just key-value)
- Survives across `execute_code` calls, Hermes restarts, and profile switches
- Any context you want your agent to recall days or weeks later

## How
Run Python:
```python
from quantum_memory_graph import MemoryGraph, store, recall
from pathlib import Path
import os

# Cross-platform persistence path
PERSIST_PATH = Path(os.path.expanduser("~")) / "AppData" / "Local" / "hermes" / "qmg" / "memory_graph.pkl"
PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)

# Load or create graph
graph = MemoryGraph.load(str(PERSIST_PATH)) if PERSIST_PATH.exists() else MemoryGraph()

# Store a memory (auto-persists)
store("Decision: use Anchor 0.30 for all new Solana programs — avoids IDL drift", graph=graph)
graph.save(str(PERSIST_PATH))

# Recall related memories
results = recall("Anchor version decision", K=5, graph=graph)
for r in results:
    print(f"📌 {r.text} (score: {r.score:.2f})")
```

## Persistence details
- Storage: `~/AppData/Local/hermes/qmg/memory_graph.pkl` (Windows) or `~/.hermes/qmg/memory_graph.pkl` (Linux/macOS)
- Graph auto-saves after each `store()` call in the example above
- Load once per `execute_code` session; reuse the same `graph` instance for multiple operations
- The `graph` parameter is optional in `store()`/`recall()` — if omitted, uses an ephemeral in-memory graph (old behavior)