// claude-subagents: a Claude Code session as a JSON Canvas, drawn live.
//
// ./scan.py lays the session out as a JSON Canvas 1.0 document (jsoncanvas.org) sized for
// this panel's width: advisor ┄▸ lead ─▸ subagents ─▸ back to lead, plus a session log.
// A copy is kept at ~/.cache/herdr-claude-subagents/<session>.canvas.
//
// This file is a small canvas viewer: it draws any canvas's nodes (text as Markdown,
// groups with their label) and edges (curves with arrows, labels). Nodes from scan.py also
// carry "x-herdr" data, drawn as richer widgets: spinners, effort meter, progress bars.
// Click a subagent card to follow its transcript beside the focused pane.

import { View, div, PathBuilder } from "gpui-kit";
import { v_flex, h_flex, TextView } from "gpui-base";
import { exec, appHome, run, theme, agents, focused, terminals } from "herdr";

const SPIN = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const MONO = "JetBrains Mono";
const PAD = 12;
const CHECKS = [["plan", "plan"], ["error", "error ×2"], ["done", "done"]];

// ------------------------------------------------------------------ helpers

/** JSON Canvas colors: presets "1".."6" (red, orange, yellow, green, cyan, purple) or hex. */
function canvasColor(t, c, fallback) {
  if (!c) return fallback;
  if (c.startsWith("#")) return c;
  return { 1: t.ansi1, 2: t.ansi3, 3: t.ansi11, 4: t.ansi2, 5: t.ansi6, 6: t.ansi5 }[c] ?? fallback;
}
function modelName(id) {
  const m = String(id || "").replace(/^claude-/, "").match(/^([a-z]+)(?:-(\d+))?(?:-(\d+))?/i);
  if (!m) return id || "?";
  const fam = m[1][0].toUpperCase() + m[1].slice(1);
  return m[2] ? `${fam} ${m[2]}${m[3] ? "." + m[3] : ""}` : fam;
}
/** The name of a subagent's log pane: unique and stable, so a click finds the pane it opened. */
/** The log pane's terminal name. Core names allow 1-32 of a-z 0-9 - _ . and must be
 *  unique among live terminals, which is what makes the toggle's lookup exact. */
const logName = (s) => {
  const slug = String(s.name || "agent").toLowerCase().replace(/[^a-z0-9_.-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 18) || "agent";
  return `log-${slug}-${String(s.id).replace(/[^a-z0-9]/gi, "").slice(-6).toLowerCase()}`;
};
const family = (id) => ["opus", "sonnet", "haiku", "fable", "mythos"].find((f) => String(id || "").toLowerCase().includes(f)) ?? "other";
const modelColor = (t, id) => canvasColor(t, { opus: "6", sonnet: "2", haiku: "5", fable: "4", mythos: "4" }[family(id)] ?? "3", t.muted);
/** A color at `a` (0..1) opacity: #rgb, #rrggbb and #rrggbbaa (alpha multiplied) all work. */
function alpha(c, a) {
  let h = String(c || "").replace("#", "");
  if (h.length === 3 || h.length === 4) h = [...h].map((x) => x + x).join("");
  if (!/^[0-9a-f]{6}([0-9a-f]{2})?$/i.test(h)) return c;
  const base = h.length === 8 ? parseInt(h.slice(6), 16) / 255 : 1;
  return "#" + h.slice(0, 6) + Math.round(Math.max(0, Math.min(1, base * a)) * 255).toString(16).padStart(2, "0");
}
const kfmt = (n) => (!n ? "0" : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1000 ? `${Math.round(n / 1000)}k` : String(n));
const clock = (ms) => {
  const d = new Date(ms);
  return [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, "0")).join(":");
};

/** Where an edge leaves or enters a node side, and which way is "out". */
function anchor(n, side) {
  const cx = n.x + n.width / 2, cy = n.y + n.height / 2;
  return {
    top: [cx, n.y, 0, -1], bottom: [cx, n.y + n.height, 0, 1],
    left: [n.x, cy, -1, 0], right: [n.x + n.width, cy, 1, 0],
  }[side] ?? [cx, cy, 0, 0];
}

// ------------------------------------------------------------------ geometry

