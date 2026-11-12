#!/usr/bin/env python3
"""Summarize pi-subagents async runs as JSON for the pi-subagents Herdr mod.

Reads <tmpdir>/pi-subagents-uid-<uid>/async-subagent-runs/*/status.json.
Read-only. Prints {"root": ..., "runs": [...]} on stdout.
"""
import json, os, sys, tempfile, time

ROOT = os.path.join(tempfile.gettempdir(), f"pi-subagents-uid-{os.getuid()}", "async-subagent-runs")
MAX_AGE_MS = 24 * 3600 * 1000
LIMIT = 40


def clip(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def task_of(step):
    name = step.get("sessionName") or ""
    if ": " in name:
        name = name.split(": ", 1)[1]
    return clip(name, 120)


def step_view(st):
    tools = [clip(f"{t.get('tool')} {t.get('args') or ''}", 90) for t in (st.get("recentTools") or [])[-3:]]
    out = [clip(l, 110) for l in (st.get("recentOutput") or []) if str(l).strip()][-4:]
    tok = st.get("tokens") or {}
    cost = (st.get("totalCost") or {}).get("costUsd")
    model = st.get("model") or ""
    return {
        "agent": st.get("agent") or "?",
        "label": st.get("label") or st.get("workflowKey") or "",
        "task": task_of(st),
        "status": st.get("status") or "",
        "model": model.split("/")[-1],
        "runId": st.get("runId"),
        "startedAt": st.get("startedAt"),
        "endedAt": st.get("endedAt"),
        "tools": tools,
        "output": out,
        "tokens": tok.get("total"),
        "cost": cost,
        "error": clip(st.get("error"), 120) if st.get("error") else "",
    }


def main():
    now = int(time.time() * 1000)
    runs = []
    try:
        ids = os.listdir(ROOT)
    except OSError:
        ids = []
    for rid in ids:
        d = os.path.join(ROOT, rid)
        try:
            with open(os.path.join(d, "status.json")) as f:
                s = json.load(f)
        except (OSError, ValueError):
            continue
        # Children of a workflow are shown under their workflow root.
        if s.get("parentWorkflowRunId"):
            continue
        last = s.get("lastUpdate") or s.get("startedAt") or 0
        state = s.get("state") or ""
        if state not in ("running", "queued") and now - last > MAX_AGE_MS:
            continue
        steps = [step_view(st) for st in s.get("steps") or []]
        # Workflow steps only carry a pointer; enrich from the child's own status.
        for v in steps:
            if v["runId"] and not v["tools"] and not v["output"]:
                try:
                    with open(os.path.join(ROOT, v["runId"], "status.json")) as f:
                        cs = json.load(f)
                    full = step_view((cs.get("steps") or [{}])[0])
                    for k in ("tools", "output", "tokens", "cost", "model", "endedAt"):
                        v[k] = v[k] or full[k]
                except (OSError, ValueError, IndexError):
                    pass
        log = s.get("outputFile") or os.path.join(d, "output-0.log")
        runs.append({
            "id": rid,
            "mode": s.get("mode") or "single",
            "state": state,
            "cwd": s.get("cwd") or "",
            "session": s.get("sessionId") or "",
            "startedAt": s.get("startedAt"),
            "endedAt": s.get("endedAt"),
            "lastUpdate": last,
            "error": clip(s.get("error"), 120) if s.get("error") else "",
            "log": log if os.path.exists(log) else "",
            "dir": d,
            "steps": steps,
        })
    live = lambda r: r["state"] in ("running", "queued")
    runs.sort(key=lambda r: (not live(r), -(r["lastUpdate"] or 0)))
    json.dump({"root": ROOT, "now": now, "runs": runs[:LIMIT]}, sys.stdout)


if __name__ == "__main__":
    main()
