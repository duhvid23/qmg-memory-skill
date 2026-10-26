#!/usr/bin/env python3
"""Load a graphify knowledge graph (graphify-out/graph.json) into qmg-memory.

graphify maps a codebase into nodes (files, classes, functions, docstrings)
and edges (calls, imports, references, ...). This script condenses that graph
into a few hundred recallable memories instead of one per symbol:

  overview   one memory describing the whole project
  file       one per source file: purpose, symbols, file-level dependencies
  cluster    one per graphify community (a group of tightly linked code)
  hub        the most connected symbols, with callers and callees
  symbol     every callable symbol (only with --symbols)

Every memory is tagged with source "graphify:<project>". Re-running replaces
the previous import for that project, so recall never returns stale structure.
A re-run on an unchanged graph.json writes nothing.

Writes are safe next to other writers (Hermes qmg plugin, qmg-mcp server):
embeddings are computed first, then the script takes <pickle>.lock, reloads
the pickle from disk, applies its changes and saves atomically (.bak kept).

Usage:
  python graphify_to_qmg.py path/to/graphify-out/graph.json --project escrova
  python graphify_to_qmg.py graph.json --project escrova --dry-run
  python graphify_to_qmg.py graph.json --project escrova --remove
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

SOURCE_PREFIX = "graphify:"
LOCK_WAIT_S = 120   # give up if another writer holds the lock this long
STALE_LOCK_S = 60   # a lock this old was left by a crashed writer (same rule as qmg-mcp and the plugin)
LOCK_BUDGET_S = 50  # others take over a lock older than STALE_LOCK_S; never save after this

# Common credential shapes; code comments and docstrings occasionally carry them.
SECRET_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----"
    r"|\b(?:sk|rk|pk)[-_](?:live|test|proj)[-_]?[A-Za-z0-9_\-]{16,}"
    r"|\b(?:ghp|gho|ghs)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"
    r"|\bxox[bap]-[A-Za-z0-9-]{10,}|\bAKIA[0-9A-Z]{16}\b|\bAIza[0-9A-Za-z_\-]{30,}"
    r"|\bwhsec_[A-Za-z0-9]{8,}"
    r"|\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r"|\b[1-9A-HJ-NP-Za-km-z]{86,90}\b"
    r"|(?i:\b(?:api[_-]?key|secret|token|password|passwd)\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+=]{12,})",
    re.S,
)

# Edges that mean "A depends on B" when A and B live in different files.
DEPENDENCY_RELATIONS = {
    "calls", "indirect_call", "imports", "imports_from",
    "references", "inherits", "uses", "implements",
}
CALL_RELATIONS = {"calls", "indirect_call"}

MAX_TEXT = 670  # Hermes prefetch shows at most ~700 chars of a hit
MAX_LIST = 12
MAX_ENTITIES = 16


def default_persist_path() -> Path:
    """$QMG_GRAPH_PATH or $QMG_PATH; else the hermes-qmg plugin's shared graph if
    installed (qmg_graph.pkl), else this skill's own memory_graph.pkl."""
    for var in ("QMG_GRAPH_PATH", "QMG_PATH"):
        if os.environ.get(var):
            return Path(os.environ[var]).expanduser()
    base = Path.home() / ("AppData/Local/hermes" if os.name == "nt" else ".hermes") / "qmg"
    shared = base / "qmg_graph.pkl"
    return shared if shared.exists() else base / "memory_graph.pkl"


@dataclass
class MemorySpec:
    kind: str
    text: str
    entities: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    files: list[str] = field(default_factory=list)  # source files it describes; sets its timestamp