const VERT = { top: true, bottom: true };

/** An orthogonal (elbow) route between two node sides, like a wiring diagram. */
function route(a, fromSide, b, toSide, ox, oy) {
  const [x1, y1] = anchor(a, fromSide), [x2, y2] = anchor(b, toSide);
  const P1 = [x1 - ox, y1 - oy], P2 = [x2 - ox, y2 - oy];
  const v1 = Boolean(VERT[fromSide]), v2 = Boolean(VERT[toSide]);
  if (v1 && v2) { const ym = (P1[1] + P2[1]) / 2; return [P1, [P1[0], ym], [P2[0], ym], P2]; }
  if (!v1 && !v2) { const xm = (P1[0] + P2[0]) / 2; return [P1, [xm, P1[1]], [xm, P2[1]], P2]; }
  return v1 ? [P1, [P1[0], P2[1]], P2] : [P1, [P2[0], P1[1]], P2];
}
function edgeRoute(e, a, b, ox, oy) {
  const below = b.y > a.y + a.height;
  return route(a, e.fromSide ?? (below ? "bottom" : "right"), b, e.toSide ?? (below ? "top" : "left"), ox, oy);
}
function origin(doc) {
  const nodes = doc.nodes ?? [];
  return [Math.min(0, ...nodes.map((n) => n.x)), Math.min(0, ...nodes.map((n) => n.y))];
}
const PACKET_SPEED = 0.32; // px per ms
const segLen = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1]);
const polyLen = (pts) => pts.slice(1).reduce((n, p, i) => n + segLen(pts[i], p), 0);
/** The first `f` (0..1) of a polyline, by length. */
function polyPart(pts, f) {
  let left = polyLen(pts) * Math.max(0, Math.min(1, f));
  const out = [pts[0]];
  for (let i = 1; i < pts.length && left > 0; i++) {
    const l = segLen(pts[i - 1], pts[i]);
    if (l <= left) { out.push(pts[i]); left -= l; continue; }
    const k = left / l;
    out.push([pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * k, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * k]);
    left = 0;
  }
  return out;
}
const pointAt = (pts, f) => polyPart(pts, f).slice(-1)[0];
function strokeOf(pts, width, dash) {
  let p = PathBuilder.stroke(width).move_to(pts[0][0], pts[0][1]);
  for (const q of pts.slice(1)) p = p.line_to(q[0], q[1]);
  if (dash) p = p.dash_array(dash);
  return p.build();
}
/** A rounded-rectangle outline as a polyline, clockwise from the top centre. */
function perimeter(w, h, r, inset) {
  const i = inset, R = Math.max(0, r - i), pts = [[w / 2, i]];
  const arc = (cx, cy, a0) => { for (let k = 1; k <= 6; k++) { const a = a0 + (Math.PI / 2) * (k / 6); pts.push([cx + R * Math.cos(a), cy + R * Math.sin(a)]); } };
  pts.push([w - i - R, i]); arc(w - i - R, i + R, -Math.PI / 2);
  pts.push([w - i, h - i - R]); arc(w - i - R, h - i - R, 0);
  pts.push([i + R, h - i]); arc(i + R, h - i - R, Math.PI / 2);
  pts.push([i, i + R]); arc(i + R, i + R, Math.PI);
  pts.push([w / 2, i]);
  return pts;
}

// ------------------------------------------------------------------ the mod

export default class ClaudeSubagents extends View {
  init(_props, cx) {
    this.doc = null;
    this.raw = "";
    this.err = "";
    this.busy = false;
    this.addr = null;
    this.width = 0;
    this.ticks = 0;
    this.seen = new Set();   // messages already sent down their edge
    this.packets = [];       // messages travelling now: {id, pts, step, text, color, fading}
    this.primed = false;     // the first scan only marks what's there as seen
    this.pid = 0;
    this.refresh(cx);
    cx.timer.every(1500, (cx) => {
      this.ticks++;
      if (this.hot() || this.ticks % 4 === 0) this.refresh(cx);
    });
  }

  meta() {
    return this.doc?.["x-herdr"] ?? {};
  }

  hot() {
    const m = this.meta();
    return m.session?.state === "working" || (m.subagents?.running ?? 0) > 0;
  }

