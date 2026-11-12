#!/usr/bin/env python3
"""Follow a Claude transcript (JSONL) and print who did what, as it happens.

Once the subagent's meta file says finished, the pane counts down and closes
itself (the program exits, the pane closes). If the mouse hovers over the pane
during that countdown, it stays open until "q" (or a signal) instead.
Hover is detected from terminal mouse reports, only when stdin is a TTY.
"""
import atexit, json, math, os, select, signal, sys, time

try:
    import termios, tty
except ImportError:  # not a POSIX terminal
    termios = tty = None

path = sys.argv[1]
DIM, CYAN, RED, BOLD, R = "\033[2m", "\033[36m", "\033[31m", "\033[1m", "\033[0m"


def show(e):
    if e.get("type") not in ("user", "assistant"):
        return
    m = e.get("message") or {}
    c = m.get("content")
    ts = (e.get("timestamp") or "")[11:19]
    if isinstance(c, str) and e.get("type") == "user" and not c.lstrip().startswith("<"):
        print(f"{DIM}{ts}{R} {BOLD}task{R} {c[:400]}")
        return
    for b in c if isinstance(c, list) else []:
        t = b.get("type")
        if t == "tool_use":
            inp = b.get("input") or {}
            arg = inp.get("description") or inp.get("command") or inp.get("file_path") or inp.get("pattern") or ""
            print(f"{DIM}{ts}{R} {CYAN}{b.get('name')}{R} {str(arg)[:160]}")
        elif t == "text" and b.get("text", "").strip() and not b["text"].lstrip().startswith("<"):
            print(f"{DIM}{ts}{R} {b['text'][:600]}")
        elif t == "tool_result" and b.get("is_error"):
            print(f"{DIM}{ts}{R} {RED}error{R} {str(b.get('content'))[:160]}")


META = path[: -len(".jsonl")] + ".meta.json" if path.endswith(".jsonl") else None
LINGER = 5  # seconds the pane stays after the subagent finishes, then it closes itself
POLL = 0.25
ENABLE_MOUSE = "\x1b[?1003h\x1b[?1006h"   # any-event tracking + SGR encoding
DISABLE_MOUSE = "\x1b[?1003l\x1b[?1006l"
MOUSE_REPORT = b"\x1b[<"
KEPT_TEXT = "— finished · kept open · q to close —"

interactive = termios is not None and os.isatty(0)
hovered = False        # any mouse report seen so far (sticky: once hovered, the countdown is cancelled for good)
stop = False           # set by "q" or a lost terminal
active = False         # terminal is currently in mouse/cbreak mode and must be restored
saved_attrs = None
status_text = None     # the status line currently drawn on the cursor line, if any


def countdown_text(n):
    return f"— finished · closing in {n}s · hover to keep open —"


def status(text):
    """Draw the status line. On a TTY it is rewritten in place; otherwise it is one plain line."""
    global status_text
    if interactive:
        status_text = text
        sys.stdout.write("\r\x1b[2K" + DIM + text + R)
    else:
        sys.stdout.write(DIM + text + R + "\n")
    sys.stdout.flush()


def read_keys(timeout):
    """Wait up to `timeout` seconds for keyboard/mouse input and act on it."""
    global hovered, stop
    if not interactive:
        if timeout:
            time.sleep(timeout)
        return
    ready, _, _ = select.select([0], [], [], timeout)
    if not ready:
        return
    try:
        data = os.read(0, 4096)
    except OSError:
        data = b""
    if not data:  # terminal went away: nothing left to keep open for
        stop = True
        return
    if MOUSE_REPORT in data:
        hovered = True
    if b"q" in data:
        stop = True


def finished():
    try:
        with open(META) as m:
            return bool(json.load(m).get("finished"))
    except (OSError, ValueError, TypeError):
        return False


def main():
    global status_text
    phase, deadline, shown = "watch", None, None   # watch -> count -> kept
    with open(path) as f:
        buf = ""
        while not stop:
            chunk = f.readline()
            if chunk:
                buf += chunk
                if buf.endswith("\n"):
                    if status_text:  # keep the status line off the transcript lines
                        sys.stdout.write("\r\x1b[2K")
                    try:
                        show(json.loads(buf))
                    except ValueError:
                        pass
                    buf = ""
                    if status_text:
                        sys.stdout.write(DIM + status_text + R)
                    sys.stdout.flush()
                read_keys(0)
                continue
            sys.stdout.flush()
            if not os.path.exists(path):
                break
            now = time.time()
            if phase == "watch" and META and finished():
                if hovered:
                    phase = "kept"
                    status(KEPT_TEXT)
                else:
                    phase, deadline, shown = "count", now + LINGER, LINGER
                    status(countdown_text(LINGER))
            elif phase == "count":
                if hovered:
                    phase = "kept"
                    status(KEPT_TEXT)
                else:
                    left = math.ceil(deadline - now)
                    if left <= 0:
                        break
                    if interactive and left != shown:
                        shown = left
                        status(countdown_text(left))
            read_keys(POLL)
    return 0


def restore():
    """Turn mouse reporting off and give the terminal back its saved attributes. Safe to call twice."""
    global active
    if not active:
        return
    active = False
    try:
        sys.stdout.write(DISABLE_MOUSE)
        sys.stdout.flush()
    except (OSError, ValueError):
        pass
    try:
        termios.tcsetattr(0, termios.TCSADRAIN, saved_attrs)
    except (OSError, termios.error):
        pass


def setup():
    global saved_attrs, active, interactive
    if not interactive:
        return
    try:
        saved_attrs = termios.tcgetattr(0)
        tty.setcbreak(0)  # no echo, no line buffering; output processing stays on
    except (OSError, termios.error):
        interactive = False
        return
    active = True
    sys.stdout.write(ENABLE_MOUSE)
    sys.stdout.flush()


def on_signal(signum, frame):
    restore()
    raise SystemExit(0)


def run():
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, on_signal)
    atexit.register(restore)
    setup()
    try:
        return main()
    finally:
        restore()


if __name__ == "__main__":
    sys.exit(run())
