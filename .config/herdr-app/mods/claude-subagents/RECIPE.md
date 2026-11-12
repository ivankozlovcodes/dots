# Claude Subagents

A side panel that draws the Claude Code session in the focused Herdr terminal as a live picture. The main session sits at the top, its advisor above it (or in a column on the left when the panel is wide), its subagents as cards in a grid, a "back to lead" box below them, and the last 10 session events at the bottom. When the advisor is present, its checkpoints (before a plan, same error ×2, before done) show as nodes wired to the stage they advise. Click a subagent card to toggle a live log of its transcript in a terminal to the right; the log closes itself 5 s after the subagent finishes. The panel follows whichever local Claude agent you focus.

![Claude Subagents](preview.png)

## What you see

Canvas width W = panel width minus 24 px (never below 220 px). The layout is chosen by W:

- **Narrow** (W below 620, or no advisor present): one column, top to bottom.
- **Wide** (W 620 or more, and the advisor is present): an advisor column on the left (184 px), a 44 px gap, then the flow in the remaining width.

Narrow, top to bottom. Rows are 40 px apart, except the return box, which is 18 px above the log.

- **Header**, 34 px, background `chrome`. "Claude" at 12 px semibold, then the session title (or name) and the terminal address joined by " · " at 11 px `dim`, truncated. A 1 px `border` line sits below.
- **Scroll area**, 12 px padding, vertical scrollbar. Everything below is drawn here at canvas coordinates.
  - **Advisor card**, only when the advisor is **present** (consulted at least once this session, or declared in the API request shape without `defer_loading`; every session here so far declares it deferred, so it stays hidden until a first consult); otherwise no advisor node, edge, column or footer item is drawn at all. Full width: 96 px with advice text, 76 px without. Title "<Model> · advisor" 12 px semibold; status word at right, 10.5 px: "on call", "advising" (with a spinner) or "silent". An 11 px muted line: "consulted N× · last <age> ago" or "on call · not consulted yet". A chip row at 10.5 px: "◇ plan", "◇ error ×2", "◇ done", each followed by " N×" once it has a count. Then "» <advice>" at 11 px.
  - **Lead card**, full width, 136 px. Title "<Model> · main session" 12.5 px semibold; status word at right (session state, or the elapsed time while working). Activity line 11.5 px. Rows at 11 px with a 72 px dim label column: `effort` (five 5×9 px bars plus the level name in mono; hidden when effort is unknown), `tool calls` (total count and the top 4 tool names with counts), `context` (context tokens, output tokens, turn number), `last` (last tool, only while working).
  - **Subagents group**, a box with a 10.5 px label "subagents · <models> · <running>/<shown> running", plus " · +N earlier" for subagents not drawn. Drawn: running ones, ones started this turn, and ones that finished less than 60 s ago (LINGER_MS); older finished ones leave the canvas. No visible subagents: no group, no return box. Cards: 2 columns when the flow width is 360 or more (the canvas width in the narrow layout; canvas width − 228 in the wide one), else 1; 10 px gaps; 26 px label band. Max 6 cards drawn.
  - **Subagent card**, 116 px tall: name 12 px semibold (truncated), model name at right in its family color (10.5 px). Progress bar (7 px tall, rounded) and "N call(s)" in mono 10.5 px. Detail line 11 px muted (falls back to the agent type). While running, "▸ <last tool>" in mono 10.5 px dim. Status row: spinner (running only), status label, then "time · N out" at right in 10.5 px dim.
  - **Back-to-lead box**, 260 px wide at most, 54 px tall, centered under the cards: "back to <Model> · lead" 12 px semibold and an 11 px status line.
  - **Session log**, full width, background `background`, 1 px `border`. "session log" 10.5 px dim, then up to 10 rows at 14 px: clock (dim), who (52 px wide, bold, model color), text (mono 10.5 px, truncated). "nothing yet" when empty.