  /** The Claude agent to follow: focused, else the one already shown, else the first here. */
  pick() {
    const claude = agents().filter((a) => a.app === "claude-code" && !a.address.includes("/"));
    const f = focused();
    const byFocus = claude.find((a) => a.address === f?.terminal || a.address === f?.agent);
    if (byFocus) return byFocus.address;
    if (claude.some((a) => a.address === this.addr)) return this.addr;
    return (claude.find((a) => a.space === f?.space) ?? claude[0])?.address ?? null;
  }

  canvasWidth() {
    return Math.max(220, Math.floor((this.width || 400) - 2 * PAD));
  }

  refresh(cx) {
    if (this.busy) return;
    this.busy = true;
    const addr = this.pick();
    const width = this.canvasWidth();
    cx.spawn(async (cx) => {
      try {
        const args = [`${appHome()}/mods/claude-subagents/scan.py`, "--width", String(width)];
        if (addr) args.push("--terminal", addr);
        const r = await exec("python3", args);
        if (r.stdout && (r.stdout !== this.raw || addr !== this.addr)) {
          this.raw = r.stdout;
          this.doc = JSON.parse(r.stdout);
          this.addr = addr;
          this.launch(cx);
          this.err = "";
          cx.notify();
        } else if (!r.stdout && r.stderr) {
          this.err = r.stderr.trim().split("\n").pop();
          cx.notify();
        }
      } catch (e) {
        this.err = (e instanceof Error ? e.message : String(e));
        cx.notify();
      }
      this.busy = false;
    });
  }

  /** The live log pane of a subagent, or null. tail.py ends itself (and its pane) after the
   *  subagent finishes, so a finished subagent's pane is simply not found. */
  /** This subagent's open log panes, found by what they run (tail.py + its transcript):
   *  herdr doesn't carry terminal.open's name onto the core terminal, so names can't be used. */
  logPanes(s) {
    return terminals().filter((t) => t.state === "live" && Array.isArray(t.argv)
      && t.argv.includes(s.transcript) && t.argv.some((a) => String(a).endsWith("/tail.py")));
  }

  logPane(s) {
    return this.logPanes(s)[0] ?? null;
  }

  /** Toggle: a click closes this subagent's log pane(s) if any is open, else opens one. */
  follow(s) {
    const open = this.logPanes(s);
    if (open.length) {
      for (const t of open) run("terminal.kill", { terminal: t.address });
      return;
    }
    run("terminal.open", {
      argv: ["python3", "-u", `${appHome()}/mods/claude-subagents/tail.py`, s.transcript],
      place: "right", name: logName(s),
    });
  }

  // ---------------------------------------------------------------- edges

  // ---------------------------------------------------------------- messages

  /** New messages on any edge become packets: a dot with the message's label that rides
   *  its edge once, corner to corner (native transitions), then fades. Nothing moves
   *  between messages. The first scan only marks existing messages as seen. */
  launch(cx) {
    const doc = this.doc;
    if (!doc?.nodes) return;
    const byId = Object.fromEntries(doc.nodes.map((n) => [n.id, n]));
    const [ox, oy] = origin(doc);
    const fresh = [];
    for (const e of doc.edges ?? []) {
      for (const m of e["x-herdr"]?.msgs ?? []) {
        const key = `${e.id}|${m.ts}|${m.text}`;
        if (this.seen.has(key)) continue;
        this.seen.add(key);
        const a = byId[e.fromNode], b = byId[e.toNode];
        if (!this.primed || !a || !b) continue;
        let pts = edgeRoute(e, a, b, ox, oy);
        if (m.rev) pts = pts.slice().reverse();
        fresh.push({ id: ++this.pid, pts, step: 0, text: m.text, color: e.color, error: e["x-herdr"]?.error, fading: false });
      }
    }
    this.primed = true;
    if (this.seen.size > 500) this.seen = new Set([...this.seen].slice(-250));
    for (const p of fresh.slice(-8)) {
      this.packets.push(p);
      cx.timer.after(30, (cx) => this.advance(p, cx));
    }
    if (fresh.length) cx.notify();
  }

