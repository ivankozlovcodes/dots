"""Run: python3 -I tests/test_scan.py"""
import importlib.util, io, json, os, sys, tempfile, contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
SCAN = os.path.join(os.path.dirname(HERE), "scan.py")
spec = importlib.util.spec_from_file_location("scan", SCAN)
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)

_n = [0]


def ts():
    _n[0] += 1
    return f"2026-01-01T00:00:{_n[0] % 60:02d}.{_n[0] // 60:03d}Z"


def prompt(t="go"):
    return {"type": "user", "timestamp": ts(), "message": {"role": "user", "content": t}}


def tool(i, name="Bash"):
    return {"type": "assistant", "timestamp": ts(), "message": {"model": "claude-opus-5-5", "content": [
        {"type": "tool_use", "id": f"tu{i}", "name": name, "input": {"command": "ls"}}]}}


def result(i, err=False):
    b = {"type": "tool_result", "tool_use_id": f"tu{i}", "content": "x"}
    if err:
        b["is_error"] = True
    return {"type": "user", "timestamp": ts(), "message": {"role": "user", "content": [b]}}


def advisor(i):
    return {"type": "assistant", "timestamp": ts(), "message": {"content": [
        {"type": "server_tool_use", "id": f"srv{i}", "name": "advisor", "input": {}}]}}


def advisor_res(i):
    return {"type": "assistant", "timestamp": ts(), "message": {"content": [
        {"type": "advisor_tool_result", "tool_use_id": f"srv{i}",
         "content": {"type": "advisor_redacted_result", "encrypted_content": "zz"}}]}}


def write(path, evs, mode="w"):
    with open(path, mode) as f:
        for e in evs:
            f.write(json.dumps(e) + "\n")


def run_parse(evs, lead=True):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.jsonl")
        write(p, evs)
        return scan.parse(p, scan.new_state(), lead)


def test_errors():
    evs = [prompt(), tool(1), result(1, True), tool(2), result(2, True), tool(3), result(3), tool(4), result(4, True)]
    for lead in (True, False):
        st = run_parse(evs, lead)
        assert st["errors"] == 3 and st["errors_in_row"] == 1, (lead, st["errors"], st["errors_in_row"])
    st = run_parse(evs[:5])
    assert st["errors_in_row"] == 2
    assert len(st["iter_ts"]) == 2


def test_iter_cap():
    st = run_parse([tool(i) for i in range(30)])
    assert len(st["iter_ts"]) == 24 and st["tools"] == 30


def test_turn_tools():
    st = run_parse([prompt(), tool(1), tool(2), tool(3)])
    assert st["turn_tools"] == 3
    st = run_parse([prompt(), tool(1), tool(2), prompt(), tool(3)])
    assert st["turn_tools"] == 1 and st["tools"] == 3 and st["turns"] == 2


def kinds(st):
    return [c["kind"] for c in st["advisor"]["log"]]


def test_advisor_kinds():
    evs = [prompt(), advisor(1), advisor_res(1),            # plan (0 tools)
           tool(1), result(1), advisor(2), advisor_res(2),  # plan (1 tool)
           tool(2), result(2), advisor(3),                  # mid
           tool(3), result(3, True), tool(4), result(4, True), advisor(4)]  # error
    st = run_parse(evs)
    assert kinds(st) == ["plan", "plan", "mid", "error"], kinds(st)
    assert st["advisor"]["calls"] == 4 and st["advisor"]["redacted"] == 2


def test_advisor_retro_done():
    st = run_parse([prompt(), tool(1), tool(2), advisor(1), prompt(), tool(3)])
    assert kinds(st) == ["done"], kinds(st)
    st = run_parse([prompt(), tool(1), tool(2), advisor(1), tool(3), prompt()])
    assert kinds(st) == ["mid"], kinds(st)