- **Footer**, 26 px, `border` line on top, mono 10.5 px: `<lead family> [<session state>]`, `subagents [running/total]`, and `<advisor family> [advising | N×]` when an advisor exists.

Wide: the flow column is the narrow stack without the advisor card, starting at x = 228. The advisor column:

- **Advisor column**, 184 px wide, the full height of the flow. Its label "<Model> · advisor" is 10.5 px in the model color at the top.
- **Header card** inside it, 8 px in, 26 px from the top, 168 px wide: 132 px with advice text, 104 px without. Title, then the status word on its own line ("advising…", "silent", "on call") at 10.5 px, the 11 px line, and the advice.
- **Checkpoint nodes** `cp-plan`, `cp-error`, `cp-done`: 168 × 42 px, 6 px radius. First line: a glyph (◆ fired, ◇ not), the label ("before a plan", "same error ×2", "before done") at 11.5 px semibold, and "N×" in mono at right. Second line 10 px dim: "last <N>s ago" or "not yet". Each is centered on its target's height (the lead, the subagents group, or the return box) and never sits above the one before it, with 8 px between.

Colors. Model family to JSON Canvas preset to theme color: Opus to 6 (`ansi5`, purple), Sonnet to 2 (`ansi3`, orange), Haiku to 5 (`ansi6`, cyan), Fable and Mythos to 4 (`ansi2`, green), anything else to 3 (`ansi11`, yellow). Card and advisor frames: 1 px in that color, 25% alpha with `surface` fill when idle; 35% alpha with an 8% tint when active. Group boxes: 33% alpha border, 5% fill. Checkpoints: border 40% alpha once counted (20% before), full color with a 16% fill when fired. Status colors: running `working`, done `done`, failed `blocked`, stopped `idle`. Subtitle and labels use `dim` and `muted`; text is `foreground`. Theme colors may already carry alpha; every tint goes through `alpha()`, which multiplies it.

Edges are elbow routes: a Z between two sides that face the same way, an L otherwise. Their color is the model color (red for errors). The advisor link and the checkpoint links are dashed (3 on, 4 off). Labels sit at the midpoint on the `chrome` background at 10.5 px: "delegate", "results", "advising", "advises".

## How it behaves

- **Lead working** (session state `working`): frame active, braille spinner at the title's right, elapsed time since the last typed prompt in place of the state word.
- **Lead idle** (any other state, or none): state word shown (`idle` if empty), no spinner, idle frame. Its border still shows the turn's tool calls.
- **Advisor**: "on call" until the first call. While a call has no result yet, "advising" with a spinner, active frame, and a dashed live edge into the lead (narrow). After calls with nothing pending, "silent". Text advice shows as "» <text>". If no advice text ever came back and at least one result was encrypted, the card shows "» advice encrypted (lead-only)"; otherwise the last text advice stays shown.
- **Checkpoints**: each advisor call in the lead transcript is classified when it happens, in this order:
  1. `error` if the lead has two tool errors in a row at that moment.
  2. `done` if the turn has subagents and every one started this turn has returned (done or failed). This is the live rule.
  3. `plan` if at most one tool call has happened this turn.
  4. `mid` otherwise. `mid` counts in the advisor's calls but has no chip and no node.

  Retroactive `done`: when the next prompt arrives and no tool call came after the turn's last advice, that advice becomes `done`. While the session is not working, the same applies to the current turn's last advice. A checkpoint is "fired" (◆, pulsing) for 20 s after its call, and also while an advisor call of that kind is pending. Chips show the count; the wide nodes also show "last <N>s ago".