class GraphifyGraph:
    """Read-only view over graph.json with the indexes the summaries need."""

    def __init__(self, data: dict):
        if not isinstance(data, dict) or "nodes" not in data:
            raise ValueError("not a graphify graph.json: missing 'nodes'")
        links = data.get("links", data.get("edges"))
        if links is None:
            raise ValueError("not a graphify graph.json: missing 'links'/'edges'")

        self.meta = data.get("graph", {}) or {}
        self.nodes: dict[str, dict] = {}
        for n in data["nodes"]:
            if "id" not in n:
                raise ValueError(f"node without id: {n!r}")
            self.nodes[n["id"]] = n
        self.links = [l for l in links if l.get("source") in self.nodes and l.get("target") in self.nodes]
        dropped = len(links) - len(self.links)
        if dropped:
            print(f"warning: skipped {dropped} edge(s) pointing at unknown nodes", file=sys.stderr)

        self.degree: Counter = Counter()
        self.out_edges: dict[str, list[dict]] = defaultdict(list)
        self.in_edges: dict[str, list[dict]] = defaultdict(list)
        self.rationale: dict[str, str] = {}
        for l in self.links:
            s, t = l["source"], l["target"]
            if l.get("relation") == "rationale_for":
                self.rationale.setdefault(t, self.label(s))
                continue
            self.degree[s] += 1
            self.degree[t] += 1
            self.out_edges[s].append(l)
            self.in_edges[t].append(l)

    def label(self, nid: str) -> str:
        n = self.nodes[nid]
        return str(n.get("label") or nid)

    def file_of(self, nid: str) -> str:
        return self.nodes[nid].get("source_file") or ""

    def is_symbol(self, nid: str) -> bool:
        n = self.nodes[nid]
        return (
            n.get("file_type") == "code"
            and not n.get("external")
            and bool(n.get("source_file"))
            and not self.is_file_node(nid)
        )

    def is_file_node(self, nid: str) -> bool:
        n = self.nodes[nid]
        src = n.get("source_file") or ""
        return bool(src) and n.get("source_location") in ("L1", None) and n.get("label") == Path(src).name

    def is_external(self, nid: str) -> bool:
        n = self.nodes[nid]
        return bool(n.get("external")) or not n.get("source_file")

    def location(self, nid: str) -> str:
        n = self.nodes[nid]
        loc = n.get("source_location") or ""
        return f"{self.file_of(nid)}:{loc.lstrip('L')}" if loc else self.file_of(nid)


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    text = SECRET_RE.sub("[REDACTED]", " ".join(text.split()))
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _sentence(text: str) -> str:
    """Docstring fragment without a trailing period, so templates add exactly one."""
    return text.strip().rstrip(".").rstrip()


def _join(items, limit: int = MAX_LIST) -> str:
    items = list(dict.fromkeys(i for i in items if i))
    if not items:
        return "none"
    head = ", ".join(items[:limit])
    return f"{head} (+{len(items) - limit} more)" if len(items) > limit else head


def _entities(project: str, *groups) -> list[str]:
    out = [project]
    for g in groups:
        out.extend(g)
    return list(dict.fromkeys(e for e in out if e))[:MAX_ENTITIES]


