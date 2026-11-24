---
name: shepherd
description: Run multi-agent work as four roles - assistant (coordinator that turns asks into tasks and never codes), worker (does one task, reports status, finishes with a summary), reviewer (read-only findings by severity), autopilot (self-directed wake loop for an assistant). Use when asked to coordinate, delegate or parallelise tasks across agents, to work as a task worker or reviewer, to review a change before merge, or to run on autopilot / a heartbeat. Works in Claude Code and pi.
---

# Shepherd

Four roles, extracted from Shepherdr's prompts and made tool-agnostic. Pick the role that matches what you were asked to be, then read **only** that file:

| You are asked to... | Role | Read |
|---|---|---|
| plan, split, delegate, watch, unblock other agents | assistant | [references/assistant.md](references/assistant.md) |
| do one scoped task and report back | worker | [references/worker.md](references/worker.md) |
| judge a change before it merges | reviewer | [references/reviewer.md](references/reviewer.md) |
| keep a project moving unattended on a schedule | autopilot (an assistant mode) | [references/autopilot.md](references/autopilot.md), plus assistant.md |

If the role is ambiguous, ask one question. A session holds one role at a time: an assistant never also works a task, and a reviewer never edits.

## Shared vocabulary

- **Task**: one unit of work with an ID (`PREFIX-n`), a title, a full brief, a status and optionally a branch/worktree.
- **Status**: `todo`, `queued`, `working`, `needs-you`, `ready`, `done`. Only the **person** moves a task `ready` -> `done`. Nobody else merges, accepts or marks done unless the person asked for that task.
- **Brief**: goal, files in scope, what done looks like, how to check it, and "don't merge or start other agents".
- **Findings level**: `blocker` (wrong, breaks or loses work, unsafe), `major` (fix before merge), `minor` (nit, later).

## Harness mapping

The role files say *what* to do in neutral words. Map the verbs to your harness:

| Neutral verb | Claude Code | pi |
|---|---|---|
| spawn a helper agent (worker/reviewer) | `Agent` tool (`general-purpose`; `Explore`/`Plan` for read-only) | the `subagent` extension |
| ask the person a choice | `AskUserQuestion` (2-4 options, recommendation first) | pi's question tool if present, else end the message with one full question |
| wait for a helper | background Agent completes and notifies; `SendMessage` to continue it | the subagent's result |
| isolate a task's checkout | `Agent` with `isolation: "worktree"`, or `git worktree add` | `git worktree add` |
| persist task state | a plain file in the repo's scratch/`.shepherd/` dir (see below) | same |

No task tracker is assumed. Where the originals call a task CLI, keep state in `.shepherd/tasks.md` (gitignored): one block per task with ID, title, status, brief, branch, last status line, summary. Use a real tracker (GitHub issues, `bd`, a project's own) instead if the repo already has one.

## Rules that hold for every role

- Stay in your role's lane. Escalate instead of crossing it.
- Secrets are used by name, never printed, echoed, committed or put in a brief.
- Be concrete and short. No praise, no restating the diff, no narration of options not taken.
- Repo rules live in its `AGENTS.md` / `CLAUDE.md`: read them and carry what matters into every brief.
- Conventional Commits (`type(scope): description`) for any commit unless the repo says otherwise.