- **Subagent running**: spinner, active frame, bar at min(1, tool calls / 24) with a 4% minimum, last-tool line, elapsed time since start, live edge.
- **Subagent done**: "✓ done" in the done color, full bar, time from start to end, idle frame.
- **Subagent failed**: "✗ failed" in the blocked color, full bar.
- **Subagent stopped**: the lead process is gone and the subagent never returned. "stopped" in the idle color, full bar.
- **Errors**: a subagent whose last tool calls failed in a row (errors in row > 0) turns its bar, its newest border segment and its edge red.
- **Order**: running first, then failed and stopped, then done; newest first within each group.
- **Back-to-lead box** text: "waiting on N subagents" while any subagent started this turn is running; "review + verify" (active frame) once they have all returned while the session is working; "results delivered" when they have returned and the session is not working; "no subagents this turn" when none started since the last prompt. When the cards fit in one row, each card links straight to the box; otherwise the group does.
- **Without subagents**: no group, no return box. The error and done checkpoints both link to the lead.
- **Progress edges**: each edge draws a dim full route (35% alpha when live, 22% otherwise), then the first `progress` of it bright over that. Live edges are 2 px at full color, idle ones 1.5 px at 75%; nothing on an edge loops. The arrowhead is lit at full progress and 40% before that. **Messages ride their edge once**: each edge's `x-herdr.msgs` (spawn "task → <name>" on lead→card or lead→group, "result ← <name>" on card→return or group→return, "consult" (reversed, toward the advisor) and "advice" on the advisor or checkpoint edge; taken from `lead_events` newer than 30 s) becomes a packet the first time a scan shows it: an 8 px dot plus a mono 10 px label that steps corner to corner along the elbow route (native `left`/`top` transitions, 0.32 px/ms, one `cx.timer.after` per leg), then fades (0.7 s opacity transition after a 0.15 s delay) and is removed by a 0.9 s timer. Between messages nothing moves. The first scan after start only marks existing messages as seen; at most 8 packets launch per scan. Progress values: lead to a card = 1 when finished, else min(1, calls / 24); lead to the group = the average of those; card to the return box = 1 when finished, else 0; return box edge = share of this turn's subagents returned; advisor edge = 1 once it has a call; checkpoint edges = 1 once that checkpoint has a count.
- **Node borders**: a node with per-iteration progress (lead: this turn's tool calls; card: all its tool calls) gets one dashed segment per tool call, clockwise from the top centre of a rounded rectangle (radius 8). 24 segments make a lap; a completed lap leaves a dim full ring underneath. The newest segment is 2.5 px and blinks (opacity 0.35 to 1, 0.7 s) while the node is live and its last call is under 8 s old; it is red when the node's errors in a row are above 0. A finished card gets one solid ring. The group and the return box get a static smooth arc (1.8 px) for their progress.
- **Click a subagent card** toggles its log pane: every live terminal in `terminals()` whose `argv` contains that subagent's transcript path and a `…/tail.py` is closed with `terminal.kill`; if none is open, `terminal.open` with `python3 -u tail.py <transcript>`, placed right, named `log-<name slug>-<last 6 of id>`. Panes are found by argv, not name: herdr does not carry `terminal.open`'s name onto the core terminal (its `name` stays null). The name still has to be a valid core name (1-32 of a-z 0-9 - _ .), since spaces or "·" make the open fail. While a card's log is open, its border is stronger (alpha 0.6) and a "◉ log" tag shows at the right of the status row. Hover tints the card `hover`.
- **Refresh**: a 1.5 s timer. A scan runs on every tick while the session is working or any subagent is running; otherwise on every fourth tick (6 s). A scan is skipped while one is in flight. The view is replaced only when the output text changes or the followed agent changes.
- **Follows the focused Claude agent**: the focused agent if it is a local `claude-code` agent; else the agent already shown, if still there; else the first Claude agent in the focused space; else the first Claude agent.
- **Width change**: when the panel width changes by more than 1 px, a scan reruns with the new width. Cards go from 1 to 2 columns at canvas width 360 (panel 384). The wide layout starts at canvas width 620 (panel 644).
- **No session**: "No Claude Code session found. Start `claude` in a Herdr terminal and focus it." If the scan printed nothing and wrote to stderr: "Scan failed: <last stderr line>".

## Built from

Layout: `layouts/main-subagents.json`, a clone of `main` 0.1.13. The part that matters:

```
work (column)
  tabs            block, px 42
  work-body (row)
    work-main (row)            main block, tab: active
    subagents       stack      px 400, min 40, max 720, radius 10
      header        {"content":{"mod":"subagents-tabs"},"height":32}
      active        "subagents-claude"
      subagents-claude  block  content {"mod":"claude-subagents"}
      subagents-pi      block  content {"mod":"pi-subagents"}   (not covered here)
```

Mods:
- `claude-subagents` (`mod.json`: `{ "place": "none", "title": "Claude" }`; `main.js`). It takes no props. It draws the scan output. Widgets are chosen by each node's `x-herdr.kind`: `lead`, `advisor`, `agent`, `return`, `log`, `checkpoint`. Group nodes and any other canvas node use the generic drawing (a group's box and label, plus its arc).
- `subagents-tabs` (`main.js`): the stack header, "Claude" and "pi" tabs, 11.5 px semibold. It reads `layout()` for the active child of stack `subagents` and calls `layout.select {stack: "subagents", child}` on click.