  advance(p, cx) {
    if (p.step < p.pts.length - 1) {
      p.step++;
      cx.notify();
      const ms = Math.max(140, segLen(p.pts[p.step - 1], p.pts[p.step]) / PACKET_SPEED);
      cx.timer.after(ms + 20, (cx) => this.advance(p, cx));
    } else if (!p.fading) {
      p.fading = true;
      cx.notify();
      cx.timer.after(900, (cx) => { this.packets = this.packets.filter((q) => q !== p); cx.notify(); });
    }
  }

  packetLayer(t) {
    return this.packets.map((p) => {
      const [x, y] = p.pts[Math.min(p.step, p.pts.length - 1)];
      const prev = p.pts[Math.max(0, p.step - 1)];
      const ms = Math.max(140, segLen(prev, [x, y]) / PACKET_SPEED);
      const c = p.error ? t.blocked : canvasColor(t, p.color, t.accent);
      return h_flex().id(`pkt-${p.id}`).absolute().left(x - 4).top(y - 4).gap(5).items_center()
        .opacity(p.fading ? 0 : 1)
        .transition("left", { duration: ms, easing: "linear" })
        .transition("top", { duration: ms, easing: "linear" })
        .transition("opacity", { duration: 700, delay: 150 })
        .child(div().size(8).flex_none().rounded(4).bg(c).border(1).border_color(t.background))
        .child(div().h(15).px(5).rounded(4).bg(alpha(t.chrome, 0.92)).border(1).border_color(alpha(c, 0.5))
          .text_size(10).font_family(MONO).text_color(c).whitespace_nowrap().child(p.text));
    });
  }

  /** Edges: a dim full route and the part done drawn bright over it; errors turn the
   *  bright part red. Messages ride on top as packets (packetLayer). */
  edgeLayer(t, doc, ox, oy, W, H) {
    const byId = Object.fromEntries(doc.nodes.map((n) => [n.id, n]));
    const out = [];
    for (const e of doc.edges ?? []) {
      const a = byId[e.fromNode], b = byId[e.toNode];
      if (!a || !b) continue;
      const pts = edgeRoute(e, a, b, ox, oy);
      const xh = e["x-herdr"] ?? {};
      const c = xh.error ? t.blocked : canvasColor(t, e.color, t.muted);
      const prog = xh.progress ?? (xh.live ? 0.5 : 1);
      const dash = xh.dashed ? [3, 4] : null;
      const layer = (id, path, color) => div().id(id).absolute().left(0).top(0).w(W).h(H).child(window.paint_path(path, color));
      out.push(layer(`edge-base-${e.id}`, strokeOf(pts, 1.2, dash), alpha(c, xh.live ? 0.35 : 0.22)));
      if (prog > 0.01) {
        out.push(layer(`edge-fill-${e.id}`, strokeOf(polyPart(pts, prog), xh.live ? 2 : 1.5, dash), alpha(c, xh.live ? 1 : 0.75)));
      }
      if ((e.toEnd ?? "arrow") === "arrow") {
        const [X2, Y2] = pts[pts.length - 1], [Xp, Yp] = pts[pts.length - 2];
        const l = segLen([Xp, Yp], [X2, Y2]) || 1, ux = (X2 - Xp) / l, uy = (Y2 - Yp) / l, s = 4.5;
        const back = [X2 - ux * s * 1.6, Y2 - uy * s * 1.6];
        const head = PathBuilder.fill().add_polygon([[X2, Y2], [back[0] - uy * s, back[1] + ux * s], [back[0] + uy * s, back[1] - ux * s]], true).build();
        out.push(layer(`edge-head-${e.id}`, head, prog >= 0.999 ? c : alpha(c, 0.4)));
      }
      if (e.label) {
        const [mx, my] = pointAt(pts, 0.5);
        out.push(div().id(`elabel-${e.id}`).absolute().left(mx + 8).top(my - 8).h(16).px(5).rounded(4)
          .bg(t.chrome).text_size(10.5).text_color(xh.live ? c : t.muted).whitespace_nowrap().child(e.label));
      }
    }
    return out;
  }