def build_memories(g: GraphifyGraph, project: str, hubs: int, symbols: bool, min_cluster: int,
                   graph_path: Path, built: datetime) -> list[MemorySpec]:
    tag = f"[graphify:{project}]"
    specs: list[MemorySpec] = []

    # ---- per-file -------------------------------------------------------
    file_symbols: dict[str, list[str]] = defaultdict(list)
    file_node: dict[str, str] = {}
    for nid, n in g.nodes.items():
        src = n.get("source_file")
        if not src:
            continue
        if g.is_file_node(nid):
            file_node[src] = nid
        elif g.is_symbol(nid):
            file_symbols[src].append(nid)

    depends_on: dict[str, Counter] = defaultdict(Counter)
    used_by: dict[str, Counter] = defaultdict(Counter)
    external_libs: dict[str, Counter] = defaultdict(Counter)
    for l in g.links:
        if l.get("relation") not in DEPENDENCY_RELATIONS:
            continue
        s, t = l["source"], l["target"]
        sf, tf = g.file_of(s), g.file_of(t)
        if not sf:
            continue
        if g.is_external(t):
            external_libs[sf][g.label(t)] += 1
        elif tf and tf != sf:
            depends_on[sf][tf] += 1
            used_by[tf][sf] += 1

    all_files = sorted(set(file_symbols) | set(file_node))
    for src in all_files:
        syms = sorted(file_symbols.get(src, []), key=lambda x: -g.degree[x])
        purpose = g.rationale.get(file_node.get(src, ""), "")
        sym_labels = [g.label(s) for s in syms]
        deps = [f for f, _ in depends_on[src].most_common()]
        users = [f for f, _ in used_by[src].most_common()]
        libs = [x for x, _ in external_libs[src].most_common()]
        text = (
            f"{tag} File {src}"
            + (f" — {_sentence(purpose)}" if purpose else "")
            + f". Defines {len(syms)} symbols: {_join(sym_labels)}."
            + f" Depends on files: {_join(deps, 8)}."
            + f" Used by files: {_join(users, 8)}."
            + f" External imports: {_join(libs, 8)}."
        )
        specs.append(MemorySpec(
            kind="file",
            text=_clip(text),
            entities=_entities(project, [src], sym_labels[:8], deps[:3]),
            metadata={"file": src, "symbols": len(syms)},
            files=[src],
        ))

    # ---- clusters -------------------------------------------------------
    members: dict[object, list[str]] = defaultdict(list)
    names: dict[object, str] = {}
    for nid, n in g.nodes.items():
        if "community" in n and g.is_symbol(nid):
            members[n["community"]].append(nid)
            names.setdefault(n["community"], str(n.get("community_name") or n["community"]))
    for cid, nids in sorted(members.items(), key=lambda kv: -len(kv[1])):
        if len(nids) < min_cluster:
            continue
        ranked = sorted(nids, key=lambda x: -g.degree[x])
        files = [f for f, _ in Counter(g.file_of(x) for x in nids).most_common()]
        key_syms = [g.label(x) for x in ranked]
        text = (
            f"{tag} Code cluster '{names[cid]}' ({len(nids)} symbols)."
            f" Spans files: {_join(files, 8)}."
            f" Key symbols: {_join(key_syms)}."
        )
        specs.append(MemorySpec(
            kind="cluster",
            text=_clip(text),
            entities=_entities(project, files[:4], key_syms[:8]),
            metadata={"community": cid, "size": len(nids)},
            files=files,
        ))

    # ---- hubs / symbols -------------------------------------------------
    ranked_syms = sorted((n for n in g.nodes if g.is_symbol(n)), key=lambda x: -g.degree[x])
    chosen = ranked_syms if symbols else ranked_syms[:hubs]
    hub_set = set(ranked_syms[:hubs])
    for nid in chosen:
        callers = [g.label(l["source"]) for l in g.in_edges[nid] if l.get("relation") in CALL_RELATIONS]
        callees = [g.label(l["target"]) for l in g.out_edges[nid] if l.get("relation") in CALL_RELATIONS]
        refs = [g.label(l["source"]) for l in g.in_edges[nid] if l.get("relation") not in CALL_RELATIONS | {"contains", "method"}]
        doc = g.rationale.get(nid, "")
        kind = "hub" if nid in hub_set else "symbol"
        text = (
            f"{tag} {'Hub symbol' if kind == 'hub' else 'Symbol'} {g.label(nid)} at {g.location(nid)}"
            + (f" — {_sentence(doc)}" if doc else "")
            + f". Called by: {_join(callers, 10)}."
            + f" Calls: {_join(callees, 10)}."
            + (f" Referenced by: {_join(refs, 6)}." if refs else "")
            + f" Connections: {g.degree[nid]}."
        )
        specs.append(MemorySpec(
            kind=kind,
            text=_clip(text),
            entities=_entities(project, [g.label(nid), g.file_of(nid)], callers[:4], callees[:4]),
            metadata={"node_id": nid, "file": g.file_of(nid), "degree": g.degree[nid]},
            files=[g.file_of(nid)],
        ))

    # ---- overview (first, so it is easy to spot) ----------------------
    biggest = sorted(members.items(), key=lambda kv: -len(kv[1]))[:8]
    top_files = sorted(all_files, key=lambda f: -sum(used_by[f].values()))[:8]
    overview = (
        f"{tag} Codebase overview for {project}: {len(all_files)} files,"
        f" {len(ranked_syms)} symbols, {len(g.links)} relationships"
        f" (graphify {g.meta.get('graphify_version', '?')}, graph built {built:%Y-%m-%d})."
        f" Query it: graphify query \"<question>\" --graph {graph_path.as_posix()}."
        f" Most depended-on files: {_join(top_files, 8)}."
        f" Largest clusters: {_join([names[c] for c, _ in biggest], 8)}."
        f" Top hubs: {_join([g.label(x) for x in ranked_syms[:8]], 8)}."
    )
    specs.insert(0, MemorySpec(
        kind="overview",
        text=_clip(overview),
        entities=_entities(project, top_files[:6]),
        metadata={"files": len(all_files), "symbols": len(ranked_syms)},
        files=all_files,
    ))
    return specs


