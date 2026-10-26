"""Self-check for scripts/graphify_to_qmg.py against a throwaway pickle (never the live graph).

Run with the python that has quantum-memory-graph installed:
  python tests/test_graphify_to_qmg.py
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bridge", ROOT / "scripts" / "graphify_to_qmg.py")
bridge = sys.modules["bridge"] = importlib.util.module_from_spec(spec)  # dataclasses needs it registered
spec.loader.exec_module(bridge)

from quantum_memory_graph.graph import MemoryGraph  # noqa: E402

FAKE_TOKEN = "ghp_" + "a1B2" * 9


def graph_json(helper_name: str) -> dict:
    node = lambda i, label, f, loc, c: {"id": i, "label": label, "file_type": "code", "source_file": f,
                                         "source_location": loc, "community": c, "community_name": "core"}
    return {
        "directed": True, "multigraph": False,
        "graph": {"schema_version": 1, "graphify_version": "test"},
        "nodes": [
            node("a", "a.py", "a.py", "L1", 0), node("b", "b.py", "b.py", "L1", 0),
            node("a_run", "run()", "a.py", "L3", 0), node("a_main", "main()", "a.py", "L9", 0),
            node("b_help", helper_name, "b.py", "L2", 0),
            {"id": "r1", "label": f"Loads config. token = {FAKE_TOKEN}", "file_type": "rationale",
             "source_file": "a.py", "source_location": "L4"},
        ],
        "links": [
            {"source": "a", "target": "a_run", "relation": "contains"},
            {"source": "a", "target": "a_main", "relation": "contains"},
            {"source": "b", "target": "b_help", "relation": "contains"},
            {"source": "a_main", "target": "a_run", "relation": "calls"},
            {"source": "a_run", "target": "b_help", "relation": "calls"},
            {"source": "r1", "target": "a_run", "relation": "rationale_for"},
        ],
    }


def run(*argv) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            code = bridge.main(list(argv))
        except SystemExit as e:
            code = e.code
    return code, out.getvalue()


def main() -> None:
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        gj = d / "demo" / "graphify-out" / "graph.json"
        gj.parent.mkdir(parents=True)
        gj.write_text(json.dumps(graph_json("helper()")), encoding="utf-8")
        a_edit = datetime(2026, 1, 2, 3, 4, 5)  # a.py's mtime as graphify recorded it; b.py has none
        (gj.parent / "manifest.json").write_text(json.dumps({"a.py": {"mtime": a_edit.timestamp()}}))
        pkl = d / "qmg_graph.pkl"
        g = MemoryGraph()
        g.add_memory("Decision: use Anchor 0.30 for new Solana programs", source="manual")
        g.save(str(pkl))
        args = (str(gj), "--qmg-path", str(pkl))

        code, out = run(*args)
        assert code == 0, out
        g = MemoryGraph.load(str(pkl))
        demo = [m for m in g.memories.values() if m.source == "graphify:demo"]
        assert any(m.source == "manual" for m in g.memories.values()), "own memory lost"
        assert len(demo) >= 4, out  # overview, 2 files, cluster, hubs
        assert all(len(m.text) <= bridge.MAX_TEXT for m in demo)
        assert not any(FAKE_TOKEN in m.text for m in demo), "secret not redacted"
        assert any("[REDACTED]" in m.text for m in demo), "rationale missing"
        built = datetime.fromtimestamp(gj.stat().st_mtime)
        stamp_of = {m.text.split(".")[0]: m.timestamp for m in demo}
        assert stamp_of["[graphify:demo] File a"] == a_edit, "file memory must carry its file's mtime"
        assert stamp_of["[graphify:demo] File b"] == built, "no manifest entry: fall back to the build time"
        assert all(m.timestamp in (a_edit, built) for m in demo), "never stamp with the import time"
        assert not pkl.with_suffix(".pkl.lock").exists()

        stamp = pkl.stat().st_mtime_ns
        code, out = run(*args, "--test-query", "which function calls helper")
        assert code == 0 and "up to date" in out and pkl.stat().st_mtime_ns == stamp, out
        assert "recall(" in out, "--test-query must still run when nothing changed"

        gj.write_text(json.dumps(graph_json("renamed_helper()")), encoding="utf-8")
        code, out = run(*args)
        assert code == 0, out
        texts = [m.text for m in MemoryGraph.load(str(pkl)).memories.values() if m.source == "graphify:demo"]
        assert any("renamed_helper()" in t for t in texts), texts
        assert not any(re.search(r"\bhelper\(\)", t) for t in texts), "stale memory left behind"

        lock = pkl.with_suffix(".pkl.lock")
        lock.write_text("999999")
        bridge.LOCK_WAIT_S, stamp = 0.3, pkl.stat().st_mtime_ns
        code, out = run(*args, "--remove")
        assert code != 0 and pkl.stat().st_mtime_ns == stamp, "must not write while another writer holds the lock"
        lock.unlink()

        with bridge.GraphLock(pkl):
            lock.write_text("12345")  # another writer took the lock over after a stall
        assert lock.exists(), "must not delete another writer's lock"
        lock.unlink()

        code, out = run(*args, "--remove")
        assert code == 0, out
        assert [m.source for m in MemoryGraph.load(str(pkl)).memories.values()] == ["manual"]

        fresh = d / "new-machine" / "qmg" / "memory_graph.pkl"  # folder does not exist yet
        code, out = run(str(gj), "--qmg-path", str(fresh))
        assert code == 0 and fresh.exists(), out
    check_default_path()
    print("ok: graphify_to_qmg self-check passed")


def check_default_path() -> None:
    with tempfile.TemporaryDirectory() as h, mock.patch.dict(os.environ, {"HOME": h, "USERPROFILE": h}, clear=True):
        own = bridge.default_persist_path()
        assert own.name == "memory_graph.pkl" and Path(h) in own.parents, own
        own.parent.mkdir(parents=True)
        (own.parent / "qmg_graph.pkl").touch()
        assert bridge.default_persist_path() == own.parent / "qmg_graph.pkl", "shared graph must win when it exists"
        os.environ["QMG_PATH"] = str(Path(h) / "x.pkl")
        assert bridge.default_persist_path() == Path(h) / "x.pkl", "env var must win"


if __name__ == "__main__":
    os.environ.pop("QMG_GRAPH_PATH", None)
    sys.exit(main())