  /** A node's border as its progress: one segment per iteration (tool call) clockwise from
   *  the top, the newest one blinking while it's fresh; laps leave the ring lit underneath.
   *  Finished: one solid ring. Continuous `progress` (groups, return box): a smooth arc. */
  ring(t, n, ox, oy) {
    const x = n["x-herdr"] ?? {};
    const iterative = typeof x.iters === "number";
    if (!iterative && typeof x.progress !== "number") return [];
    const c = canvasColor(t, n.color, t.accent);
    const w = n.width, h = n.height, per = perimeter(w, h, 8, 0.75), L = polyLen(per);
    const at = (id) => div().id(`ring-${id}-${n.id}`).absolute().left(n.x - ox).top(n.y - oy).w(w).h(h);
    const now = this.meta().now ?? 0;
    const heat = x.last_iter ? Math.max(0, 1 - (now - x.last_iter) / 8000) : 0;
    const out = [];
    if (iterative && x.done) {
      out.push(at("full").child(window.paint_path(strokeOf(per, 1.5), x.errors_in_row ? t.blocked : alpha(c, 0.9))));
      return out;
    }
    if (iterative) {
      const slots = x.slots || 24, laps = Math.floor(x.iters / slots), k = x.iters % slots;
      const slot = L / slots;
      if (laps > 0) out.push(at("lap").child(window.paint_path(strokeOf(per, 1.5), alpha(c, 0.45))));
      if (k > 0) {
        out.push(at("done").opacity(0.65 + 0.35 * heat)
          .child(window.paint_path(strokeOf(polyPart(per, k / slots), 2, [slot - 3, 3]), c)));
        // The newest iteration: red after an error, blinking while it's fresh.
        const tail = polyPart(per, k / slots), head = polyPart(per, (k - 1) / slots);
        const seg = [head[head.length - 1], ...tail.slice(head.length)];
        if (seg.length > 1) {
          out.push(at("new").when(heat > 0 && x.live, (el) => el.loop("opacity", { from: 0.35, to: 1, period: 700 }))
            .child(window.paint_path(strokeOf(seg, 2.5), x.errors_in_row ? t.blocked : c)));
        }
      }
      return out;
    }
    if (x.progress > 0.005) {
      out.push(at("arc")
        .child(window.paint_path(strokeOf(polyPart(per, x.progress), 1.8), c)));
    }
    return out;
  }

  // ---------------------------------------------------------------- nodes

  frame(t, n, ox, oy, color, active, strong = false) {
    return v_flex().id(`node-${n.id}`).absolute().left(n.x - ox).top(n.y - oy).w(n.width).h(n.height)
      .overflow_hidden().rounded(8).border(1)
      .border_color(alpha(color, strong ? 0.6 : active ? 0.35 : 0.25)).bg(active ? alpha(color, 0.08) : t.surface);
  }

  bar(t, frac, color, live) {
    const w = Math.max(0.04, Math.min(1, frac));
    return div().flex_1().h(7).rounded(3).bg(t.raised).overflow_hidden()
      .child(div().h_full().w(`${Math.round(w * 1000) / 10}%`).rounded(3).bg(color)
        .transition("width", 400));
  }

  row(t, k, v, vc) {
    return h_flex().gap(8)
      .child(div().w(72).flex_none().whitespace_nowrap().text_size(11).text_color(t.dim).child(k))
      .child(div().flex_1().min_w(0).truncate().text_size(11).font_family(MONO).text_color(vc ?? t.foreground).child(v));
  }

