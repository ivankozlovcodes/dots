"""Lay a scanned Claude Code session out as a JSON Canvas 1.0 document.

https://jsoncanvas.org/spec/1.0/ : nodes {id, type, x, y, width, height, color?}
(text nodes carry Markdown `text`, groups a `label`) and edges {id, fromNode,
fromSide, toNode, toSide, toEnd?, color?, label?}. Every node's Markdown reads on
its own, so any canvas viewer shows the session; the herdr mod draws richer
widgets from the "x-herdr" field each node and edge carries (kind + live data).

Two layouts, picked by width:

  narrow (< WIDE)                      wide (>= WIDE)
    advisor                              ┌ advisor ┐
      ┊                                  │ header  │
    lead                                 │ plan ┄┄┄┼┄▸ lead
      │                                  │         │     │
    [ subagents ]                        │ error ┄┄┼┄▸ [ subagents ]
      │                                  │         │     │
    back to lead                         │ done ┄┄┄┼┄▸ back to lead
    session log                          └─────────┘ session log

Progress is data, not decoration: node x-herdr carries `iters` (tool calls),
`last_iter` (ms), `errors_in_row`; edge x-herdr carries `progress` (0..1),
`live`, `error`. The renderer turns those into filling borders and edges.
"""
import re
import time

WIDE = 620        # canvas width at which the advisor gets its own column
ADV_W = 184       # advisor column width in the wide layout
COL_GAP = 44      # between advisor column and the flow
MAX_CARDS = 6
GAP = 40          # between rows, room for an edge and its label
CARD_H = 116
GROUP_PAD = 10
GROUP_HEAD = 26
SLOTS = 24        # border segments: one per iteration, then it laps

# JSON Canvas preset colors: 1 red, 2 orange, 3 yellow, 4 green, 5 cyan, 6 purple.
FAMILY_COLOR = {"opus": "6", "sonnet": "2", "haiku": "5", "fable": "4", "mythos": "4"}
EFFORT = {"low": 1, "medium": 2, "high": 3, "xhigh": 4, "max": 5}
CHECKPOINTS = [("plan", "before a plan"), ("error", "same error ×2"), ("done", "before done")]
HOT_MS = 20000      # a checkpoint counts as "just fired" for this long
MSG_WINDOW = 30000  # messages newer than this ride along on their edge
LINGER_MS = 60000   # a finished subagent from an earlier turn stays on the canvas this long


def family(model):
    m = (model or "").lower()
    return next((f for f in FAMILY_COLOR if f in m), "other")


def model_name(model):
    """claude-opus-5-5 → Opus 5.5"""
    m = re.match(r"^(?:claude-)?([a-z]+)(?:-(\d+))?(?:-(\d+))?", (model or "").lower())
    if not m:
        return model or "?"
    name = m.group(1).capitalize()
    if m.group(2):
        name += " " + m.group(2) + ("." + m.group(3) if m.group(3) else "")
    return name


def color_of(model):
    return FAMILY_COLOR.get(family(model), "3")


def kfmt(n):
    n = n or 0
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{round(n / 1000)}k" if n >= 1000 else str(n)


