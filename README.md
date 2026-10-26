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

# Persistence path 🎯 — same rule as the graphify bridge: env var, then the hermes-qmg
# plugin's shared qmg_graph.pkl if it exists, else this skill's memory_graph.pkl
def qmg_path() -> Path:
    for var in ("QMG_GRAPH_PATH", "QMG_PATH"):
        if os.environ.get(var):
            return Path(os.environ[var]).expanduser()
    base = Path.home() / ("AppData/Local/hermes" if os.name == "nt" else ".hermes") / "qmg"
    shared = base / "qmg_graph.pkl"
    return shared if shared.exists() else base / "memory_graph.pkl"

PERSIST_PATH = qmg_path()
PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)

# Load or create graph
graph = MemoryGraph.load(str(PERSIST_PATH)) if PERSIST_PATH.exists() else MemoryGraph()

# Store a memory, then save. Not on the shared qmg_graph.pkl: other agents write it under a
# lock; store through Hermes' memory tool or the qmg MCP `qmg_store` there instead.
if PERSIST_PATH.name != "qmg_graph.pkl":
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

- Re-running replaces that project's previous import; your own memories are untouched, and an unchanged graph writes nothing
- Writes into the shared `qmg_graph.pkl` when the hermes-qmg plugin is installed, under the same lock the plugin and qmg-mcp use (`<pickle>.bak` kept)
- `--dry-run` previews, `--remove` deletes the import, `--symbols` stores every function (large)
- Self-check: `python tests/test_graphify_to_qmg.py` (uses a throwaway pickle)

Example: the hermes-qmg plugin source (15 files) became 55 memories; the write held the shared lock
for 0.2s on a 1,100-memory graph, `recall("which function backs up the plugin before install")` returned
`restore_backup()` first, and fact queries still returned the facts first.

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

With the hermes-qmg plugin installed, its shared `qmg_graph.pkl` in the same folder is used instead (read it, store through Hermes or `qmg_store`).
Call `graph.save(...)` after storing (`store()` does not write to disk). Override the path with `QMG_GRAPH_PATH` or `QMG_PATH`.  
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