def spawn(i, aid):
    return [{"type": "assistant", "timestamp": ts(), "message": {"model": "claude-opus-5-5", "content": [
                {"type": "tool_use", "id": f"ag{i}", "name": "Agent", "input": {"description": f"a{i}: x", "subagent_type": "general-purpose"}}]}},
            {"type": "user", "timestamp": ts(), "toolUseResult": {"isAsync": True, "status": "async_launched", "agentId": aid},
             "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"ag{i}", "content": "launched"}]}}]


def notify(i, aid):
    return {"type": "user", "timestamp": ts(), "message": {"role": "user", "content":
            f"<task-notification>\n<task-id>{aid}</task-id>\n<tool-use-id>ag{i}</tool-use-id>\n<status>completed</status>\n</task-notification>"}}


def test_advisor_live_done():
    # Consulted while a subagent still runs: not "done". After every one is back: "done", live.
    evs = [prompt(), tool(1), result(1), *spawn(1, "aaa"), *spawn(2, "bbb"), tool(2), result(2), advisor(1),
           notify(1, "aaa"), notify(2, "bbb"), tool(3), result(3), advisor(2)]
    st = run_parse(evs)
    assert kinds(st) == ["mid", "done"], kinds(st)


def make_lead(d, evs):
    p = os.path.join(d, "11111111-aaaa-bbbb-cccc-222222222222.jsonl")
    write(p, evs)
    return p


def run_main(argv):
    old = sys.argv, sys.stdout
    sys.argv = ["scan.py"] + argv
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            scan.main()
    finally:
        sys.argv = old[0]
    return json.loads(buf.getvalue())


def with_cache(d):
    scan.CACHE_DIR = os.path.join(d, "cache")
    os.makedirs(scan.CACHE_DIR)


def x(doc):
    return doc["x-herdr"]


def test_override_and_output():
    with tempfile.TemporaryDirectory() as d:
        with_cache(d)
        p = make_lead(d, [prompt(), tool(1), tool(2), advisor(1)])
        with open(os.path.join(scan.CACHE_DIR, "override.json"), "w") as f:
            json.dump({"transcript": p, "state": "idle", "activity": "act", "title": "ttl"}, f)
        doc = run_main(["--terminal", "t1", "--width", "400"])
        s = x(doc)["session"]
        assert s["demo"] is True and s["alive"] is True and s["state"] == "idle"
        assert s["activity"] == "act" and s["title"] == "ttl" and s["id"] == "11111111-aaaa-bbbb-cccc-222222222222"
        # idle + last call has no tools after it -> reported as done
        assert os.path.exists(os.path.join(scan.CACHE_DIR, s["id"] + ".json"))
        cache = json.load(open(os.path.join(scan.CACHE_DIR, s["id"] + ".json")))
        assert cache["v"] == scan.CACHE_VERSION and cache["lead"]["advisor"]["log"][0]["kind"] == "mid"  # cache not mutated
        # working state: stays mid
        with open(os.path.join(scan.CACHE_DIR, "override.json"), "w") as f:
            json.dump({"transcript": p, "state": "working"}, f)
        doc = run_main([])
        assert x(doc)["session"]["state"] == "working"
        # missing transcript -> override ignored
        with open(os.path.join(scan.CACHE_DIR, "override.json"), "w") as f:
            json.dump({"transcript": p + ".nope", "state": "working"}, f)
        assert scan.load_override() is None


def capture_data():
    """Run main with canvas.build stubbed to grab the data dict."""
    got = {}
    orig = scan.canvas.build
    scan.canvas.build = lambda data, w: got.update(data) or orig(data, w)
    return got, orig


def test_data_shape():
    with tempfile.TemporaryDirectory() as d:
        with_cache(d)
        p = make_lead(d, [prompt(), tool(1), result(1, True), advisor(1), tool(2), tool(3), advisor(2), prompt(), tool(4), advisor(3)])
        got, orig = capture_data()
        try:
            run_main(["--transcript", p])
            assert got["session"]["demo"] and got["session"]["state"] == "working"
            L, A = got["lead"], got["advisor"]
            assert L["turn_tools"] == 1 and L["errors"] == 1 and L["errors_in_row"] == 1 and len(L["iter_ts"]) == 4
            assert A["last_kind"] == "plan"
            cp = A["checkpoints"]
            assert set(cp) >= {"plan", "error", "done", "mid"}
            assert cp["mid"]["count"] == 0 and cp["done"]["count"] == 1 and cp["plan"]["count"] == 2 and cp["plan"]["last_ts"]
            assert len(A["recent"]) == 3
            # idle: last call has tools_since == 0 and is in the current turn -> done
            with open(os.path.join(scan.CACHE_DIR, "override.json"), "w") as f:
                json.dump({"transcript": p, "state": "idle"}, f)
            run_main([])
            assert got["advisor"]["last_kind"] == "done" and got["advisor"]["checkpoints"]["done"]["count"] == 2
        finally:
            scan.canvas.build = orig


def test_incremental():
    evs = [prompt(), advisor(1), tool(1), result(1, True), tool(2), result(2, True), advisor(2), tool(3), prompt(), tool(4), advisor(3)]
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.jsonl")
        write(p, evs)
        one = scan.parse(p, scan.new_state(), True)
        q = os.path.join(d, "a.jsonl")
        os.remove(q)
        write(q, evs[:6])
        st = scan.parse(q, scan.new_state(), True)
        # a half-written trailing line must not be consumed
        with open(q, "a") as f:
            f.write(json.dumps(evs[6])[:20])
        st = scan.parse(q, st, True)
        with open(q, "w") as f:
            for e in evs[:6]:
                f.write(json.dumps(e) + "\n")
            f.write(json.dumps(evs[6]) + "\n")
        write(q, evs[7:], "a")
        st = scan.parse(q, st, True)
        for k in ("errors", "errors_in_row", "turn_tools", "iter_ts", "advisor", "tools", "turns", "events"):
            assert st[k] == one[k], (k, st[k], one[k])


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
