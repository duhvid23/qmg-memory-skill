# qmg-memory 🧠✨

> Persistent cross-session memory for Hermes Agent using **quantum-memory-graph** with pickle storage.
> Remember decisions, preferences, bugs, lessons — across restarts and sessions.

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
import os
from pathlib import Path
from quantum_memory_graph import MemoryGraph, store, recall

# Cross-platform persistence path 🎯 (override with QMG_PATH)
if os.environ.get("QMG_PATH"):
    PERSIST_PATH = Path(os.environ["QMG_PATH"]).expanduser()
elif os.name == "nt":
    PERSIST_PATH = Path.home() / "AppData" / "Local" / "hermes" / "qmg" / "memory_graph.pkl"
else:
    PERSIST_PATH = Path.home() / ".hermes" / "qmg" / "memory_graph.pkl"
PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)

# Load or create graph
graph = MemoryGraph.load(str(PERSIST_PATH)) if PERSIST_PATH.exists() else MemoryGraph()

# Store a memory, then save
store("Decision: use Anchor 0.30 for all new Solana programs — avoids IDL drift", graph=graph)
graph.save(str(PERSIST_PATH))

# Recall related memories (recall returns a dict)
result = recall("Anchor version decision", K=5, graph=graph)
for m in result["memories"]:
    print(f"📌 {m['text']} (score: {m['relevance']:.2f})")
```

---

## 🕸️ Codebase memory with graphify

[graphify](https://github.com/Graphify-Labs/graphify) maps a repo into a knowledge graph with tree-sitter (local, no LLM).
`scripts/graphify_to_qmg.py` turns that graph into memories your agent can recall: one per file, one per code cluster, the top hub functions, and a project overview.

```bash
uv tool install graphifyy                 # or: pipx install graphifyy
graphify install --platform hermes        # optional: the /graphify skill for Hermes

graphify update path/to/repo              # -> path/to/repo/graphify-out/graph.json
python scripts/graphify_to_qmg.py path/to/repo/graphify-out/graph.json --project myrepo \
    --test-query "where is authentication handled"
```

- Re-running replaces that project's previous import; your own memories are untouched
- `--dry-run` previews, `--remove` deletes the import, `--symbols` stores every function (large)
- The pickle is backed up to `memory_graph.pkl.bak` before each write

Example: graphify's own 55-file source became 204 memories in ~30s on CPU, and
`recall("how does community detection work")` returned `cluster.py` first.

---

## 💡 When to use

- ✅ Remember architecture decisions, debugging lessons, API quirks
- ✅ Store user preferences, environment specifics, team conventions
- ✅ Cross-reference related facts (graph magic ✨)
- ❌ Not for: ephemeral session data, large blobs, real-time sync

---

## 📁 Persistence

| Platform | Path |
|----------|------|
| Windows | `%USERPROFILE%\AppData\Local\hermes\qmg\memory_graph.pkl` |
| Linux/macOS | `~/.hermes/qmg/memory_graph.pkl` |

Call `graph.save(...)` after storing (`store()` does not write to disk). Override the path with `QMG_PATH`.  
Load once per `execute_code` session; reuse the same `graph` instance.

---

## 🔧 Requirements

- `quantum-memory-graph` Python package
- `graphifyy` (optional, for codebase memory)
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
- More importers like `graphify_to_qmg.py` (docs, tickets, chat logs)
- Web UI to browse the graph

---

## 📄 License

MIT — do whatever, just don't blame me if your agent develops feelings.

---

> Made with 💜 for the Hermes community by [@duhvid23](https://github.com/duhvid23)