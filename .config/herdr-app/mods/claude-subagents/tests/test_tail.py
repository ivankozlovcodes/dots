"""Run: python3 -I tests/test_tail.py"""
import json, os, pty, signal, subprocess, sys, tempfile, termios, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TAIL = os.path.join(ROOT, "tail.py")
MOUSE_ON, MOUSE_OFF = "\x1b[?1003h", "\x1b[?1003l"
HOVER = "\x1b[<35;10;5M"


def write_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f)


def make_transcript(d):
    jsonl = os.path.join(d, "agent-x.jsonl")
    meta = os.path.join(d, "agent-x.meta.json")
    with open(jsonl, "w") as f:
        f.write(json.dumps({"type": "user", "message": {"content": "hi"},
                            "timestamp": "2026-01-01T00:00:00.000Z"}) + "\n")
    write_json(meta, {"finished": False})
    return jsonl, meta


class PtyTail:
    """tail.py with stdin/stdout/stderr on a real pty; output collected by a background reader."""

    def __init__(self, jsonl):
        self.master, self.slave = pty.openpty()
        self.attrs_before = termios.tcgetattr(self.slave)
        self.chunks = []
        self.proc = subprocess.Popen([sys.executable, "-u", TAIL, jsonl],
                                     stdin=self.slave, stdout=self.slave, stderr=self.slave,
                                     close_fds=True)
        self.reader = threading.Thread(target=self._drain, daemon=True)
        self.reader.start()

    def _drain(self):
        while True:
            try:
                data = os.read(self.master, 4096)
            except OSError:
                break
            if not data:
                break
            self.chunks.append(data)

    def output(self):
        return b"".join(self.chunks).decode("utf-8", "replace")

    def wait_for(self, text, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            if text in self.output():
                return True
            time.sleep(0.05)
        return text in self.output()

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        self.reader.join(2)
        os.close(self.slave)
        os.close(self.master)


def test_tty_closes_after_countdown_without_hover():
    with tempfile.TemporaryDirectory() as d:
        jsonl, meta = make_transcript(d)
        t = PtyTail(jsonl)
        try:
            assert t.wait_for(MOUSE_ON), "mouse reporting was never enabled"
            write_json(meta, {"finished": True})
            try:
                t.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                raise AssertionError("tail still running 8 s after finished, no hover")
            out = t.output()
            assert t.proc.returncode == 0, t.proc.returncode
            assert "closing in" in out, out
            assert MOUSE_ON in out and MOUSE_OFF in out, out
        finally:
            t.close()


def test_tty_hover_keeps_open_until_q():
    with tempfile.TemporaryDirectory() as d:
        jsonl, meta = make_transcript(d)
        t = PtyTail(jsonl)
        try:
            assert t.wait_for(MOUSE_ON), "mouse reporting was never enabled"
            t0 = time.time()
            write_json(meta, {"finished": True})
            time.sleep(1.5)
            os.write(t.master, HOVER.encode())
            while time.time() - t0 < 9:
                time.sleep(0.1)
            assert t.proc.poll() is None, "tail exited despite hover"
            out = t.output()
            assert "kept open" in out, out
            os.write(t.master, b"q")
            try:
                t.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                raise AssertionError("tail did not exit within 2 s of q")
            assert t.proc.returncode == 0, t.proc.returncode
            time.sleep(0.2)
            assert MOUSE_OFF in t.output(), t.output()
        finally:
            t.close()


def test_tty_sigterm_restores_terminal():
    with tempfile.TemporaryDirectory() as d:
        jsonl, _ = make_transcript(d)
        t = PtyTail(jsonl)
        try:
            assert t.wait_for(MOUSE_ON), "mouse reporting was never enabled"
            before = t.attrs_before
            during = termios.tcgetattr(t.slave)
            assert not during[3] & termios.ICANON and not during[3] & termios.ECHO, during[3]
            t.proc.send_signal(signal.SIGTERM)
            try:
                t.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                raise AssertionError("tail did not exit on SIGTERM")
            assert t.proc.returncode == 0, t.proc.returncode
            t.reader.join(2)
            assert MOUSE_OFF in t.output(), t.output()
            after = termios.tcgetattr(t.slave)
            for flag in (termios.ECHO, termios.ICANON):
                assert bool(before[3] & flag) == bool(after[3] & flag), (flag, before[3], after[3])
        finally:
            t.close()


def test_non_tty_closes_without_mouse_codes():
    with tempfile.TemporaryDirectory() as d:
        jsonl, meta = make_transcript(d)
        write_json(meta, {"finished": True})
        t0 = time.time()
        p = subprocess.run([sys.executable, "-u", TAIL, jsonl], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8)
        elapsed = time.time() - t0
        out = p.stdout.decode("utf-8", "replace")
        assert p.returncode == 0, (p.returncode, p.stderr)
        assert elapsed < 8, elapsed
        assert "finished" in out and "task" in out, out
        assert MOUSE_ON not in out and MOUSE_OFF not in out, out


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