Herdr calls from `claude-subagents`: `exec("python3", [scan.py, "--width", W, "--terminal", addr])` (the `--terminal` only when a Claude agent is picked); `appHome()`; `run("terminal.open", {argv, place: "right", name})`; `run("terminal.kill", {terminal})`; `terminals()` (log panes by argv); `agents()`; `focused()`; `theme()`; `cx.timer.every(1500)`; `cx.timer.after` (packet legs); `cx.spawn`; `cx.notify`; `on_size_change`. Theme names used: `chrome`, `surface`, `raised`, `hover`, `border`, `background`, `foreground`, `muted`, `dim`, `accent`, `working`, `done`, `blocked`, `idle`, `ansi1`, `ansi2`, `ansi3`, `ansi5`, `ansi6`, `ansi11`. gpui-kit: `View`, `div`, `PathBuilder` (`stroke`, `fill`, `dash_array`, `add_polygon`), `window.paint_path`, `.frames`, `.loop`, `.when`. gpui-base: `v_flex`, `h_flex`, `TextView` (for generic text nodes; scan.py emits none).

Programs:
- `python3 scan.py --width <px> [--terminal <addr>]`, run by `exec` on each refresh. Debug: `--session <id>` takes a finished session by id; `--transcript PATH` shows any lead transcript as a working session.
- `hc get <addr> --json` from inside scan.py (`hc`, then `~/.local/bin/hc`, 5 s timeout), to find the terminal's foreground pid, cwd, status and title.
- `python3 -u tail.py <transcript>`, opened in a terminal by a card click. It prints user tasks, assistant text, tool calls and errors. When `agent-<id>.meta.json` says `finished`, it counts down on one rewritten line, "— finished · closing in Ns · hover to keep open —", and exits at 0, which closes its pane. On a TTY it enables any-event mouse reporting (`\x1b[?1003h\x1b[?1006h`, cbreak input); any mouse report over the pane (hover) cancels the countdown for good ("— finished · kept open · q to close —") and the pane stays until `q`, the card toggle, or the transcript disappearing. Every exit path restores the mouse mode and terminal attributes. Not on a TTY: no mouse codes, plain 5 s countdown.
- `canvas.py` is imported by scan.py; it runs nothing.
- `python3 demo.py [--dir DIR] [--speed 1.0] [--loops N]`: a fake session (below).

Files read, read-only, under `~/.claude`: `sessions/<pid>.json` (`sessionId`, `pid`, `cwd`, `status`, `updatedAt`), all `sessions/*.json` when no terminal matches; `projects/<cwd with non-alphanumerics replaced by "-">/<sessionId>.jsonl` (the lead transcript); `projects/<slug>/<sessionId>/subagents/agent-*.meta.json` and `agent-*.jsonl`. scan.py also reads `override.json` in the cache folder (below).