def dur(ms):
    if ms is None or ms < 0:
        return ""
    s = int(ms // 1000)
    if s < 60:
        return f"{s}s"
    m = s // 60
    return f"{m}m {s % 60}s" if m < 60 else f"{m // 60}h {m % 60}m"


def clock(ms):
    return time.strftime("%H:%M:%S", time.localtime(ms / 1000))


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def last_iter(x):
    ts = x.get("iter_ts") or []
    return ts[-1] if ts else x.get("updated")


def build(d, width):
    W = int(width)
    now = d["now"]
    S, L, A, subs = d["session"], d["lead"], d["advisor"], d["subagents"]
    nodes, edges = [], []
    has_adv = bool(A.get("model")) and bool(A.get("present"))
    wide = W >= WIDE and has_adv

    def node(id_, kind, x, y_, w, h, text, color=None, extra=None, type_="text"):
        n = {"id": id_, "type": type_, "x": int(x), "y": int(y_), "width": int(w), "height": int(h)}
        if type_ == "group":
            n["label"] = text
        else:
            n["text"] = text
        if color:
            n["color"] = color
        n["x-herdr"] = {"kind": kind, **(extra or {})}
        nodes.append(n)
        return n

    def edge(a, a_side, b, b_side, label=None, color=None, dashed=False, live=False, progress=0.0, error=False, msgs=None):
        e = {"id": f"{a}-{b}", "fromNode": a, "fromSide": a_side, "toNode": b, "toSide": b_side, "toEnd": "arrow"}
        if label:
            e["label"] = label
        if color:
            e["color"] = color
        e["x-herdr"] = {"dashed": dashed, "live": live, "progress": round(max(0.0, min(1.0, progress)), 3), "error": error,
                        "msgs": msgs or []}
        edges.append(e)

    # Messages between agents, for edges to carry: each one travels its edge once, live.
    lead_ev = [e for e in d.get("lead_events", []) if e.get("ts") and now - e["ts"] < MSG_WINDOW]

    def msgs_for(s, kind, text):
        def mine(e):
            return e["kind"] == kind and (e["text"] in (f"{s['name']}: {s['detail']}", s["detail"])
                                          or e["text"].startswith(f"{s['name']}:"))
        return [{"ts": e["ts"], "text": text} for e in lead_ev if mine(e)]

    def adv_msgs(kind=None):
        recent = A.get("recent") or []
        def kind_at(ts):  # the checkpoint of the advisor call at or just before ts
            k = [r["kind"] for r in recent if r["ts"] <= ts + 1]
            return k[-1] if k else None
        out = []
        for e in lead_ev:
            if e["kind"] not in ("advisor", "advice") or (kind and kind_at(e["ts"]) != kind):
                continue
            out.append({"ts": e["ts"], "text": "consult" if e["kind"] == "advisor" else "advice",
                        "rev": e["kind"] == "advisor"})
        return out

    working = S["state"] == "working"
    running = [s for s in subs if s["status"] == "running"]
    fx, FW = (ADV_W + COL_GAP, W - ADV_W - COL_GAP) if wide else (0, W)
    y = 0
    lead_h = 136

    # -- advisor (narrow: a card on top) ------------------------------------------
    cps = A.get("checkpoints") or {}
    last_kind = A.get("last_kind")
    hot = lambda k: bool(cps.get(k, {}).get("last_ts")) and now - cps[k]["last_ts"] < HOT_MS
    advice = A.get("last_text") or ("advice encrypted (lead-only)" if A.get("redacted") else "")
    ago = dur(now - A["last_ts"]).split(" ")[0] + " ago" if A.get("last_ts") else ""
    line = f"consulted {A['calls']}× · last {ago}" if A.get("calls") else "on call · not consulted yet"
    head_h = 132 if advice else 104
    if wide:  # start the flow low enough that "before a plan" sits level with the lead
        y = max(0, int(GROUP_HEAD + head_h + 12 + 21 - lead_h / 2))
    adv_extra = {**A, "line": line, "advice": advice, "wide": wide,
                 "hot": {k: hot(k) for k, _ in CHECKPOINTS}, "checkpoints": cps, "last_kind": last_kind}
    if has_adv and not wide:
        h = 96 if advice else 76
        node("advisor", "advisor", 0, y, W, h,
             f"**{model_name(A['model'])} · advisor**\n{line}" + (f"\n\n» {advice}" if advice else ""),
             color_of(A["model"]), adv_extra)
        edge("advisor", "bottom", "lead", "top", "advising" if A.get("consulting") else ("advises" if A.get("calls") else None),
             color_of(A["model"]), dashed=True, live=bool(A.get("consulting")), progress=1.0 if A.get("calls") else 0.0,
             msgs=adv_msgs())
        y += h + GAP

    # -- lead -----------------------------------------------------------------------
    activity = S["activity"] or L["last_text"] or S["title"] or ""
    tools = ", ".join(f"{n} {k}" for n, k in L["top_tools"])
    turn_tools = L.get("turn_tools", 0)
    node("lead", "lead", fx, y, FW, lead_h,
         f"**{model_name(L['model'])} · main session** — {S['state'] or 'idle'}\n{activity}\n\n"
         f"effort `{L['effort'] or '?'}` · {plural(L['tools'], 'tool call')} ({tools}) · {turn_tools} this turn\n"
         f"context {kfmt(L['ctx'])} · out {kfmt(L['out_tokens'])} · turn {L['turns']}",
         color_of(L["model"]),
         {**L, "state": S["state"], "activity": activity, "effort_level": EFFORT.get(L["effort"], 0),
          "elapsed": dur(now - L["turn_start"]) if working and L["turn_start"] else "",
          "iters": turn_tools, "slots": SLOTS, "last_iter": last_iter(L), "live": working,
          "errors_in_row": L.get("errors_in_row", 0), "done": False})
    y += lead_h + GAP
    targets = {"plan": "lead"}

    # -- subagents ----------------------------------------------------------------------
    # Only what's live: running, started this turn, or finished within LINGER_MS.
    # Older ones leave the canvas and are only counted in the group label.
    turn = L["turn_start"] or 0
    this_turn = [s for s in subs if (s["started"] or 0) >= turn]
    visible = [s for s in subs if s["status"] == "running" or (s["started"] or 0) >= turn
               or (s["ended"] and now - s["ended"] < LINGER_MS)]
    shown = visible[:MAX_CARDS]
    if shown:
        cols = 2 if FW >= 360 else 1
        rows = (len(shown) + cols - 1) // cols
        cw = (FW - 2 * GROUP_PAD - (cols - 1) * GROUP_PAD) / cols
        gh = GROUP_HEAD + rows * (CARD_H + GROUP_PAD)
        models = list(dict.fromkeys(model_name(s["model"]) for s in shown if s["model"]))
        more = f" · +{len(subs) - len(shown)} earlier" if len(subs) > len(shown) else ""
        finished = sum(1 for s in shown if s["status"] != "running")
        node("subagents", "group", fx, y, FW, gh,
             f"subagents · {', '.join(models) or '?'} · {len(running)}/{len(shown)} running{more}",
             color_of(shown[0]["model"]),
             {"progress": finished / len(shown), "live": bool(running)}, type_="group")
        for i, s in enumerate(shown):
            r, c = divmod(i, cols)
            x = fx + GROUP_PAD + c * (cw + GROUP_PAD)
            cy = y + GROUP_HEAD + r * (CARD_H + GROUP_PAD)
            live = s["status"] == "running"
            end = s["ended"] or s["updated"]
            time_ = dur(now - (s["started"] or now)) if live else (dur(end - s["started"]) if s["started"] and end else "")
            node(f"agent-{s['id']}", "agent", x, cy, cw, CARD_H,
                 f"**{s['name']}** · {model_name(s['model'])}\n{s['detail'] or s['type']}\n\n"
                 f"{s['status']} · {plural(s['tools'], 'tool call')} · {time_}"
                 + (f" · {plural(s.get('errors', 0), 'error')}" if s.get("errors") else "")
                 + (f"\n`{s['last_tool']}`" if live and s["last_tool"] else ""),
                 color_of(s["model"]),
                 {**s, "time": time_, "iters": s["tools"], "slots": SLOTS, "last_iter": last_iter(s),
                  "live": live, "done": not live, "errors_in_row": s.get("errors_in_row", 0)})
        fill = lambda s: 1.0 if s["status"] != "running" else min(1.0, s["tools"] / SLOTS)
        if rows == 1:  # one row: wire each card straight to the lead, like a fan-out
            for s in shown:
                edge("lead", "bottom", f"agent-{s['id']}", "top", None, color_of(s["model"]),
                     live=s["status"] == "running", progress=fill(s), error=s.get("errors_in_row", 0) > 0,
                     msgs=msgs_for(s, "spawn", f"task → {s['name']}"))
        else:
            edge("lead", "bottom", "subagents", "top", "delegate", color_of(shown[0]["model"]),
                 live=bool(running), progress=sum(fill(s) for s in shown) / len(shown),
                 msgs=[m for s in shown for m in msgs_for(s, "spawn", f"task → {s['name']}")])
        targets["error"] = "subagents"
        y += gh + GAP

        # -- back to the lead ---------------------------------------------------------------
        waiting = [s for s in this_turn if s["status"] == "running"]
        back = bool(this_turn) and not waiting and working
        sub_text = (f"waiting on {plural(len(waiting), 'subagent')}" if waiting
                    else "review + verify" if back else "results delivered" if this_turn else "no subagents this turn")
        rw = min(FW, 260)
        returned = (len(this_turn) - len(waiting)) / len(this_turn) if this_turn else 0
        node("return", "return", fx + (FW - rw) / 2, y, rw, 54,
             f"**back to {model_name(L['model'])} · lead**\n{sub_text}", color_of(L["model"]),
             {"active": back, "line": sub_text, "model": L["model"], "progress": returned, "live": back})
        if rows == 1:
            for s in shown:
                edge(f"agent-{s['id']}", "bottom", "return", "top", None, color_of(s["model"]),
                     progress=1.0 if s["status"] != "running" else 0.0, live=back,
                     msgs=msgs_for(s, "return", f"result ← {s['name']}"))
        else:
            edge("subagents", "bottom", "return", "top", "results", color_of(L["model"]), progress=returned, live=back,
                 msgs=[m for s in shown for m in msgs_for(s, "return", f"result ← {s['name']}")])
        targets["done"] = "return"
        y += 54 + 18
    else:
        targets["error"] = targets["done"] = "lead"

    # -- session log ------------------------------------------------------------------------
    log = d["log"][-10:]
    lines = []
    for e in log:
        who = e.get("who") or "lead"
        if who == "lead":
            who = model_name(A.get("model")) if e["kind"] in ("advisor", "advice") else "lead"
        lines.append(f"{clock(e['ts'])}  {who:<8} {e['text']}")
    node("log", "log", fx, y, FW, 30 + 15 * max(1, len(log)),
         "session log\n```\n" + ("\n".join(lines) or "nothing yet") + "\n```", None,
         {"rows": [dict(e, model=e.get("model") or (A.get("model") if e["kind"] in ("advisor", "advice") else L["model"])) for e in log]})
    y += 30 + 15 * max(1, len(log))

    # -- advisor column (wide): a group with a header card and one node per checkpoint,
    #    each sitting level with the stage it advises and wired to it ----------------------
    if wide:
        c = color_of(A["model"])
        node("advisor-col", "group", 0, 0, ADV_W, y, f"{model_name(A['model'])} · advisor", c,
             {"live": bool(A.get("consulting")), "progress": 0}, type_="group")
        node("advisor", "advisor", 8, GROUP_HEAD, ADV_W - 16, head_h,
             f"**{model_name(A['model'])} · advisor**\n{line}" + (f"\n\n» {advice}" if advice else ""), c, adv_extra)
        by_id = {n["id"]: n for n in nodes}
        floor = GROUP_HEAD + head_h + 12
        for k, label in CHECKPOINTS:
            tgt = by_id[targets[k]]
            cy = max(floor, tgt["y"] + tgt["height"] / 2 - 21)
            n = cps.get(k, {}).get("count", 0)
            fired = hot(k) or (A.get("consulting") and last_kind == k)
            node(f"cp-{k}", "checkpoint", 8, cy, ADV_W - 16, 42,
                 f"{'◆' if fired else '◇'} {label}" + (f" · {n}×" if n else ""), c,
                 {"kind_of": k, "label": label, "count": n, "fired": fired, "last_ts": cps.get(k, {}).get("last_ts")})
            edge(f"cp-{k}", "right", targets[k], "left", None, c, dashed=True, live=fired, progress=1.0 if n else 0.0,
                 msgs=adv_msgs(k))
            floor = cy + 42 + 8

    return {
        "nodes": nodes,
        "edges": edges,
        "x-herdr": {
            "now": now, "terminal": d["terminal"], "width": W, "wide": wide,
            "session": S, "lead_model": L["model"], "advisor": {k: A.get(k) for k in ("model", "calls", "consulting", "present")},
            "subagents": {"running": len(running), "total": len(subs)},
        },
    }