  lead(t, n, x, ox, oy) {
    const c = canvasColor(t, n.color, t.accent);
    const working = x.state === "working";
    return this.frame(t, n, ox, oy, c, working).px(12).py(9).gap(3)
      .child(h_flex().gap(6).items_center()
        .child(div().text_size(12.5).font_semibold().text_color(c).child(`${modelName(x.model)} · main session`))
        .child(div().flex_1())
        .when(working, (el) => el.child(div().text_size(11).text_color(t.working).frames(SPIN, 90)))
        .child(div().text_size(10.5).text_color(working ? t.working : t.dim).child(working ? x.elapsed || "working" : x.state || "idle")))
      .child(div().w_full().min_w(0).h(16).flex_none().whitespace_nowrap().truncate().text_size(11.5).text_color(t.foreground).child(x.activity || "—"))
      .when(x.effort_level > 0, (el) => el.child(h_flex().gap(8).items_center()
        .child(div().w(72).flex_none().text_size(11).text_color(t.dim).child("effort"))
        .child(h_flex().gap(2).children([1, 2, 3, 4, 5].map((i) => div().w(5).h(9).rounded(1).bg(i <= x.effort_level ? c : t.raised))))
        .child(div().text_size(11).font_family(MONO).text_color(c).child(x.effort))))
      .child(this.row(t, "tool calls", `${x.tools}  ${x.top_tools.map(([k, v]) => `${k} ${v}`).join(" · ")}`))
      .child(this.row(t, "context", `${kfmt(x.ctx)} · out ${kfmt(x.out_tokens)} · turn ${x.turns}`))
      .when(working && Boolean(x.last_tool), (el) => el.child(this.row(t, "last", x.last_tool, t.muted)));
  }

  advisor(t, n, x, ox, oy) {
    const c = canvasColor(t, n.color, t.ansi5);
    return this.frame(t, n, ox, oy, c, x.consulting).px(12).py(8).gap(2)
      .child(h_flex().gap(6).items_center()
        .child(div().text_size(12).font_semibold().text_color(c).child(`${modelName(x.model)} · advisor`))
        .when(x.consulting, (el) => el.child(div().text_size(11).text_color(c).frames(SPIN, 90)))
        .child(div().flex_1())
        .when(!x.wide, (el) => el.child(div().text_size(10.5).text_color(x.consulting ? c : t.dim).child(x.consulting ? "advising" : x.calls ? "silent" : "on call"))))
      .when(Boolean(x.wide), (el) => el.child(div().text_size(10.5).text_color(x.consulting ? c : t.dim).child(x.consulting ? "advising…" : x.calls ? "silent" : "on call")))
      .child(div().text_size(11).text_color(t.muted).whitespace_normal().child(x.line))
      .when(!x.wide, (el) => el.child(h_flex().gap(10).pt(2).children(CHECKS.map(([k, label]) => {
        const cp = x.checkpoints?.[k] ?? {}, fired = x.hot?.[k] || (x.consulting && x.last_kind === k);
        return div().id(`chip-${k}`).text_size(10.5).text_color(fired ? c : cp.count ? t.muted : t.dim)
          .when(fired, (d) => d.loop("opacity", { from: 0.5, to: 1, period: 900 }))
          .child(`${fired ? "◆" : "◇"} ${label}${cp.count ? ` ${cp.count}×` : ""}`);
      }))))
      .when(Boolean(x.advice), (el) => el.child(div().text_size(11).whitespace_normal().child(`» ${x.advice}`)));
  }

  checkpoint(t, n, x, ox, oy) {
    const c = canvasColor(t, n.color, t.ansi5);
    const ago = x.last_ts ? `${Math.round(((this.meta().now ?? 0) - x.last_ts) / 1000)}s ago` : "never";
    return div().id(`node-${n.id}`).absolute().left(n.x - ox).top(n.y - oy).w(n.width).h(n.height)
      .rounded(6).border(1).border_color(x.fired ? c : alpha(c, x.count ? 0.4 : 0.2))
      .bg(x.fired ? alpha(c, 0.16) : t.surface).px(9).flex().flex_col().justify_center()
      .child(h_flex().gap(6).items_center()
        .child(div().text_size(11).text_color(x.fired ? c : x.count ? t.foreground : t.dim)
          .when(x.fired, (d) => d.loop("opacity", { from: 0.45, to: 1, period: 900 })).child(x.fired ? "◆" : "◇"))
        .child(div().flex_1().text_size(11.5).font_semibold().text_color(x.fired ? c : x.count ? t.foreground : t.muted).child(x.label))
        .when(x.count > 0, (el) => el.child(div().text_size(10.5).font_family(MONO).text_color(c).child(`${x.count}×`))))
      .child(div().text_size(10).text_color(t.dim).child(x.count ? `last ${ago}` : "not yet"));
  }