Demo. `demo.py` writes a session in the real on-disk format: the lead transcript `DIR/<sid>.jsonl` and `DIR/<sid>/subagents/agent-<id>.jsonl` with `.meta.json`. While it runs it keeps `~/.cache/herdr-claude-subagents/override.json` pointing at the lead transcript (state, activity, title "demo: subagent swarm"). scan.py honors that file in place of the focused session, and the output then carries `session.demo: true`. The script: a prompt; a plan advice; a read and a grep; three background agents (search, grep, audit) with the audit's tests failing twice, which fires "same error ×2"; an edit and a test run; the "before done" advice; the final text; then state `idle`. Models: lead `claude-sonnet-5-5`, advisor `claude-opus-5-5`, subagents `claude-haiku-5-5`. Its default `--dir` is a fixed `/tmp/claude-1000/…/scratchpad/demo-session` path. It takes about 84 s at speed 1.

Cache: `~/.cache/herdr-claude-subagents/` (or `$XDG_CACHE_HOME/herdr-claude-subagents/`). `<sessionId>.json` holds `{"v": 6, "lead": …, "subs": {agent id: …}}`. Each transcript's state has the byte offset, inode, totals, the last 24 tool-call times (`iter_ts`), the last 40 events, and for the lead the advisor state (calls, pending calls, the last 20 classified calls). `<sessionId>.canvas` is the JSON Canvas copy, rewritten only when it changes.

