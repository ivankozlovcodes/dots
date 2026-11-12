#!/usr/bin/env python3
"""Summarize one Claude Code session (lead, advisor, subagents) as JSON for the
claude-subagents Herdr mod.

    scan.py [--terminal tN | --session <id>] [--width px]

Prints a JSON Canvas 1.0 document (https://jsoncanvas.org) laid out for that
width; live details ride along in "x-herdr" fields that other viewers ignore.

Finds the session: herdr terminal -> its foreground `claude` pid ->
~/.claude/sessions/<pid>.json. Without --terminal (or when that fails), the most
recently updated live session. Then reads, read-only:

    ~/.claude/projects/<cwd-slug>/<session>.jsonl              the lead
    ~/.claude/projects/<cwd-slug>/<session>/subagents/agent-*  each subagent

Transcripts grow to many MB, so parsing is incremental: byte offsets and the
running totals are cached in ~/.cache/herdr-claude-subagents/<session>.json.
"""
import glob, json, os, re, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import canvas  # noqa: E402  (./canvas.py: lays the session out as JSON Canvas)
from datetime import datetime

HOME = os.path.expanduser("~")
CLAUDE = os.path.join(HOME, ".claude")
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache"), "herdr-claude-subagents")
CACHE_VERSION = 6
ITER_KEPT = 24
ADVISOR_LOG_KEPT = 20
EVENTS_KEPT = 40
LOG_SHOWN = 14