def file_mtimes(graph_path: Path) -> dict[str, datetime]:
    """Source-file mtimes graphify records in manifest.json beside graph.json ({} if absent)."""
    try:
        data = json.loads((graph_path.parent / "manifest.json").read_text(encoding="utf-8"))
        return {f: datetime.fromtimestamp(v["mtime"]) for f, v in data.items()
                if isinstance(v, dict) and isinstance(v.get("mtime"), (int, float))}
    except (OSError, ValueError, AttributeError):
        return {}


# ---------------------------------------------------------------- qmg I/O

class GraphLock:
    """<pickle>.lock created with O_EXCL: the protocol qmg-mcp/server.py and the hermes-qmg plugin use."""

    def __init__(self, pickle_path: Path):
        self.path = pickle_path.with_suffix(pickle_path.suffix + ".lock")

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + LOCK_WAIT_S
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                try:  # a lock older than STALE_LOCK_S was left by a crashed writer: take it over
                    if time.time() - self.path.stat().st_mtime > STALE_LOCK_S:
                        self.path.unlink()
                        continue
                except OSError:  # released meanwhile, or still open by a live writer on Windows
                    pass
                if time.monotonic() > deadline:
                    raise SystemExit(f"error: {self.path} held by another writer for {LOCK_WAIT_S}s; nothing changed")
                time.sleep(0.2)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)  # if we stall past STALE_LOCK_S others may take over; check_budget then stops our save
        self.t0 = time.monotonic()
        return self

    def check_budget(self) -> None:
        if time.monotonic() - self.t0 > LOCK_BUDGET_S:
            raise SystemExit(f"error: lock held over {LOCK_BUDGET_S}s; nothing saved, re-run")

    def __exit__(self, *exc):
        # after a stall another writer may have taken over the lock; only remove our own
        try:
            if self.path.read_text() == str(os.getpid()):
                self.path.unlink()
        except FileNotFoundError:
            pass
        return False


class PrecomputedEncoder:
    """Stands in for the embedding model so add_memories_batch reuses vectors computed before locking."""

    def __init__(self, table: dict):
        self.table = table

    def encode(self, texts, **_):
        import numpy as np
        return np.stack([self.table[t] for t in texts])


def remove_project(graph, source: str) -> int:
    """Drop every memory a previous import stored under `source`."""
    stale = [mid for mid, m in graph.memories.items() if m.source == source]
    for mid in stale:
        del graph.memories[mid]
        if graph.graph.has_node(mid):
            graph.graph.remove_node(mid)
    if stale:
        if not hasattr(graph, "_rebuild_indices"):
            raise RuntimeError("quantum-memory-graph has no _rebuild_indices(); cannot safely remove memories")
        graph._rebuild_indices()
    return len(stale)


