"""Shared helpers: JSON output, errors, subprocess calls, paths and times."""
import datetime as _dt
import json
import os
import subprocess
import sys
import tempfile

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"


class LfkError(Exception):
    """An error reported to the caller as JSON: {"ok": false, "error": code, ...}."""

    def __init__(self, code, message, exit_code=1, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.extra = extra

    def to_json(self):
        out = {"ok": False, "error": self.code, "message": self.message}
        out.update(self.extra)
        return out


def emit(obj, pretty=False, ascii_only=False, out_file=None):
    text = json.dumps(obj, ensure_ascii=ascii_only, indent=2 if pretty else None, default=str)
    if out_file:
        with open(out_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        text = json.dumps({"ok": obj.get("ok", True), "written": os.path.abspath(out_file)}, ensure_ascii=ascii_only)
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def setup_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def run(args, timeout=None, env=None, input_text=None, encoding="utf-8"):
    """Run a program and return (returncode, stdout, stderr) as text. Never opens a console window."""
    kwargs = {}
    if IS_WIN:
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        p = subprocess.run(
            [str(a) for a in args], capture_output=True, timeout=timeout, env=env,
            input=input_text.encode(encoding) if input_text is not None else None, **kwargs)
    except subprocess.TimeoutExpired:
        raise LfkError("timeout", f"{os.path.basename(str(args[0]))} did not finish in {timeout} s")
    except OSError as e:
        raise LfkError("tool_failed", f"could not start {args[0]}: {e}")
    return p.returncode, p.stdout.decode(encoding, "replace"), p.stderr.decode(encoding, "replace")


def temp_path(suffix):
    fd, path = tempfile.mkstemp(prefix="lfk-", suffix=suffix)
    os.close(fd)
    os.unlink(path)
    return path


def remove_quietly(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def iso_time(epoch):
    if epoch is None:
        return None
    try:
        return _dt.datetime.fromtimestamp(float(epoch)).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return None


def filetime_to_iso(ft):
    """Windows FILETIME (100 ns since 1601) to local ISO time."""
    if ft in (None, "", 0):
        return None
    return iso_time(int(ft) / 10_000_000 - 11_644_473_600)


def parse_date(text):
    """'2024-05-01' or '2024-05-01T10:00' -> epoch seconds (local time)."""
    try:
        return _dt.datetime.fromisoformat(text).timestamp()
    except ValueError:
        raise LfkError("bad_argument", f"not a date: {text!r} (use YYYY-MM-DD)", exit_code=2)


def parse_size(text):
    """'500', '10k', '5MB', '1.5g' -> bytes."""
    t = str(text).strip().lower().rstrip("b")
    mult = 1
    for suffix, m in (("k", 1024), ("m", 1024 ** 2), ("g", 1024 ** 3), ("t", 1024 ** 4)):
        if t.endswith(suffix):
            t, mult = t[:-1], m
            break
    try:
        return int(float(t) * mult)
    except ValueError:
        raise LfkError("bad_argument", f"not a size: {text!r} (use e.g. 500, 10k, 5MB, 1.5GB)", exit_code=2)


def abspath(p):
    return os.path.abspath(os.path.expanduser(str(p)))


def fix_case_prefix(path, roots):
    """Some tools lower-case the folder you gave them; put the caller's spelling back."""
    low = path.lower()
    for r in roots:
        rr = r.rstrip("\\/")
        if low.startswith(rr.lower()) and len(path) >= len(rr):
            return rr + path[len(rr):]
    return path