  agent(t, n, x, ox, oy, now) {
    const c = canvasColor(t, n.color, t.accent);
    const live = x.status === "running";
    const st = { running: t.working, done: t.done, failed: t.blocked, stopped: t.idle }[x.status] ?? t.dim;
    const label = { done: "✓ done", failed: "✗ failed" }[x.status] ?? x.status;
    const open = Boolean(this.logPane(x));
    return this.frame(t, n, ox, oy, c, live, open).px(10).py(8).gap(4)
      .cursor_pointer().hover((s) => s.bg(t.hover))
      .on_click(() => this.follow(x))
      .child(h_flex().gap(6).items_center()
        .child(div().flex_1().min_w(0).truncate().text_size(12).font_semibold().child(x.name))
        .child(div().flex_none().text_size(10.5).text_color(c).child(modelName(x.model))))
      .child(h_flex().gap(6).items_center()
        .child(this.bar(t, x.done ? 1 : Math.min(1, x.iters / (x.slots || 24)), x.errors_in_row ? t.blocked : c, live))
        .child(div().flex_none().text_size(10.5).font_family(MONO).text_color(t.muted).child(`${x.tools} call${x.tools === 1 ? "" : "s"}`)))
      .child(div().text_size(11).text_color(t.muted).truncate().child(x.detail || x.type))
      .when(live && Boolean(x.last_tool), (el) => el.child(div().text_size(10.5).font_family(MONO).text_color(t.dim).truncate().child(`▸ ${x.last_tool}`)))
      .child(h_flex().gap(5).items_center()
        .when(live, (el) => el.child(div().text_size(10.5).text_color(st).frames(SPIN, 90)))
        .child(div().text_size(10.5).text_color(st).child(label))
        .child(div().flex_1())
        .child(div().text_size(10.5).text_color(t.dim).child([x.time, `${kfmt(x.out_tokens)} out`].filter(Boolean).join(" · ")))
        .when(open, (el) => el.child(div().flex_none().text_size(10.5).font_semibold().text_color(c).child("◉ log"))));
  }

  ret(t, n, x, ox, oy) {
    const c = canvasColor(t, n.color, t.border);
    return this.frame(t, n, ox, oy, x.active ? c : t.border, x.active).items_center().justify_center()
      .child(div().text_size(12).font_semibold().text_color(x.active ? c : t.muted).child(`back to ${modelName(x.model)} · lead`))
      .child(div().text_size(11).text_color(x.active ? t.foreground : t.dim).child(x.line));
  }

  log(t, n, x, ox, oy) {
    const tone = { spawn: t.accent, return: t.done, advisor: t.ansi5, advice: t.ansi5, prompt: t.foreground };
    const verb = { spawn: "→ ", return: "← ", prompt: "› " };
    return v_flex().id(`node-${n.id}`).absolute().left(n.x - ox).top(n.y - oy).w(n.width).h(n.height)
      .overflow_hidden().rounded(8).border(1).border_color(t.border).bg(t.background).px(10).pt(6).gap(1)
      .child(div().text_size(10.5).text_color(t.dim).pb(3).child("session log"))
      .when(x.rows.length === 0, (el) => el.child(div().text_size(11).text_color(t.dim).child("nothing yet")))
      .children(x.rows.map((e, i) => h_flex().id(`log-${i}`).h(14).gap(7).text_size(10.5).font_family(MONO)
        .child(div().flex_none().text_color(t.dim).child(clock(e.ts)))
        .child(div().flex_none().w(52).truncate().font_semibold().text_color(modelColor(t, e.model))
          .child(e.who === "lead" ? (e.kind === "advisor" || e.kind === "advice" ? modelName(e.model) : "lead") : e.who))
        .child(div().flex_1().min_w(0).truncate().text_color(tone[e.kind] ?? t.muted).child(`${verb[e.kind] ?? ""}${e.text}`))));
  }

  /** Any JSON Canvas node: groups get their label, text nodes Markdown, others their name. */
  generic(t, n, ox, oy) {
    const c = canvasColor(t, n.color, t.border);
    const base = div().id(`node-${n.id}`).absolute().left(n.x - ox).top(n.y - oy).w(n.width).h(n.height).rounded(8);
    if (n.type === "group") {
      return base.border(1).border_color(alpha(c, 0.33)).bg(alpha(c, 0.05)).px(10).pt(5)
        .child(div().text_size(10.5).text_color(c).truncate().child(n.label ?? ""));
    }
    const body = n.type === "text" ? TextView.markdown(`md-${n.id}`, n.text ?? "")
      : div().text_size(11.5).child(n.type === "file" ? n.file : n.type === "link" ? n.url : n.type);
    return base.overflow_hidden().border(1).border_color(c).bg(t.surface).p(8).child(body);
  }