def clip(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def ts_ms(s):
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


# ---------------------------------------------------------------- session lookup

def hc_get(addr):
    for hc in ("hc", os.path.join(HOME, ".local/bin/hc")):
        try:
            r = subprocess.run([hc, "get", addr, "--json"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return json.loads(r.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            continue
    return None


def descendants(pid):
    """pid and its child processes (claude may run under a wrapper)."""
    out, todo = [], [int(pid)]
    while todo and len(out) < 64:
        p = todo.pop()
        out.append(p)
        try:
            with open(f"/proc/{p}/task/{p}/children") as f:
                todo += [int(c) for c in f.read().split()]
        except OSError:
            pass
    return out


def read_session(pid):
    try:
        with open(os.path.join(CLAUDE, "sessions", f"{pid}.json")) as f:
            s = json.load(f)
        return s if s.get("sessionId") else None
    except (OSError, ValueError):
        return None


def find_session(addr):
    term = hc_get(addr) if addr else None
    if term:
        fg = term.get("foreground") or {}
        for pid in [p for p in (fg.get("pid"), term.get("pid")) if p]:
            for p in descendants(pid):
                s = read_session(p)
                if s:
                    return s, term
    best = None
    for f in glob.glob(os.path.join(CLAUDE, "sessions", "*.json")):
        try:
            with open(f) as h:
                s = json.load(h)
        except (OSError, ValueError):
            continue
        if not s.get("sessionId") or not alive(s.get("pid")):
            continue
        if term and term.get("cwd") and s.get("cwd") != term.get("cwd"):
            continue
        if best is None or (s.get("updatedAt") or 0) > (best.get("updatedAt") or 0):
            best = s
    return best, term


def transcript_path(sess):
    sid, cwd = sess["sessionId"], sess.get("cwd") or ""
    p = os.path.join(CLAUDE, "projects", re.sub(r"[^A-Za-z0-9]", "-", cwd), f"{sid}.jsonl")
    if os.path.exists(p):
        return p
    hits = glob.glob(os.path.join(CLAUDE, "projects", "*", f"{sid}.jsonl"))
    return hits[0] if hits else p


# ---------------------------------------------------------------- transcript parsing

def tool_summary(name, inp):
    inp = inp if isinstance(inp, dict) else {}
    base = lambda p: os.path.basename(str(p or "").rstrip("/")) or str(p or "")
    if name == "Bash":
        return clip(inp.get("description") or inp.get("command"), 70)
    if name in ("Read", "Write", "Edit", "NotebookEdit"):
        return base(inp.get("file_path") or inp.get("notebook_path"))
    if name in ("Grep", "Glob"):
        return clip(inp.get("pattern"), 60)
    if name == "Agent" or name == "Task":
        return clip(inp.get("description"), 60)
    if name in ("WebFetch",):
        return clip(inp.get("url"), 60)
    if name in ("WebSearch",):
        return clip(inp.get("query"), 60)
    if name == "Skill":
        return clip(inp.get("skill"), 40)
    if name.startswith("mcp__"):
        return name.split("__")[-1]
    for v in inp.values():
        if isinstance(v, str) and v.strip():
            return clip(v, 60)
    return ""


def is_prompt(e):
    """A user message the person typed (not a tool result, reminder or notification)."""
    if e.get("type") != "user" or e.get("isMeta") or e.get("isSidechain"):
        return False
    c = (e.get("message") or {}).get("content")
    if isinstance(c, str):
        return bool(c.strip()) and not c.lstrip().startswith("<")
    if isinstance(c, list):
        if any(b.get("type") == "tool_result" for b in c if isinstance(b, dict)):
            return False
        txt = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
        return any(t.strip() and not t.lstrip().startswith("<") for t in txt)
    return False


def new_state():
    return {
        "offset": 0, "ino": None,
        "model": None, "effort": None, "advisor_model": None,
        "tools": 0, "tool_counts": {}, "last_tool": "", "last_text": "",
        "out_tokens": 0, "ctx": 0, "first_ts": None, "last_ts": None,
        "turn_start": None, "turns": 0,
        "errors": 0, "errors_in_row": 0, "turn_tools": 0, "iter_ts": [],
        "advisor_decl": None,  # the advisor tool as the API request declared it: {model, deferred}
        "advisor": {"calls": 0, "last_ts": None, "last_text": "", "redacted": 0, "errors": [], "pending": {},
                    "log": [], "since": 0},
        "agents": {},  # tool_use_id -> {desc, type, model, ts, agentId, result_ts, status}
        "events": [],
    }


def push(st, ts, kind, text, who=None):
    st["events"].append({"ts": ts, "kind": kind, "text": clip(text, 90), **({"who": who} if who else {})})
    if len(st["events"]) > EVENTS_KEPT:
        del st["events"][: len(st["events"]) - EVENTS_KEPT]


def feed(st, e, lead):
    ts = ts_ms(e.get("timestamp"))
    t = e.get("type")
    if ts:
        st["first_ts"] = st["first_ts"] or ts
        st["last_ts"] = ts
    msg = e.get("message") or {}
    if lead and t == "api-request-shape":
        # Is the advisor tool really there? Declared tools are listed in the request shape;
        # a deferred one ("defer_loading") isn't loaded unless it gets called up.
        def find(o):
            if isinstance(o, dict):
                if str(o.get("type", "")).startswith("advisor_") and o.get("name") == "advisor":
                    return o
                o = list(o.values())
            if isinstance(o, list):
                for v in o:
                    r = find(v)
                    if r:
                        return r
            return None
        decl = find(e.get("shape"))
        st["advisor_decl"] = {"model": decl.get("model"), "deferred": bool(decl.get("defer_loading"))} if decl else None
        return
    if lead and is_prompt(e):
        log = st["advisor"]["log"]
        if log and log[-1]["turn"] == st["turns"] and st["advisor"]["since"] == 0:
            log[-1]["kind"] = "done"  # the turn's last advice was followed by no work
        st["turn_start"] = ts
        st["turns"] += 1
        st["turn_tools"] = 0
        c = msg.get("content")
        text = c if isinstance(c, str) else " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
        push(st, ts, "prompt", text)
        return
    if t == "assistant":
        if msg.get("model") and not str(msg.get("model")).startswith("<"):
            st["model"] = msg["model"]
        st["effort"] = e.get("effort") or e.get("perTurnEffort") or st["effort"]
        st["advisor_model"] = e.get("advisorModel") or st["advisor_model"]
        u = msg.get("usage") or {}
        st["out_tokens"] += u.get("output_tokens") or 0
        ctx = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
        if ctx:
            st["ctx"] = ctx
        for b in msg.get("content") or []:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "tool_use":
                name = b.get("name") or "?"
                summ = tool_summary(name, b.get("input"))
                st["tools"] += 1
                st["turn_tools"] += 1
                st["advisor"]["since"] += 1
                st["iter_ts"] = (st["iter_ts"] + [ts])[-ITER_KEPT:]
                st["tool_counts"][name] = st["tool_counts"].get(name, 0) + 1
                st["last_tool"] = f"{name} {summ}".strip()
                if lead and name in ("Agent", "Task"):
                    inp = b.get("input") or {}
                    st["agents"][b.get("id")] = {
                        "desc": inp.get("description") or "", "type": inp.get("subagent_type") or "",
                        "model": inp.get("model") or "", "ts": ts, "status": "starting",
                    }
                    push(st, ts, "spawn", inp.get("description") or inp.get("subagent_type") or "subagent")
                else:
                    push(st, ts, "tool", st["last_tool"])
            elif bt == "server_tool_use" and b.get("name") == "advisor":
                adv = st["advisor"]
                adv["calls"] += 1
                # "done" live: this turn delegated, and every subagent has come back.
                turn_agents = [a for a in st["agents"].values() if (a.get("ts") or 0) >= (st["turn_start"] or 0)]
                all_back = bool(turn_agents) and all(a.get("status") in ("done", "failed") for a in turn_agents)
                kind = ("error" if st["errors_in_row"] >= 2 else "done" if all_back
                        else "plan" if st["turn_tools"] <= 1 else "mid")
                adv["log"] = (adv["log"] + [{"ts": ts, "kind": kind, "turn": st["turns"]}])[-ADVISOR_LOG_KEPT:]
                adv["since"] = 0
                st["advisor"]["last_ts"] = ts
                st["advisor"]["pending"][b.get("id")] = ts
                push(st, ts, "advisor", "consulted")
            elif bt == "advisor_tool_result":
                c = b.get("content") or {}
                ct = c.get("type") if isinstance(c, dict) else None
                st["advisor"]["pending"].pop(b.get("tool_use_id"), None)
                if ct == "advisor_result":
                    st["advisor"]["last_text"] = clip(c.get("text"), 240)
                    push(st, ts, "advice", c.get("text"))
                elif ct == "advisor_redacted_result":
                    st["advisor"]["redacted"] += 1
                    push(st, ts, "advice", "advice returned (encrypted)")
                elif ct == "advisor_tool_result_error":
                    st["advisor"]["errors"] = (st["advisor"]["errors"] + [c.get("error_code")])[-3:]
                    push(st, ts, "advice", f"advisor error: {c.get('error_code')}")
            elif bt == "text" and (b.get("text") or "").strip():
                st["last_text"] = clip(b["text"], 200)
            elif bt == "thinking" and (b.get("thinking") or "").strip():
                st["last_text"] = clip(b["thinking"], 200)
    elif t == "user":
        tur = e.get("toolUseResult")
        for b in msg.get("content") or [] if isinstance(msg.get("content"), list) else []:
            if not isinstance(b, dict) or b.get("type") != "tool_result":
                continue
            if b.get("is_error"):
                st["errors"] += 1
                st["errors_in_row"] += 1
            else:
                st["errors_in_row"] = 0
            a = st["agents"].get(b.get("tool_use_id")) if lead else None
            if not a:
                continue
            if isinstance(tur, dict) and tur.get("agentId"):
                a["agentId"] = tur["agentId"]
                a["model"] = tur.get("resolvedModel") or a["model"]
            if isinstance(tur, dict) and tur.get("status") == "async_launched":
                a["status"] = "running"
            else:
                a["status"] = "failed" if b.get("is_error") else "done"
                a["result_ts"] = ts
                push(st, ts, "return", a["desc"] or "subagent")
        # Background agents report back through a <task-notification> message.
        c = msg.get("content")
        if lead and isinstance(c, str) and "<task-notification>" in c:
            m = re.search(r"<tool-use-id>([^<]+)</tool-use-id>", c)
            a = st["agents"].get(m.group(1)) if m else None
            if a:
                a["status"] = "failed" if re.search(r"<status>(failed|error|killed)", c) else "done"
                a["result_ts"] = ts
                push(st, ts, "return", a["desc"] or "subagent")


def parse(path, st, lead):
    try:
        info = os.stat(path)
    except OSError:
        return st
    if st["ino"] != info.st_ino or info.st_size < st["offset"]:
        st = new_state()
        st["ino"] = info.st_ino
    if info.st_size == st["offset"]:
        return st
    with open(path, "rb") as f:
        f.seek(st["offset"])
        chunk = f.read()
    end = chunk.rfind(b"\n")
    if end < 0:
        return st
    for line in chunk[: end + 1].splitlines():
        if not line.strip():
            continue
        try:
            feed(st, json.loads(line), lead)
        except (ValueError, AttributeError, TypeError):
            continue
    st["offset"] += end + 1
    return st


# ---------------------------------------------------------------- main

def name_of(desc, kind):
    if ":" in desc:
        head, rest = desc.split(":", 1)
        if 0 < len(head.strip()) <= 18:
            return head.strip(), rest.strip()
    return (kind or "agent"), desc


def main():
    addr = None
    demo = load_override()
    if "--transcript" in sys.argv:
        i = sys.argv.index("--transcript")
        if i + 1 < len(sys.argv) and os.path.exists(sys.argv[i + 1]):
            demo = {"transcript": os.path.abspath(sys.argv[i + 1]), "state": "working"}
    if "--terminal" in sys.argv and not demo:
        i = sys.argv.index("--terminal")
        addr = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
    now = int(time.time() * 1000)
    if demo:
        sess, term = {"sessionId": os.path.basename(demo["transcript"])[: -len(".jsonl")], "cwd": "", "pid": None}, None
    elif "--session" in sys.argv:  # debugging: a session by id, even a finished one
        sid = sys.argv[sys.argv.index("--session") + 1]
        hits = glob.glob(os.path.join(CLAUDE, "projects", "*", f"{sid}.jsonl"))
        sess, term = ({"sessionId": sid, "cwd": "", "pid": None}, None) if hits else (None, None)
    else:
        sess, term = find_session(addr)
    if not sess:
        json.dump({"nodes": [], "edges": [], "x-herdr": {"now": now, "session": None, "terminal": addr}}, sys.stdout)
        return
    sid = sess["sessionId"]
    tpath = demo["transcript"] if demo else transcript_path(sess)
    os.makedirs(CACHE_DIR, exist_ok=True)
    cpath = os.path.join(CACHE_DIR, f"{sid}.json")
    try:
        with open(cpath) as f:
            cache = json.load(f)
        if cache.get("v") != CACHE_VERSION:
            raise ValueError
    except (OSError, ValueError):
        cache = {"v": CACHE_VERSION, "lead": new_state(), "subs": {}}

    lead = cache["lead"] = parse(tpath, cache["lead"], True)
    lead_alive = True if demo else alive(sess.get("pid"))
    sub_dir = os.path.join(tpath[: -len(".jsonl")], "subagents")
    by_agent = {a.get("agentId"): (tid, a) for tid, a in lead["agents"].items() if a.get("agentId")}
    by_tool = lead["agents"]

    subs, log = [], [dict(e, who="lead") for e in lead["events"]]
    for meta_path in glob.glob(os.path.join(sub_dir, "agent-*.meta.json")):
        aid = os.path.basename(meta_path)[len("agent-"): -len(".meta.json")]
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        jpath = meta_path[: -len(".meta.json")] + ".jsonl"
        st = cache["subs"][aid] = parse(jpath, cache["subs"].get(aid) or new_state(), False)
        tid = meta.get("toolUseId")
        spawn = by_tool.get(tid) or (by_agent.get(aid) or (None, {}))[1]
        desc = meta.get("description") or spawn.get("desc") or ""
        name, detail = name_of(desc, meta.get("agentType"))
        if meta.get("finished") or spawn.get("status") in ("done", "failed"):
            status = "failed" if spawn.get("status") == "failed" else "done"
        elif not lead_alive:
            status = "stopped"
        else:
            status = "running"
        try:
            mtime = int(os.path.getmtime(jpath) * 1000)
        except OSError:
            mtime = st["last_ts"]
        subs.append({
            "id": aid, "name": name, "detail": detail, "type": meta.get("agentType") or "",
            "model": st["model"] or meta.get("pickedEffortModel") or meta.get("model") or "",
            "status": status, "background": meta.get("requestShape") == "background",
            "depth": meta.get("spawnDepth") or 1,
            "tools": st["tools"], "last_tool": st["last_tool"], "last_text": st["last_text"],
            "out_tokens": st["out_tokens"], "ctx": st["ctx"],
            "errors": st["errors"], "errors_in_row": st["errors_in_row"], "iter_ts": st["iter_ts"],
            "started": st["first_ts"] or spawn.get("ts"), "updated": max(filter(None, [st["last_ts"], mtime]), default=None),
            "ended": spawn.get("result_ts") or (st["last_ts"] if status != "running" else None),
            "transcript": jpath,
        })
        for ev in st["events"]:
            if ev["kind"] == "tool":
                log.append(dict(ev, who=name, model=subs[-1]["model"]))

    with open(cpath + ".tmp", "w") as f:
        json.dump(cache, f)
    os.replace(cpath + ".tmp", cpath)

    order = {"running": 0, "failed": 1, "stopped": 1, "done": 2}
    subs.sort(key=lambda s: (order.get(s["status"], 3), -(s["started"] or 0)))
    log = sorted((e for e in log if e.get("ts")), key=lambda e: e["ts"])[-LOG_SHOWN:]
    status = (term or {}).get("status") or {}
    adv = lead["advisor"]
    state = demo.get("state") or "" if demo else status.get("state") or sess.get("status") or ""
    alog = [dict(c) for c in adv["log"]]
    if alog and state != "working" and alog[-1]["turn"] == lead["turns"] and adv["since"] == 0:
        alog[-1]["kind"] = "done"
    checkpoints = {k: {"count": 0, "last_ts": None} for k in ("plan", "error", "done", "mid")}
    for c in alog:
        cp = checkpoints.setdefault(c["kind"], {"count": 0, "last_ts": None})
        cp["count"] += 1
        cp["last_ts"] = max(filter(None, [cp["last_ts"], c["ts"]]), default=None)

    data = {
        "now": now,
        "terminal": addr,
        "session": {
            "id": sid, "name": sess.get("name") or "", "cwd": sess.get("cwd") or "", "pid": sess.get("pid"),
            "alive": lead_alive, "state": state,
            "activity": (demo.get("activity") or "") if demo else status.get("msg") or "",
            "title": (demo.get("title") or "") if demo else (term or {}).get("title") or "",
            "transcript": tpath, "version": sess.get("version") or "",
            **({"demo": True} if demo else {}),
        },
        "lead": {
            "model": lead["model"] or "", "effort": lead["effort"] or "", "tools": lead["tools"],
            "top_tools": sorted(lead["tool_counts"].items(), key=lambda kv: -kv[1])[:4],
            "last_tool": lead["last_tool"], "last_text": lead["last_text"],
            "out_tokens": lead["out_tokens"], "ctx": lead["ctx"], "turns": lead["turns"],
            "turn_tools": lead["turn_tools"], "errors": lead["errors"], "errors_in_row": lead["errors_in_row"],
            "iter_ts": lead["iter_ts"],
            "turn_start": lead["turn_start"], "started": lead["first_ts"], "updated": lead["last_ts"],
        },
        "advisor": {
            "model": lead["advisor_model"] or "", "calls": adv["calls"], "last_ts": adv["last_ts"],
            "last_text": adv["last_text"], "redacted": adv["redacted"], "errors": adv["errors"],
            "consulting": bool(adv["pending"]),
            # Drawn only when it's really there: consulted this session, or loaded (not deferred).
            "present": adv["calls"] > 0 or bool(lead.get("advisor_decl") and not lead["advisor_decl"]["deferred"]),
            "declared": lead.get("advisor_decl"),
            "checkpoints": checkpoints, "last_kind": alog[-1]["kind"] if alog else None, "recent": alog[-5:],
        },
        "subagents": subs,
        "log": log,
        "lead_events": lead["events"][-20:],  # spawns, returns, advisor calls: the messages edges carry
    }
    doc = canvas.build(data, width_arg())
    text = json.dumps(doc)
    # The live canvas, for any JSON Canvas viewer; only rewritten when it changes.
    out = os.path.join(CACHE_DIR, f"{sid}.canvas")
    try:
        with open(out) as f:
            same = f.read() == text
    except OSError:
        same = False
    if not same:
        with open(out + ".tmp", "w") as f:
            f.write(text)
        os.replace(out + ".tmp", out)
    sys.stdout.write(text)


def load_override():
    """Demo mode: CACHE_DIR/override.json points at a transcript to show instead of a live session."""
    try:
        with open(os.path.join(CACHE_DIR, "override.json")) as f:
            o = json.load(f)
        t = o.get("transcript")
        if isinstance(o, dict) and isinstance(t, str) and t.endswith(".jsonl") and os.path.exists(t):
            return {"transcript": t, "state": o.get("state") or "working",
                    "activity": o.get("activity") or "", "title": o.get("title") or ""}
    except (OSError, ValueError, AttributeError):
        pass
    return None


def width_arg():
    if "--width" in sys.argv:
        try:
            return max(220, int(float(sys.argv[sys.argv.index("--width") + 1])))
        except (IndexError, ValueError):
            pass
    return 400

if __name__ == "__main__":
    main()