Output: a JSON Canvas 1.0 document on stdout. Nodes: `advisor` (narrow: the card; wide: the header card inside the column), `advisor-col` (wide only), `cp-plan`, `cp-error`, `cp-done` (wide only), `lead`, `subagents` (group, when there are subagents), `agent-<id>` per card, `return`, `log`. Edges: `advisor` to `lead` (narrow, advisor present only); `lead` to `subagents` ("delegate") and `subagents` to `return` ("results"), or `lead` to each card and each card to `return` when the cards fit one row; `cp-*` right side to the target's left side (wide). Document `x-herdr`: `now`, `terminal`, `width`, `wide`, `session`, `lead_model`, `advisor` {model, calls, consulting, present}, `subagents` {running, total}. Each node carries `x-herdr` data:
- `lead`: `iters` (this turn's tool calls), `slots` 24, `last_iter`, `live`, `errors_in_row`, `turn_tools`, `effort_level`.
- `advisor`: the advisor's fields plus `line`, `advice`, `wide`, `hot`, `checkpoints` ({plan, error, done, mid} with `count` and `last_ts`), `last_kind`, `recent` (the last 5 classified calls; the panel does not draw it).
- `agent`: the subagent's fields plus `time`, `iters` (all its tool calls), `slots`, `last_iter`, `live`, `done`, `errors_in_row`.
- `return`: `active`, `line`, `model`, `progress` (share of this turn's subagents returned), `live`.
- `checkpoint`: `kind_of`, `label`, `count`, `fired`, `last_ts`.
- `log`: `rows`.
- group nodes: `progress`, `live`.

Each edge's `x-herdr` has `dashed`, `live`, `progress` (0 to 1) and `error`. With no session: empty `nodes` and `edges`, and `session: null`.

## Watch out

- The stack `header` must be an object, `{"content":{"mod":"subagents-tabs"},"height":32}`. The string `"tabs"` (as AGENTS.md suggests) is rejected: the whole layout file is not applied (`layout.error`: "expected struct Header") and the app keeps the last good layout.
- `preview.png` is not in this folder yet. `herdr-app shot` saves the whole window's last rendered frame, not this panel alone, so it can show a stale frame.
- `herdr-app check` renders once with no session data, so it only proves the empty state. To test the widgets with real data, bake a scan.py canvas into a copy of main.js so the copy starts with it, and render that copy.
- While `override.json` exists, the panel shows the demo instead of the focused session. `demo.py` removes the file when it exits normally or on SIGINT/SIGTERM, but not after a SIGKILL, so a stale file keeps the demo on screen until it is deleted.
- Opus 5.5 advisor advice is encrypted (`advisor_redacted_result`), so no advice text reaches the panel. Only call counts, the checkpoints and the "encrypted" note show.
- The bar on a card counts tool calls (min(1, calls / 24)); it is not a real percentage. A finished subagent shows a full bar.
- A subagent counts as finished when its `agent-*.meta.json` says `"finished": true`, or when the lead transcript has its result: a `tool_result` for a foreground agent, or a `<task-notification>` naming its `<tool-use-id>` for a background one (`<status>failed|error|killed` marks it failed). Otherwise it stays running while the lead process lives, and shows "stopped" after.
- A subagent's model comes from its transcript, else its meta `pickedEffortModel` or `model`; "?" when none.
- Local machine only. scan.py uses the local `/proc`, `~/.claude` and `os.kill`, and pick() ignores addresses with "/". A remote Claude session shows the "No Claude Code session found" text.
- At most 6 cards are drawn, and finished subagents from earlier turns drop off after 60 s; the rest count in "+N earlier". Each transcript keeps its last 40 events (EVENTS_KEPT); the merged log of lead events and subagent tool calls is capped at 14 (LOG_SHOWN), of which the canvas draws the last 10; edge messages come from the lead's last 20 events (`lead_events`).
- Transcript parsing is incremental. If the transcript's inode changes or it shrinks, the cached state resets. So does a cache whose `v` is not 6 (CACHE_VERSION).
- The canvas `text` fields hold Markdown for other viewers. This panel draws its own widgets for the six kinds above, and draws the edge labels itself, so those text fields are never shown here.
- The wide layout has no advisor-to-lead edge: the checkpoint nodes are its link. Chip labels (narrow: "plan", "error ×2", "done") differ from the node labels (wide: "before a plan", "same error ×2", "before done").
- `place: "none"` means only the layout places this mod. A fresh build that expects it to dock itself will see nothing.
- The mod uses timers only for data; do not add spinner timers, since `.frames` and `.loop` animate natively.

## Done when

- `herdr-app check ~/.config/herdr-app/mods/claude-subagents` passes.
- `python3 -I ~/.config/herdr-app/mods/claude-subagents/tests/test_scan.py` prints 9 `ok` lines and exits 0.
- `python3 -I ~/.config/herdr-app/mods/claude-subagents/tests/test_canvas.py` prints 12 `ok` lines and exits 0 (card expiry, advisor presence, edge messages, JSON Canvas validity, tail.py self-exit).
- `python3 ~/.config/herdr-app/mods/claude-subagents/scan.py --width 400` prints JSON whose `nodes` include `lead`, and writes `~/.cache/herdr-claude-subagents/<sessionId>.canvas` identical to stdout.
- `scan.py --session <id> --width 400` on a finished session prints a canvas with the same node ids.
- With no live Claude session, the panel shows "No Claude Code session found. Start `claude` in a Herdr terminal and focus it."
- Focusing a Claude terminal shows its title in the header and its model in the lead card.
- A subagent started during a turn shows a spinner and a rising bar. When it returns, the card reads "✓ done" or "✗ failed".
- Clicking a card opens a right-side terminal running `tail.py` on its transcript (core name stays null); clicking it again closes it. After the subagent finishes, the pane closes 5 s later unless the pointer moved over it.
- Panel width 384 px or more gives two card columns; below that, one.
- Panel width 644 px or more, with the advisor present, shows the wide layout: an advisor column on the left with three checkpoint nodes wired to the lead, the subagents and the return box.
- `python3 demo.py` at speed 1 (about 84 s) shows the demo session in the panel, with the plan, "same error ×2" and "before done" checkpoints firing, and removes `override.json` when it ends.
- The Claude | pi header switches the stack between this mod and `pi-subagents`.
