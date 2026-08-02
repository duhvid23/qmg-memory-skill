# qmg-memory 🧠✨

> Persistent cross-session memory for Hermes Agent using **quantum-memory-graph** with pickle storage.
> Remember decisions, preferences, bugs, deploy lessons — across restarts and sessions.

---

## 🎯 What it does

| Feature | Details |
|---------|---------|
| **Long-term memory** | Survives Hermes restarts, `execute_code` calls, profile switches |
| **Graph-based** | Connects related facts — not just a flat key-value store |
| **Cross-session** | Recall context from days/weeks ago |
| **Zero config** | Drop in skills folder, works immediately |

---

## 📦 Install

```bash
# Clone into your Hermes skills directory
git clone https://github.com/duhvid23/qmg-memory-skill.git \
  ~/AppData/Local/hermes/skills/qmg-memory
```

> **Windows:** `~/AppData/Local/hermes/skills/qmg-memory`  
> **Linux/macOS:** `~/.hermes/skills/qmg-memory`

Restart Hermes or run `hermes skills reload` (if available).

---

## 🚀 Quick Start

```python
from quantum_memory_graph import MemoryGraph, store, recall
from pathlib import Path
import os

# Cross-platform persistence path 🎯
PERSIST_PATH = Path(os.path.expanduser("~")) / "AppData" / "Local" / "hermes" / "qmg" / "memory_graph.pkl"
PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)

# Load or create graph
graph = MemoryGraph.load(str(PERSIST_PATH)) if PERSIST_PATH.exists() else MemoryGraph()

# Store a memory (auto-persists)
store("Escrova: mainnet deploy uses Squads multisig 2/3 for program upgrades", graph=graph)
graph.save(str(PERSIST_PATH))

# Recall related memories
results = recall("Escrova deploy multisig", K=5, graph=graph)
for r in results:
    print(f"📌 {r.text} (score: {r.score:.2f})")
```

---

## 💡 When to use

- ✅ Remember architecture decisions, Zinc bugs, deploy lessons
- ✅ Store user preferences, API quirks, environment specifics
- ✅ Cross-reference related facts (graph magic ✨)
- ❌ Not for: ephemeral session data, large blobs, real-time sync

---

## 📁 Persistence

| Platform | Path |
|----------|------|
| Windows | `%USERPROFILE%\AppData\Local\hermes\qmg\memory_graph.pkl` |
| Linux/macOS | `~/.hermes/qmg/memory_graph.pkl` |

The graph auto-saves after each `store()` call in the example above.  
Load once per `execute_code` session; reuse the same `graph` instance.

---

## 🔧 Requirements

- `quantum-memory-graph` Python package
- Hermes Agent (any recent version)

```bash
pip install quantum-memory-graph
```

---

## 🤝 Contributing

PRs welcome! Ideas:
- Add TTL/expiry for memories
- Add tagging/categories
- Export/import JSON for backup
- Web UI to browse the graph

---

## 📄 License

MIT — do whatever, just don't blame me if your agent develops feelings.

---

> Made with 💜 for the Hermes community by [@duhvid23](https://github.com/duhvid23)