"""Run: python3 -I tests/test_canvas.py"""
import importlib.util, json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CANVAS = os.path.join(ROOT, "canvas.py")
TAIL = os.path.join(ROOT, "tail.py")
spec = importlib.util.spec_from_file_location("canvas", CANVAS)
canvas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(canvas)

NOW = 10_000_000  # ms


def lead(turn_start=NOW - 30_000, **over):
    d = {"model": "claude-opus-5-5", "effort": "high", "tools": 5, "top_tools": [("Bash", 3)],
         "last_tool": "Bash", "last_text": "", "out_tokens": 1200, "ctx": 50000, "turns": 2,
         "turn_start": turn_start, "turn_tools": 2, "errors": 0, "errors_in_row": 0,
         "iter_ts": [NOW - 5000, NOW - 4000], "tools": 5}
    d.update(over)
    return d


def advisor(present=False, **over):
    d = {"model": "claude-opus-5-5", "present": present, "calls": 0, "consulting": False,
         "checkpoints": {}, "last_kind": None, "recent": [], "last_ts": None, "last_text": "", "redacted": False}
    d.update(over)
    return d


def sub(i, name, status="running", started=NOW - 600_000, ended=None, detail="work", tools=1):
    return {"id": f"s{i}", "name": name, "model": "claude-haiku-5-5", "detail": detail, "type": "general-purpose",
            "status": status, "started": started, "ended": ended, "updated": ended or NOW - 1000,
            "tools": tools, "last_tool": "Read", "errors": 0, "errors_in_row": 0, "iter_ts": []}


def data(subs=(), adv=None, lead_events=(), log=(), turn_start=NOW - 30_000):
    return {
        "now": NOW,
        "terminal": "t1",
        "session": {"state": "working", "activity": "doing things", "title": "T", "id": "sess", "demo": False},
        "lead": lead(turn_start=turn_start),
        "advisor": adv if adv is not None else advisor(),
        "subagents": list(subs),
        "log": list(log),
        "lead_events": list(lead_events),
    }


def by_id(doc):
    return {n["id"]: n for n in doc["nodes"]}


def ids(doc):
    return set(by_id(doc))


def group_label(doc):
    return by_id(doc)["subagents"]["label"]


# -- 1. visibility rule ------------------------------------------------------------------

def test_visibility_running_old_shown():
    doc = canvas.build(data([sub(1, "old", "running", started=NOW - 600_000)]), 700)
    assert "agent-s1" in ids(doc), ids(doc)


def test_visibility_done_recent_vs_stale():
    subs = [
        sub(1, "recent", "completed", started=NOW - 600_000, ended=NOW - 10_000),   # ended 10 s ago
        sub(2, "stale", "completed", started=NOW - 400_000, ended=NOW - 300_000),   # ended 5 min ago
    ]
    doc = canvas.build(data(subs), 700)
    got = ids(doc)
    assert "agent-s1" in got, got
    assert "agent-s2" not in got, got
    assert "+1 earlier" in group_label(doc), group_label(doc)


def test_visibility_done_this_turn_shown():
    # started at/after lead.turn_start: this turn, so shown even though it finished.
    subs = [sub(1, "thisturn", "completed", started=NOW - 10_000, ended=NOW - 5_000)]
    doc = canvas.build(data(subs), 700)
    assert "agent-s1" in ids(doc), ids(doc)
    assert "+" not in group_label(doc), group_label(doc)


def test_visibility_mixed_label_counts_hidden():
    subs = [
        sub(1, "run", "running", started=NOW - 600_000),
        sub(2, "recent", "completed", started=NOW - 600_000, ended=NOW - 10_000),
        sub(3, "stale", "completed", started=NOW - 400_000, ended=NOW - 300_000),
        sub(4, "thisturn", "completed", started=NOW - 10_000, ended=NOW - 5_000),
    ]
    doc = canvas.build(data(subs), 700)
    got = ids(doc)
    assert {"agent-s1", "agent-s2", "agent-s4"} <= got and "agent-s3" not in got, got
    assert "+1 earlier" in group_label(doc), group_label(doc)


def test_visibility_none_visible_no_group_no_return():
    subs = [sub(1, "stale", "completed", started=NOW - 400_000, ended=NOW - 300_000)]
    doc = canvas.build(data(subs), 700)
    got = ids(doc)
    assert "subagents" not in got and "return" not in got, got
    assert not any(i.startswith("agent-") for i in got), got
    # and with no subagents at all
    doc = canvas.build(data([]), 700)
    got = ids(doc)
    assert "subagents" not in got and "return" not in got, got


# -- 2. advisor presence -----------------------------------------------------------------

def test_advisor_absent_has_no_advisor_nodes():
    for w in (400, 700):
        doc = canvas.build(data(adv=advisor(present=False, model="claude-opus-5-5")), w)
        got = ids(doc)
        assert not any("advisor" in i for i in got), (w, got)
        assert not any(i.startswith("cp-") for i in got), (w, got)


