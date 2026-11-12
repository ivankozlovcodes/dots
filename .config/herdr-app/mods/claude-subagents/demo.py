#!/usr/bin/env python3
"""Simulate a growing Claude Code session with background subagents.

Writes a lead transcript DIR/<sid>.jsonl and subagent transcripts
DIR/<sid>/subagents/agent-<id>.jsonl (+ .meta.json), mirroring the real
on-disk format, and keeps ~/.cache/herdr-claude-subagents/override.json
pointing at the lead transcript while it runs.

Usage: python3 demo.py [--dir DIR] [--speed 1.0] [--loops N]
"""
import argparse
import base64
import json
import os
import random
import signal
import string
import time
import uuid
from datetime import datetime, timezone

DEFAULT_DIR = ("/tmp/claude-1000/-home-iv/d7d4b8cb-3f1c-4d5c-aec5-47ad1425bca9"
               "/scratchpad/demo-session")
OVERRIDE_PATH = os.path.expanduser("~/.cache/herdr-claude-subagents/override.json")
TITLE = "demo: subagent swarm"
LEAD_MODEL = "claude-sonnet-5-5"
ADVISOR_MODEL = "claude-opus-5-5"
SUB_MODEL = "claude-haiku-5-5"
VERSION = "2.1.319"
CWD = "/home/iv/projects/webapp"
PROMPT = "Refactor auth to use the new session store"
B62 = string.ascii_letters + string.digits
HEX = "0123456789abcdef"
CONTEXT_START = 20000
CONTEXT_END = 120000
LEAD_RECORDS_EXPECTED = 16  # used to pace the lead's context growth

SPEED = 1.0

AUTH_TS = """import { randomUUID } from "crypto";
import { Session } from "./session/types";

const sessions = new Map<string, Session>();

export function createSession(userId: string): Session {
  const id = randomUUID();
  const s: Session = { id, userId, createdAt: Date.now() };
  sessions.set(id, s);
  return s;
}

export function getSession(id: string): Session | undefined {
  return sessions.get(id);
}
"""

TEST_ERR = ("FAIL  tests/auth.test.ts > login > stores session\n"
            "TypeError: Cannot read properties of undefined (reading 'set')\n"
            "    at SessionStore.set (src/session/store.ts:14:21)\n\n"
            " Test Files  1 failed (1)\n      Tests  1 failed | 8 passed (9)\n"
            "exit code 1")
TEST_OK = (" Test Files  3 passed (3)\n      Tests  27 passed (27)")