def save_atomic(graph, path: Path) -> None:
    """Write a temp file, back up the old pickle, then rename, so a crash never truncates it."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    try:
        graph.save(tmp)
        with open(tmp, "r+b") as fh:
            os.fsync(fh.fileno())
        if path.exists():
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("graph_json", type=Path, help="path to graphify-out/graph.json")
    p.add_argument("--project", help="project name used to tag memories (default: graph folder's parent name)")
    p.add_argument("--qmg-path", type=Path, default=None, help=f"memory pickle (default: $QMG_PATH or {default_persist_path()})")
    p.add_argument("--hubs", type=int, default=25, help="number of most-connected symbols to store (default 25)")
    p.add_argument("--symbols", action="store_true", help="store every callable symbol, not just hubs (large)")
    p.add_argument("--min-cluster", type=int, default=3, help="skip clusters smaller than this (default 3)")
    p.add_argument("--max-memories", type=int, default=3000, help="refuse to import more than this many (default 3000)")
    p.add_argument("--model", default=None, help="sentence-transformers model; must match the pickle's (default: qmg's)")
    p.add_argument("--dry-run", action="store_true", help="print the memories without touching the pickle")
    p.add_argument("--remove", action="store_true", help="only delete this project's imported memories")
    p.add_argument("--test-query", default=None, help="after import, run recall() with this query and print results")
    args = p.parse_args(argv)

    gpath = args.graph_json.resolve()
    project = args.project or (gpath.parent.parent.name if gpath.parent.name == "graphify-out" else gpath.parent.name)
    source = SOURCE_PREFIX + project
    qmg_path = (args.qmg_path or default_persist_path()).expanduser()

    specs: list[MemorySpec] = []
    built, mtimes = datetime.now(), {}
    if not args.remove:
        # stamp each memory with its newest source file's mtime (else the graph's build time),
        # never "now": qmg boosts recent memories and links ones stamped in the same hour
        built, mtimes = datetime.fromtimestamp(gpath.stat().st_mtime), file_mtimes(gpath)
        with open(gpath, encoding="utf-8") as fh:
            g = GraphifyGraph(json.load(fh))
        specs = build_memories(g, project, args.hubs, args.symbols, args.min_cluster, gpath, built)
        counts = Counter(s.kind for s in specs)
        print(f"{project}: {len(specs)} memories ({', '.join(f'{k}={v}' for k, v in counts.items())})")
        if len(specs) > args.max_memories:
            print(f"error: {len(specs)} memories exceeds --max-memories {args.max_memories}; "
                  "drop --symbols or raise the cap", file=sys.stderr)
            return 2
        if args.dry_run:
            for s in specs:
                print(f"\n[{s.kind}] {s.text}\n  entities: {s.entities}")
            return 0

    from quantum_memory_graph import MemoryGraph, recall
    from quantum_memory_graph.graph import Memory

    if args.remove and not qmg_path.exists():
        print(f"nothing to remove: {qmg_path} does not exist")
        return 0

    # qmg ids hash the first 200 chars; keep one spec per id so none is silently merged
    unique: dict[str, MemorySpec] = {}
    for s in specs:
        unique.setdefault(Memory.make_id(s.text), s)
    specs = list(unique.values())
    model_name = args.model or MemoryGraph.DEFAULT_MODEL
    encoder, vectors = None, {}
    if specs:
        # embed before taking the lock: other writers wait on it
        from sentence_transformers import SentenceTransformer
        encoder = SentenceTransformer(model_name)
        texts = [s.text for s in specs]
        vectors = dict(zip(texts, encoder.encode(texts, normalize_embeddings=True, show_progress_bar=False)))

    with GraphLock(qmg_path) as lock:
        graph = MemoryGraph.load(str(qmg_path)) if qmg_path.exists() else MemoryGraph(model=model_name)
        if specs and graph._model_name != model_name:
            raise SystemExit(f"error: {qmg_path} embeds with {graph._model_name}; re-run with --model {graph._model_name}")
        old_texts = {m.text for m in graph.memories.values() if m.source == source}
        if args.remove and not old_texts:
            print(f"nothing to remove for {source}")
            return 0
        if not args.remove and old_texts == {s.text for s in specs}:
            print(f"{source} is up to date ({len(old_texts)} memories); nothing written")
        else:
            removed = remove_project(graph, source)
            print(f"removed {removed} previous memories for {source}")
            if specs:
                graph._embedder = PrecomputedEncoder(vectors)
                stored = graph.add_memories_batch(
                    texts=[s.text for s in specs],
                    entities_list=[s.entities for s in specs],
                    timestamps=[max((mtimes[f] for f in s.files if f in mtimes), default=built) for s in specs],
                    sources=[source] * len(specs),
                )
                graph._embedder = encoder  # same pickle shape qmg's own writers produce
                # add_memories_batch has no metadata argument; attach it afterwards.
                for mem, spec in zip(stored, specs):
                    mem.metadata = {**spec.metadata, "kind": spec.kind, "graphify_graph": str(gpath)}
                print(f"stored {len(stored)} memories")
            lock.check_budget()
            save_atomic(graph, qmg_path)
            print(f"saved {qmg_path} (lock held {time.monotonic() - lock.t0:.1f}s)  stats={graph.stats()}")

    if args.test_query:
        res = recall(args.test_query, K=5, graph=graph)
        print(f"\nrecall({args.test_query!r}) via {res.get('method')}:")
        for m in res.get("memories", []):
            print(f"  {m['relevance']:.2f}  {m['text'][:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