  node(t, n, ox, oy, now) {
    const x = n["x-herdr"];
    switch (x?.kind) {
      case "lead": return this.lead(t, n, x, ox, oy);
      case "advisor": return this.advisor(t, n, x, ox, oy);
      case "agent": return this.agent(t, n, x, ox, oy, now);
      case "return": return this.ret(t, n, x, ox, oy);
      case "log": return this.log(t, n, x, ox, oy);
      case "checkpoint": return this.checkpoint(t, n, x, ox, oy);
      default: return this.generic(t, n, ox, oy);
    }
  }

  // ---------------------------------------------------------------- render

  render(_cx) {
    const t = theme();
    const doc = this.doc;
    const m = this.meta();
    const root = v_flex().id("root").size_full().bg(t.chrome).text_color(t.foreground)
      .on_size_change((size, cx) => {
        const had = this.width;
        this.width = size.width;
        // Re-lay the canvas for the new width (scan.py sizes it to the panel).
        if (Math.abs(had - size.width) > 1) { this.refresh(cx); cx.notify(); }
      });

    if (!doc || !m.session) {
      return root.child(div().p(14).text_size(12).text_color(t.dim).whitespace_normal()
        .child(this.err ? `Scan failed: ${this.err}` : "No Claude Code session found. Start `claude` in a Herdr terminal and focus it."));
    }

    const nodes = doc.nodes ?? [];
    const ox = Math.min(0, ...nodes.map((n) => n.x)), oy = Math.min(0, ...nodes.map((n) => n.y));
    const W = Math.max(0, ...nodes.map((n) => n.x + n.width)) - ox;
    const H = Math.max(0, ...nodes.map((n) => n.y + n.height)) - oy;
    // Groups first, so they sit behind the nodes inside them; edges under everything else.
    const groups = nodes.filter((n) => n.type === "group");
    const rest = nodes.filter((n) => n.type !== "group");

    const plane = div().id("plane").relative().w(W).h(H).flex_none()
      .children(groups.map((n) => this.generic(t, n, ox, oy)))
      .children(this.edgeLayer(t, doc, ox, oy, W, H))
      .children(groups.flatMap((n) => this.ring(t, n, ox, oy)))
      .children(rest.map((n) => this.node(t, n, ox, oy, m.now)))
      .children(rest.flatMap((n) => this.ring(t, n, ox, oy)))
      .children(this.packetLayer(t));

    const S = m.session, A = m.advisor ?? {}, subs = m.subagents ?? { running: 0, total: 0 };
    const item = (k, v, c) => h_flex().gap(4).flex_none().child(div().text_color(t.dim).child(k)).child(div().text_color(c).child(`[${v}]`));

    return root
      .child(h_flex().h(34).px(PAD).flex_none().items_center().gap(8)
        .child(div().text_size(12).font_semibold().child("Claude"))
        .child(div().flex_1().min_w(0).truncate().text_size(11).text_color(t.dim)
          .child([S.title || S.name, m.terminal].filter(Boolean).join(" · "))))
      .child(div().h(1).flex_none().bg(t.border))
      .child(v_flex().id("scroll").flex_1().min_h(0).overflow_y_scrollbar().p(PAD).child(plane))
      .child(h_flex().h(26).px(PAD).flex_none().gap(12).items_center().text_size(10.5).font_family(MONO)
        .border_t(1).border_color(t.border).overflow_hidden()
        .child(item(family(m.lead_model), S.state || "idle", S.state === "working" ? t.working : t.muted))
        .child(item("subagents", `${subs.running}/${subs.total}`, subs.running ? t.working : t.muted))
        .when(Boolean(A.model && A.present), (el) => el.child(item(family(A.model), A.consulting ? "advising" : `${A.calls}×`, modelColor(t, A.model)))));
  }
}