def test_advisor_present_wide():
    doc = canvas.build(data(adv=advisor(present=True)), 700)
    got = ids(doc)
    assert {"advisor-col", "advisor", "cp-plan", "cp-error", "cp-done"} <= got, got
    assert doc["x-herdr"]["wide"] is True


def test_advisor_present_narrow():
    doc = canvas.build(data(adv=advisor(present=True)), 400)
    got = ids(doc)
    assert "advisor" in got and "advisor-col" not in got, got
    assert doc["x-herdr"]["wide"] is False


# -- 3. edge messages --------------------------------------------------------------------

def test_spawn_message_rides_edge():
    subs = [sub(1, "alpha", "running", started=NOW - 1000, detail="find bugs")]
    evs = [{"ts": NOW - 1000, "kind": "spawn", "text": "alpha: find bugs"}]
    doc = canvas.build(data(subs, lead_events=evs), 700)
    edge = next(e for e in doc["edges"] if e["fromNode"] == "lead" and e["toNode"] == "agent-s1")
    texts = [m["text"] for m in edge["x-herdr"]["msgs"]]
    assert "task → alpha" in texts, texts


def test_old_spawn_message_dropped():
    subs = [sub(1, "alpha", "running", started=NOW - 1000, detail="find bugs")]
    evs = [{"ts": NOW - 40_000, "kind": "spawn", "text": "alpha: find bugs"}]
    doc = canvas.build(data(subs, lead_events=evs), 700)
    edge = next(e for e in doc["edges"] if e["fromNode"] == "lead" and e["toNode"] == "agent-s1")
    assert edge["x-herdr"]["msgs"] == [], edge["x-herdr"]["msgs"]


# -- 4. JSON Canvas validity -------------------------------------------------------------

SIDES = {"top", "right", "bottom", "left"}


def check_canvas(doc, label):
    json.dumps(doc)
    nodes = doc["nodes"]
    node_ids = [n["id"] for n in nodes]
    assert len(node_ids) == len(set(node_ids)), (label, "duplicate node ids", node_ids)
    for n in nodes:
        assert n["type"] in ("text", "group", "file", "link"), (label, n["id"], n["type"])
        for k in ("x", "y", "width", "height"):
            assert type(n[k]) is int, (label, n["id"], k, n[k])
        assert n["width"] > 0 and n["height"] > 0, (label, n["id"])
    edge_ids = [e["id"] for e in doc["edges"]]
    assert len(edge_ids) == len(set(edge_ids)), (label, "duplicate edge ids", edge_ids)
    known = set(node_ids)
    for e in doc["edges"]:
        assert e["fromNode"] in known and e["toNode"] in known, (label, e["id"])
        assert e["fromSide"] in SIDES and e["toSide"] in SIDES, (label, e["id"])


def test_build_output_is_valid_canvas():
    cases = []
    for w in (400, 700, 1200):
        for adv in (advisor(present=False), advisor(present=True, calls=2, last_kind="plan",
                    checkpoints={"plan": {"count": 2, "last_ts": NOW - 1000}})):
            for subs in ([], [sub(1, "a")], [sub(i, f"a{i}", "completed", started=NOW - 10_000, ended=NOW - 5_000)
                              for i in range(1, 4)],
                         [sub(i, f"a{i}") for i in range(1, 9)]):
                evs = [{"ts": NOW - 1000, "kind": "spawn", "text": "a1: x"}]
                log = [{"ts": NOW - 2000, "kind": "tool", "text": "Bash ls"}]
                cases.append((f"w{w} adv{adv['present']} subs{len(subs)}",
                              canvas.build(data(subs, adv=adv, lead_events=evs, log=log), w)))
    for label, doc in cases:
        check_canvas(doc, label)


# -- 5. tail.py exits when the subagent is finished --------------------------------------

def test_tail_exits_after_finish():
    with tempfile.TemporaryDirectory() as d:
        jsonl = os.path.join(d, "agent-x.jsonl")
        meta = os.path.join(d, "agent-x.meta.json")
        with open(jsonl, "w") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "hi"},
                                "timestamp": "2026-01-01T00:00:00.000Z"}) + "\n")
        with open(meta, "w") as f:
            json.dump({"finished": False}, f)
        p = subprocess.Popen([sys.executable, "-u", TAIL, jsonl], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(1.5)
            assert p.poll() is None, "tail exited before the subagent finished"
            with open(meta, "w") as f:
                json.dump({"finished": True}, f)
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                raise AssertionError("tail still running 8 s after finished")
            out, err = p.stdout.read(), p.stderr.read()
            assert p.returncode == 0, (p.returncode, err)
            assert "finished" in out and "task" in out, out
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception:
                import traceback
                fails += 1
                print("FAIL", name)
                traceback.print_exc()
    sys.exit(1 if fails else 0)
