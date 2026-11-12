// pi-subagents: a right-side panel listing pi-subagents async runs (live first).
// Data: ./scan.py reads <tmp>/pi-subagents-uid-<uid>/async-subagent-runs/*/status.json (read-only).
// Click a run to expand it; "Follow log" opens `tail -f` of its output beside the focused pane.

import { View, div, svg } from "gpui-kit";
import { v_flex, h_flex } from "gpui-base";
import { exec, watchFolder, appHome, run, theme, layout } from "herdr";

const NODE = "subagents";
const RAIL = 40;
function find(node, id) {
  if (node?.id === id) return node;
  for (const c of node?.children ?? []) { const f = find(c, id); if (f) return f; }
  return null;
}
// Collapsed goes by width, so dragging the edge narrow collapses it too.
const width = () => find(layout(), NODE)?.size?.px ?? 340;
const collapsed = () => width() < 120;
function toggle() {
  if (collapsed()) run("layout.resize", { id: NODE, px: Number(localStorage.getItem("width")) || 340 });
  else { localStorage.setItem("width", String(width())); run("layout.resize", { id: NODE, px: RAIL }); }
}

const LIVE = new Set(["running", "queued"]);
const COLOR = { running: "working", queued: "working", complete: "done", failed: "blocked", error: "blocked", partial: "blocked", rejected: "blocked", stopped: "idle", paused: "idle" };
const SPIN = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

