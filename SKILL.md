---
name: qmg-memory
description: Persistent cross-session memory using quantum-memory-graph with pickle storage
tags:
  - memory
  - persistent
  - quantum-memory-graph
  - escrova
related_skills: []
---

# Quantum Memory Graph

Store and recall long-term agent memories using quantum-memory-graph with **persistent pickle storage**.

## When to use
- Remember or recall decisions, preferences, incidents, Zinc bugs, deploy lessons, Escrova notes
- Cross-session memory that connects related facts
- Survives across `execute_code` calls and Hermes restarts

## How
Run Python:
```python
from quantum_memory_graph import MemoryGraph, store, recall
from pathlib import Path

# Cross-platform persistence path
import os
PERSIST_PATH = Path(os.path.expanduser("~")) / "AppData" / "Local" / "hermes" / "qmg" / "memory_graph.pkl"
PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)

# Load or create graph
if PERSIST_PATH.exists():
    graph = MemoryGraph.load(str(PERSIST_PATH))
else:
    graph = MemoryGraph()

# Store (auto-persists)
store("Escrova: mainnet deploy uses Squads multisig 2/3 for program upgrades", graph=graph)
graph.save(str(PERSIST_PATH))

# Recall
results = recall("Escrova deploy multisig", K=5, graph=graph)
```

## Persistence details
- Storage: `C:\Users\dj_19.HERMES\AppData\Local\hermes\qmg\memory_graph.pkl` (pickle)
- Graph auto-saves after each `store()` call in the example above
- Load once per `execute_code` session; reuse the same `graph` instance for multiple operations
- The `graph` parameter is optional in `store()`/`recall()` — if omitted, uses an ephemeral in-memory graph (old behavior)