SPECS = [
    {
        "desc": "search: map the repo",
        "prompt": ("You are the agent named 'search'. Map the repository at "
                   f"{CWD}: list the TypeScript sources, the session modules and the "
                   "test layout. Report a short map and do not modify anything."),
        "final": ("Repo map: src/auth.ts (createSession/getSession over a module-level Map), "
                  "src/session/store.ts and src/session/types.ts (session model), "
                  "src/routes/login.ts and logout.ts (callers), src/middleware/requireAuth.ts, "
                  "tests under tests/ (Vitest). No changes made."),
        "plan": [
            ("Glob", {"pattern": "**/*.ts", "path": CWD, "description": "List TypeScript files"},
             "src/auth.ts\nsrc/session/store.ts\nsrc/session/types.ts\nsrc/routes/login.ts\n"
             "src/routes/logout.ts\nsrc/middleware/requireAuth.ts\ntests/auth.test.ts", False),
            ("Bash", {"command": "ls -la src src/session", "description": "Inspect src layout"},
             "src:\nauth.ts\nmiddleware\nroutes\nsession\n\nsrc/session:\nstore.ts\ntypes.ts\nindex.ts", False),
            ("Read", {"file_path": f"{CWD}/src/session/store.ts", "description": "Read session store"},
             "export class SessionStore {\n  private items = new Map<string, Session>();\n"
             "  set(id: string, s: Session) { this.items.set(id, s); }\n"
             "  get(id: string) { return this.items.get(id); }\n}", False),
            ("Read", {"file_path": f"{CWD}/src/auth.ts", "description": "Read auth module"}, AUTH_TS, False),
            ("Grep", {"pattern": "export (class|function) \\w+", "path": f"{CWD}/src",
                      "output_mode": "content", "description": "List exported symbols"},
             "src/auth.ts:6:export function createSession(userId: string): Session {\n"
             "src/auth.ts:12:export function getSession(id: string): Session | undefined {\n"
             "src/session/store.ts:1:export class SessionStore {", False),
            ("Bash", {"command": "head -40 package.json", "description": "Read package manifest"},
             '{\n  "name": "webapp",\n  "scripts": { "test": "vitest run" },\n  "devDependencies": { "vitest": "^3.2.0" }\n}', False),
        ],
    },
    {
        "desc": "grep: find call sites",
        "prompt": ("You are the agent named 'grep'. Find every call site of getSession, "
                   "createSession and direct use of the in-memory session Map across src/ "
                   "and report file:line for each. Do not modify anything."),
        "final": ("Call sites: 7 across src/. getSession: src/auth.ts:12, src/routes/logout.ts:9, "
                  "src/middleware/requireAuth.ts:21. createSession: src/auth.ts:6, "
                  "src/routes/login.ts:14. Direct Map access: src/auth.ts:4 only. No changes made."),
        "plan": [
            ("Grep", {"pattern": "session", "path": f"{CWD}/src", "output_mode": "files_with_matches",
                      "description": "Find files mentioning session"},
             "src/auth.ts\nsrc/routes/login.ts\nsrc/routes/logout.ts\nsrc/middleware/requireAuth.ts", False),
            ("Bash", {"command": "grep -rn 'getSession\\|createSession' src | head -50",
                      "description": "Find session call sites"},
             "src/auth.ts:6:export function createSession(\nsrc/auth.ts:12:export function getSession(\n"
             "src/routes/login.ts:14:  const s = createSession(user.id);\n"
             "src/routes/logout.ts:9:  const s = getSession(req.cookies.sid);\n"
             "src/middleware/requireAuth.ts:21:  const s = getSession(token);", False),
            ("Grep", {"pattern": "SessionStore", "path": f"{CWD}/src", "output_mode": "content",
                      "description": "Check existing SessionStore usage"},
             "src/session/store.ts:1:export class SessionStore {", False),
            ("Read", {"file_path": f"{CWD}/src/routes/login.ts", "description": "Read login route"},
             "import { createSession } from '../auth';\n\nexport async function login(req, res) {\n"
             "  const user = await verify(req.body);\n  const s = createSession(user.id);\n"
             "  res.cookie('sid', s.id);\n  res.json({ ok: true });\n}", False),
            ("Read", {"file_path": f"{CWD}/src/routes/logout.ts", "description": "Read logout route"},
             "import { getSession } from '../auth';\n\nexport function logout(req, res) {\n"
             "  const s = getSession(req.cookies.sid);\n  if (s) s.revoked = true;\n  res.end();\n}", False),
            ("Glob", {"pattern": "**/*middleware*", "path": CWD, "description": "Find middleware files"},
             "src/middleware/requireAuth.ts", False),
            ("Read", {"file_path": f"{CWD}/src/middleware/requireAuth.ts",
                      "description": "Read auth middleware"},
             "import { getSession } from '../auth';\n\nexport function requireAuth(req, res, next) {\n"
             "  const s = getSession(req.headers.authorization);\n  if (!s) return res.status(401).end();\n"
             "  next();\n}", False),
            ("Bash", {"command": "grep -rn 'Map<string, Session>' src",
                      "description": "Check direct Map usage"},
             "src/auth.ts:4:const sessions = new Map<string, Session>();", False),
            ("Grep", {"pattern": "createSession\\(", "path": f"{CWD}/src", "output_mode": "content",
                      "description": "Confirm createSession callers"},
             "src/auth.ts:6:export function createSession(userId: string): Session {\n"
             "src/routes/login.ts:14:  const s = createSession(user.id);", False),
        ],
    },
    {
        "desc": "audit: run tests in a worktree",
        "prompt": ("You are the agent named 'audit'. Create a git worktree of HEAD at "
                   "../webapp-audit, install dependencies there, run the auth tests and report "
                   "the results. Do not modify the main checkout."),
        "final": ("Ran in worktree ../webapp-audit (detached HEAD). npm ci ok. "
                  "'npm test -- auth' failed twice with a TypeError in SessionStore.set (stale "
                  "vitest cache in the fresh worktree). A direct vitest run passed, and the full "
                  "suite passes: 3 files, 27 tests. No changes to the main checkout."),
        "plan": [
            ("Bash", {"command": "git worktree add ../webapp-audit HEAD",
                      "description": "Create audit worktree"},
             "Preparing worktree (detached HEAD 3f9c2ab)\nHEAD is now at 3f9c2ab refactor: split routes", False),
            ("Bash", {"command": "cd ../webapp-audit && npm ci --silent",
                      "description": "Install deps in worktree"},
             "added 412 packages in 18s", False),
            ("Read", {"file_path": "/home/iv/projects/webapp-audit/package.json",
                      "description": "Read package manifest"},
             '{ "scripts": { "test": "vitest run" } }', False),
            ("Bash", {"command": "cd ../webapp-audit && ls tests",
                      "description": "List test files"},
             "auth.test.ts\nsession.test.ts\nrequireAuth.test.ts", False),
            ("Bash", {"command": "cd ../webapp-audit && npm test -- auth",
                      "description": "Run auth tests"}, TEST_ERR, True),
            ("Bash", {"command": "cd ../webapp-audit && npm test -- auth --runInBand",
                      "description": "Rerun auth tests serially"}, TEST_ERR, True),
            ("Read", {"file_path": "/home/iv/projects/webapp-audit/tests/auth.test.ts",
                      "description": "Read auth test"},
             "beforeEach(() => { store = new SessionStore(); });\n\ntest('stores session', () => {\n"
             "  store.set('a', s);\n});", False),
            ("Grep", {"pattern": "new SessionStore", "path": "/home/iv/projects/webapp-audit/src",
                      "output_mode": "content", "description": "Find SessionStore construction"},
             "src/session/store.ts:1:export class SessionStore {", False),
            ("Bash", {"command": "cd ../webapp-audit && npx vitest run tests/auth.test.ts",
                      "description": "Run auth test file directly"},
             " Test Files  1 passed (1)\n      Tests  9 passed (9)", False),
            ("Read", {"file_path": "/home/iv/projects/webapp-audit/src/session/store.ts",
                      "description": "Read session store"},
             "export class SessionStore {\n  private items = new Map<string, Session>();\n}", False),
            ("Bash", {"command": "git -C ../webapp-audit diff --stat",
                      "description": "Confirm no worktree edits"}, "", False),
            ("Bash", {"command": "cd ../webapp-audit && npm test",
                      "description": "Run full test suite"}, TEST_OK, False),
        ],
    },
]