function dur(ms) {
  if (!(ms >= 0)) return "";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h ${m % 60}m` : `${Math.floor(h / 24)}d`;
}
const ago = (ms) => (ms >= 0 ? `${dur(ms).split(" ")[0]} ago` : "");
const kfmt = (n) => (n == null ? "" : n >= 1000 ? `${(n / 1000).toFixed(1)}k tok` : `${n} tok`);

export default class PiSubagents extends View {
  init(_props, cx) {
    this.data = { runs: [] };
    this.raw = "";
    this.err = "";
    this.open = new Set();
    this.showDone = true;
    this.busy = false;
    this.ticks = 0;
    this.refresh(cx);
    // Data timer: every 2 s while something runs (elapsed time, progress), every 10 s otherwise.
    cx.timer.every(2000, (cx) => {
      this.ticks++;
      if (this.live() > 0 || this.ticks % 5 === 0) this.refresh(cx);
    });
    // Instant pickup of new runs / status writes.
    cx.spawn(async (cx) => {
      const root = this.data.root;
      for (;;) {
        try { await watchFolder(this.data.root ?? root ?? "/tmp"); } catch { return; }
        this.refresh(cx);
      }
    });
  }

  live() {
    return this.data.runs.filter((r) => LIVE.has(r.state)).length;
  }

  refresh(cx) {
    if (this.busy) return;
    this.busy = true;
    cx.spawn(async (cx) => {
      try {
        const r = await exec("python3", [`${appHome()}/mods/pi-subagents/scan.py`]);
        if (r.stdout && r.stdout !== this.raw) {
          this.raw = r.stdout;
          this.data = JSON.parse(r.stdout);
          this.err = "";
          cx.notify();
        } else if (!r.stdout && r.stderr && this.err !== r.stderr) {
          this.err = r.stderr.trim().split("\n").pop();
          cx.notify();
        }
      } catch (e) {
        this.err = String(e?.message ?? e);
        cx.notify();
      }
      this.busy = false;
    });
  }

  follow(r) {
    if (!r.log) return;
    run("terminal.open", { argv: ["tail", "-n", "200", "-F", r.log], place: "right", name: `log ${r.id.slice(0, 8)}` });
  }

  badge(t, state) {
    const c = t[COLOR[state] ?? "unknown"] ?? t.dim;
    return div().flex_none().px(6).h(18).rounded(5).bg(c + "26").text_size(10.5).font_semibold().text_color(c)
      .flex().items_center().child(state || "?");
  }

  stepBlock(t, r, s, i) {
    const now = Date.now();
    const end = s.endedAt ?? (LIVE.has(r.state) ? now : r.endedAt);
    const meta = [s.model, s.startedAt ? dur(end - s.startedAt) : "", kfmt(s.tokens), s.cost ? `$${s.cost.toFixed(3)}` : ""].filter(Boolean).join(" · ");
    return v_flex().gap(2).pl(10).border_l(1.5).border_color(t.input).mt(4)
      .child(h_flex().gap(6).items_center()
        .child(div().text_size(12).font_medium().text_color(t.foreground).child(s.label ? `${s.agent} · ${s.label}` : s.agent))
        .child(div().flex_1())
        .when(r.mode !== "single", (el) => el.child(this.badge(t, s.status))))
      .when(Boolean(s.task), (el) => el.child(div().text_size(11.5).text_color(t.muted).whitespace_normal().child(s.task)))
      .when(Boolean(meta), (el) => el.child(div().text_size(10.5).text_color(t.dim).child(meta)))
      .when(s.tools.length > 0, (el) => el.child(v_flex().mt(2).children(s.tools.map((x, j) =>
        div().id(`tool-${r.id}-${i}-${j}`).text_size(10.5).font_family("monospace").text_color(t.dim).truncate().child(`▸ ${x}`)))))
      .when(s.output.length > 0, (el) => el.child(v_flex().mt(2).p(6).rounded(6).bg(t.background).children(s.output.map((x, j) =>
        div().id(`out-${r.id}-${i}-${j}`).text_size(10.5).font_family("monospace").text_color(t.muted).truncate().child(x)))))
      .when(Boolean(s.error) && s.error !== r.error, (el) => el.child(div().text_size(11).text_color(t.blocked).child(s.error)));
  }

  runRow(t, r) {
    const now = Date.now();
    const isLive = LIVE.has(r.state);
    const open = this.open.has(r.id);
    const agents = [...new Set(r.steps.map((s) => s.agent))];
    const name = r.mode === "workflow" ? `workflow · ${r.steps.length} agent${r.steps.length === 1 ? "" : "s"}` : agents.join(" → ") || r.mode;
    const first = r.steps[0];
    const sub = r.mode === "workflow" ? r.steps.map((s) => s.label || s.agent).join(", ") : first?.task ?? "";
    const when = isLive ? dur(now - (r.startedAt ?? now)) : ago(now - (r.endedAt ?? r.lastUpdate));
    const tool = isLive ? r.steps.find((s) => LIVE.has(s.status))?.tools?.slice(-1)[0] ?? "" : "";

    return v_flex().id(`run-${r.id}`).flex_none().px(10).py(8).rounded(8).gap(2)
      .bg(open ? t.raised : t.chrome)
      .border(1).border_color(isLive ? t.working + "55" : t.border)
      .hover((s) => s.bg(t.hover))
      .cursor_pointer()
      .on_click((_e, cx) => { open ? this.open.delete(r.id) : this.open.add(r.id); cx.notify(); })
      .child(h_flex().gap(6).items_center()
        .when(isLive, (el) => el.child(div().w(12).flex_none().text_color(t.working).frames(SPIN, 90)))
        .child(div().flex_1().min_w(0).truncate().text_size(12.5).font_semibold().text_color(isLive ? t.foreground : t.muted).child(name))
        .child(div().flex_none().text_size(10.5).text_color(t.dim).child(when))
        .child(this.badge(t, r.state)))
      .when(Boolean(sub) && !open, (el) => el.child(div().text_size(11.5).text_color(t.dim).truncate().child(sub)))
      .when(Boolean(tool) && !open, (el) => el.child(div().text_size(10.5).font_family("monospace").text_color(t.muted).truncate().child(`▸ ${tool}`)))
      .when(open, (el) => el
        .children(r.steps.map((s, i) => this.stepBlock(t, r, s, i)))
        .when(Boolean(r.error), (el) => el.child(div().mt(4).text_size(11).text_color(t.blocked).whitespace_normal().child(r.error)))
        .child(h_flex().mt(6).gap(6).items_center()
          .child(div().flex_1().text_size(10).font_family("monospace").text_color(t.dim).truncate().child(r.id.slice(0, 8)))
          .when(Boolean(r.log), (el) => el.child(
            h_flex().id(`log-${r.id}`).px(8).h(22).rounded(6).items_center().bg(t.surface).border(1).border_color(t.border)
              .text_size(11).text_color(t.foreground).hover((s) => s.bg(t.hover))
              .cursor_pointer()
              .on_click((_e, cx) => { cx.stop_propagation(); this.follow(r); })
              .child("Follow log")))));
  }

  rail(t, live, done) {
    const failed = done.filter((r) => COLOR[r.state] === "blocked").length;
    return v_flex().id("root").size_full().bg(t.chrome).items_center().pt(8).gap(8)
      .child(div().id("expand").size(26).rounded(6).flex().items_center().justify_center().cursor_pointer()
        .text_size(13).text_color(t.muted).hover((s) => s.bg(t.hover).text_color(t.foreground))
        .on_click(() => toggle()).child("«"))
      .child(div().id("rail-body").flex_1().w_full().flex().flex_col().items_center().gap(6).cursor_pointer()
        .on_click(() => toggle())
        .when(live.length > 0, (el) => el
          .child(div().text_color(t.working).frames(SPIN, 90))
          .child(div().px(5).h(18).rounded(5).bg(t.working + "26").text_size(10.5).font_semibold().text_color(t.working)
            .flex().items_center().child(String(live.length))))
        .when(failed > 0, (el) => el.child(div().px(5).h(18).rounded(5).bg(t.blocked + "26").text_size(10.5).font_semibold()
          .text_color(t.blocked).flex().items_center().child(`!${failed}`)))
        .when(live.length === 0, (el) => el.child(div().text_size(10.5).text_color(t.dim).child(String(done.length)))));
  }

  render(cx) {
    const t = theme();
    const runs = this.data.runs ?? [];
    const live = runs.filter((r) => LIVE.has(r.state));
    const done = runs.filter((r) => !LIVE.has(r.state));
    if (collapsed()) return this.rail(t, live, done);
    const shown = this.showDone ? [...live, ...done] : live;

    const header = h_flex().h(36).px(12).flex_none().items_center().gap(8)
      .child(div().text_size(12).font_semibold().text_color(t.foreground).child("Subagents"))
      .when(live.length > 0, (el) => el.child(div().px(6).h(18).rounded(5).bg(t.working + "26").text_size(10.5).font_semibold()
        .text_color(t.working).flex().items_center().child(`${live.length} running`)))
      .child(div().flex_1())
      .child(h_flex().id("toggle-done").px(8).h(22).rounded(6).items_center().text_size(11)
        .text_color(this.showDone ? t.foreground : t.dim).hover((s) => s.bg(t.hover))
        .cursor_pointer()
        .on_click((_e, cx) => { this.showDone = !this.showDone; cx.notify(); })
        .child(this.showDone ? `Finished (${done.length})` : `Finished hidden`))
      .child(div().id("collapse").size(22).rounded(6).flex().items_center().justify_center().cursor_pointer()
        .text_size(13).text_color(t.muted).hover((s) => s.bg(t.hover).text_color(t.foreground))
        .on_click(() => toggle()).child("»"));

    const empty = div().px(14).py(10).text_size(12).text_color(t.dim).whitespace_normal()
      .child(this.err ? `Scan failed: ${this.err}` : live.length === 0 && runs.length > 0 ? "Nothing running." : "No subagent runs in the last 24 h. Background (async) pi-subagents runs show up here.");

    return v_flex().id("root").size_full().bg(t.chrome).text_color(t.foreground)
      .child(header)
      .child(div().h(1).flex_none().bg(t.border))
      .child(shown.length === 0
        ? empty
        : v_flex().id("runs").flex_1().min_h(0).p(8).gap(6).overflow_y_scrollbar().children(shown.map((r) => this.runRow(t, r))));
  }
}