def rnd(alphabet, n):
    return "".join(random.choices(alphabet, k=n))


def now_iso():
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def pause(lo=0.7, hi=2.0):
    time.sleep(random.uniform(lo, hi) / SPEED)


def append(path, rec):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
        f.flush()


def write_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
        f.flush()
    os.replace(tmp, path)


def usage(inp, cr, cc, out):
    return {
        "input_tokens": inp,
        "cache_creation_input_tokens": cc,
        "cache_read_input_tokens": cr,
        "output_tokens": out,
        "output_tokens_details": {"thinking_tokens": random.randint(0, out // 3)},
        "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0},
        "service_tier": "standard",
        "cache_creation": {"ephemeral_1h_input_tokens": cc, "ephemeral_5m_input_tokens": 0},
        "inference_geo": "global",
        "iterations": [{"input_tokens": inp, "output_tokens": out,
                        "cache_read_input_tokens": cr, "cache_creation_input_tokens": cc,
                        "type": "message"}],
        "speed": "standard",
    }


def summarize(name, inp):
    if name in ("Read", "Edit"):
        return os.path.basename(inp.get("file_path", ""))
    if name in ("Grep", "Glob"):
        return inp.get("pattern", "")
    return inp.get("description", inp.get("command", ""))[:80]


class Actor:
    """One transcript file plus its own parentUuid chain."""

    def __init__(self, path, sidechain, prompt_id, agent_id=None):
        self.path = path
        self.sidechain = sidechain
        self.prompt_id = prompt_id
        self.agent_id = agent_id
        self.last = None

    def emit(self, type_, sid, message, **extra):
        rec = {"parentUuid": self.last, "isSidechain": self.sidechain}
        if self.agent_id:
            rec["agentId"] = self.agent_id
        rec["promptId"] = self.prompt_id
        rec["type"] = type_
        rec["message"] = message
        rec.update(extra)
        rec.update({
            "uuid": str(uuid.uuid4()),
            "timestamp": now_iso(),
            "userType": "external",
            "entrypoint": "sdk-cli",
            "cwd": CWD,
            "sessionId": sid,
            "version": VERSION,
            "gitBranch": "HEAD",
        })
        append(self.path, rec)
        self.last = rec["uuid"]
        return rec


class Sub:
    def __init__(self, spec, aid, tid, actor, meta_path, meta):
        self.spec = spec
        self.name = spec["desc"].split(":")[0]
        self.aid = aid
        self.tid = tid
        self.actor = actor
        self.meta_path = meta_path
        self.meta = meta
        self.i = 0
        self.consec = 0
        self.double_error = False
        self.finished = False


class Session:
    def __init__(self, base):
        self.sid = str(uuid.uuid4())
        self.lead_path = os.path.join(base, self.sid + ".jsonl")
        self.sub_dir = os.path.join(base, self.sid, "subagents")
        os.makedirs(self.sub_dir, exist_ok=True)
        open(self.lead_path, "a").close()
        self.lead = Actor(self.lead_path, False, str(uuid.uuid4()))
        self.ctx = CONTEXT_START
        self.step_ctx = (CONTEXT_END - CONTEXT_START) / LEAD_RECORDS_EXPECTED
        self.checkpoint_done = False
        self.subs = []

    def override(self, state, activity):
        write_atomic(OVERRIDE_PATH, {
            "transcript": self.lead_path,
            "state": state,
            "activity": activity,
            "title": TITLE,
        })

    # ---- lead -------------------------------------------------------------
    def lead_asst(self, content, stop_reason, out):
        inc = int(self.step_ctx * random.uniform(0.75, 1.25))
        if self.ctx + inc + out > CONTEXT_END:
            inc = random.randint(300, 800)
        msg = {
            "model": LEAD_MODEL,
            "id": "msg_01" + rnd(B62, 22),
            "type": "message",
            "role": "assistant",
            "content": content,
            "container": None,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "stop_details": None,
            "usage": usage(random.randint(2, 4), self.ctx, inc, out),
        }
        self.ctx += inc + out
        return self.lead.emit("assistant", self.sid, msg,
                              requestId="req_011" + rnd(B62, 21),
                              requestedModel=LEAD_MODEL,
                              effort="high",
                              perTurnEffort="high",
                              advisorModel=ADVISOR_MODEL,
                              promptCacheRequested="1h")

    def lead_tool(self, name, inp, result, is_error=False, text=None):
        tid = "toolu_01" + rnd(B62, 22)
        content = []
        if text:
            content.append({"type": "text", "text": text})
        content.append({"type": "tool_use", "id": tid, "name": name,
                        "input": inp, "caller": {"type": "direct"}})
        self.lead_asst(content, "tool_use", random.randint(90, 260))
        self.override("working", f"{name}: {summarize(name, inp)}")
        time.sleep(0.5 / SPEED)
        self.lead.emit("user", self.sid, {"role": "user", "content": [
            {"tool_use_id": tid, "type": "tool_result", "content": result, "is_error": is_error}]})
        pause()
        return tid

    def advisor(self, plan_text, label):
        srv_id = "srvtoolu_" + rnd(B62, 24)
        self.lead_asst([{"type": "server_tool_use", "id": srv_id,
                         "name": "advisor", "input": {}}], "tool_use", random.randint(60, 140))
        self.override("working", f"Consulting advisor ({label})")
        time.sleep(2.0 / SPEED)
        enc = base64.b64encode(os.urandom(96)).decode()
        self.lead_asst([
            {"type": "advisor_tool_result", "tool_use_id": srv_id,
             "content": {"type": "advisor_redacted_result", "encrypted_content": enc}},
            {"type": "text", "text": plan_text},
        ], "end_turn", random.randint(180, 420))
        pause()

    def spawn(self, spec, text=None):
        tid = "toolu_01" + rnd(B62, 22)
        aid = rnd(HEX, 17)
        inp = {"description": spec["desc"], "prompt": spec["prompt"],
               "subagent_type": "general-purpose", "model": "haiku",
               "run_in_background": True}
        content = []
        if text:
            content.append({"type": "text", "text": text})
        content.append({"type": "tool_use", "id": tid, "name": "Agent",
                        "input": inp, "caller": {"type": "direct"}})
        self.lead_asst(content, "tool_use", random.randint(200, 400))
        self.override("working", f"Spawning {spec['desc'].split(':')[0]} agent")
        time.sleep(0.5 / SPEED)
        result_text = (
            "Async agent launched successfully. (This tool result is internal metadata "
            "— never quote or paste any part of it, including the agentId below, into a "
            "user-facing reply.)\n"
            f"agentId: {aid} (internal ID - do not mention to user.)\n"
            "The agent is working in the background. You will be notified automatically when it completes.")
        self.lead.emit("user", self.sid,
                       {"role": "user", "content": [{"tool_use_id": tid, "type": "tool_result",
                                                     "content": [{"type": "text", "text": result_text}]}]},
                       toolUseResult={"isAsync": True, "status": "async_launched", "agentId": aid,
                                      "description": spec["desc"], "resolvedModel": SUB_MODEL})

        path = os.path.join(self.sub_dir, f"agent-{aid}.jsonl")
        meta_path = os.path.join(self.sub_dir, f"agent-{aid}.meta.json")
        actor = Actor(path, True, self.lead.prompt_id, aid)
        open(path, "a").close()
        actor.emit("user", self.sid, {"role": "user", "content": spec["prompt"]})
        meta = {
            "agentType": "general-purpose",
            "isBuiltIn": True,
            "description": spec["desc"],
            "toolUseId": tid,
            "spawnDepth": 1,
            "requestShape": "background",
            "requestNonInteractive": True,
            "model": "haiku",
            "pickedEffortModel": SUB_MODEL,
            "finished": False,
        }
        write_atomic(meta_path, meta)
        self.subs.append(Sub(spec, aid, tid, actor, meta_path, meta))
        pause()

    # ---- subagents ----------------------------------------------------------
    def sub_step(self, sub):
        name, inp, result, is_err = sub.spec["plan"][sub.i]
        tid = "toolu_01" + rnd(B62, 22)
        cr = 9000 + sub.i * 1600 + random.randint(0, 800)
        msg = {
            "model": SUB_MODEL,
            "id": "msg_01" + rnd(B62, 22),
            "type": "message",
            "role": "assistant",
            "content": [{"type": "tool_use", "id": tid, "name": name,
                         "input": inp, "caller": {"type": "direct"}}],
            "container": None,
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": usage(2, cr, random.randint(300, 1200), random.randint(40, 350)),
        }
        a = sub.actor.emit("assistant", self.sid, msg,
                           requestId="req_011" + rnd(B62, 21),
                           requestedModel=SUB_MODEL)
        self.override("working", f"{sub.name}: {summarize(name, inp)}")
        time.sleep(0.5 / SPEED)
        sub.actor.emit("user", self.sid, {"role": "user", "content": [
            {"tool_use_id": tid, "type": "tool_result", "content": result, "is_error": is_err}]},
            sourceToolAssistantUUID=a["uuid"])
        sub.i += 1
        if is_err:
            sub.consec += 1
            if sub.consec == 2:
                sub.double_error = True
        else:
            sub.consec = 0
        pause()

    def sub_finish(self, sub):
        cr = 9000 + sub.i * 1600
        msg = {
            "model": SUB_MODEL,
            "id": "msg_01" + rnd(B62, 22),
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": sub.spec["final"]}],
            "container": None,
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": usage(4, cr, random.randint(300, 900), random.randint(60, 200)),
        }
        sub.actor.emit("assistant", self.sid, msg,
                       requestId="req_011" + rnd(B62, 21), requestedModel=SUB_MODEL)
        sub.meta["finished"] = True
        write_atomic(sub.meta_path, sub.meta)
        sub.finished = True

        body = (f"<task-notification>\n<task-id>{sub.aid}</task-id>\n"
                f"<tool-use-id>{sub.tid}</tool-use-id>\n<status>completed</status>\n"
                f"<summary>Agent \"{sub.spec['desc']}\" finished</summary>\n</task-notification>")
        self.lead.emit("user", self.sid, {"role": "user", "content": body},
                       origin={"kind": "task-notification", "producer": "session-task"},
                       promptSource="system", turnOrigin="task_notification")
        still = [s.name for s in self.subs if not s.finished]
        self.override("working", f"{sub.name} finished; waiting on {', '.join(still) or 'nothing'}")
        pause()

    def checkpoint(self):
        self.lead_tool("Bash", {"command": "npm test -- auth", "description": "Run auth tests"},
                       TEST_ERR, True,
                       text="audit hit the same failure twice, so I'll check the store myself.")
        self.lead_tool("Bash", {"command": "npx vitest run tests/auth.test.ts",
                                "description": "Run auth test file directly"}, TEST_ERR, True)
        self.advisor("Same error twice in a row (TypeError in SessionStore.set). Stop re-running "
                     "the suite. Check whether the store is constructed before use and whether the "
                     "test fixture resets it, before touching callers.", "same error x2")
        self.checkpoint_done = True

    # ---- run ----------------------------------------------------------------
    def run(self):
        self.override("working", "Received prompt")
        self.lead.emit("user", self.sid, {"role": "user", "content": PROMPT},
                       promptSource="sdk", turnOrigin="sdk", permissionMode="default")
        pause()

        self.advisor("Plan: 1) Read src/auth.ts to map the in-memory Map usage. 2) Grep for "
                     "session call sites. 3) Fan out search, grep and audit subagents in parallel. "
                     "4) Migrate auth.ts to the SessionStore API and keep the public signatures. "
                     "5) Run the auth tests before reporting back.", "plan")

        self.lead_tool("Read", {"file_path": f"{CWD}/src/auth.ts", "description": "Read auth module"},
                       AUTH_TS, text="Let me look at the current auth flow first.")
        self.lead_tool("Grep", {"pattern": "session", "path": f"{CWD}/src",
                                "output_mode": "content", "description": "Find session usage"},
                       "src/auth.ts:4:const sessions = new Map<string, Session>();\n"
                       "src/auth.ts:6:export function createSession(userId: string): Session {\n"
                       "src/routes/login.ts:14:  const s = createSession(user.id);\n"
                       "src/routes/logout.ts:9:  const s = getSession(req.cookies.sid);")

        for n, spec in enumerate(SPECS):
            self.spawn(spec, text=("Splitting the discovery work across three background agents."
                                   if n == 0 else None))

        # Interleave subagent iterations until every subagent has finished.
        while not all(s.finished for s in self.subs):
            active = [s for s in self.subs if not s.finished]
            names = ", ".join(s.name for s in active)
            self.override("working", f"Waiting on {len(active)} subagent(s): {names}")
            sub = random.choice(active)
            if sub.i < len(sub.spec["plan"]):
                self.sub_step(sub)
                if sub.double_error and not self.checkpoint_done:
                    self.checkpoint()
            else:
                self.sub_finish(sub)

        self.lead_tool("Edit", {
            "file_path": f"{CWD}/src/auth.ts",
            "old_string": 'import { Session } from "./session/types";\n\nconst sessions = new Map<string, Session>();',
            "new_string": ('import { Session } from "./session/types";\n'
                           'import { SessionStore } from "./session/store";\n\n'
                           'const sessions = new SessionStore();'),
        }, "The file " + f"{CWD}/src/auth.ts" + " has been updated successfully.")
        self.lead_tool("Bash", {"command": "npm test -- auth", "description": "Run tests"}, TEST_OK)
        self.advisor("Before done: the auth tests pass. Confirm getSession still returns the same "
                     "Session shape for logout, and check routes/logout.ts before reporting.",
                     "before done")

        self.lead_asst([{"type": "text", "text": (
            "Refactored src/auth.ts to use SessionStore. The module-level Map is replaced, and "
            "createSession and getSession keep their signatures. search mapped the repo, grep found "
            "7 call sites, and audit ran the suite in a worktree. It hit the same SessionStore "
            "TypeError twice before passing. Auth tests: 27 passed.")}], "end_turn",
            random.randint(150, 300))
        self.override("idle", "Session complete; waiting for input")
        pause()


def main():
    ap = argparse.ArgumentParser(description="Growing fake Claude Code session for dashboard demos.")
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--loops", type=int, default=1)
    args = ap.parse_args()
    if args.speed <= 0:
        ap.error("--speed must be > 0")
    if args.loops < 1:
        ap.error("--loops must be >= 1")

    global SPEED
    SPEED = args.speed
    base = os.path.abspath(os.path.expanduser(args.dir))
    os.makedirs(base, exist_ok=True)
    os.makedirs(os.path.dirname(OVERRIDE_PATH), exist_ok=True)

    def on_signal(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    try:
        for n in range(args.loops):
            Session(base).run()
            if n + 1 < args.loops:
                time.sleep(3.0 / SPEED)
    finally:
        try:
            os.remove(OVERRIDE_PATH)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
