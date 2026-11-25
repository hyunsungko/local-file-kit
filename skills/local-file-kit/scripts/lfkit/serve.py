"""serve: keep DigUp's searcher running so a search of the whole index takes about a second, not a process start.

`lfk serve` starts `digup search-service` (the index open, the query encoder on the CPU) and holds it, answering on a
named pipe (Windows) or a Unix socket in the per-user data folder - nothing listens on the network. Requests need the
key in serve.json beside it. `search` asks it first and runs `digup search` itself when it is not running.

The service loads the vectors (1,536 bytes per indexed piece) on the first search or the prewarm at start.
--idle is passed on as digup's --encoder-idle: after that many seconds without a search digup lets the vectors go,
and the next search reads them back from the index - seconds while Windows still caches the index file, minutes
when it does not. A search reads every vector, so the same wait comes when Windows moves them out of memory.
The server therefore runs at normal priority (a logon task starts it below normal, with low memory priority,
which makes its memory the first to go) and logs each search's time to search-times.log. --autostart on adds a
Windows task that starts it at logon; a large --idle there keeps the vectors in memory.
--release-at PERCENT (Windows, default 80, 0 = off) lets the vectors go early: when the whole computer's memory use
is at that percent or more, the helpers are stopped (checked every 15 s) and the next search starts them again.
Each release is a line in memory-release.log.
--reload-at PERCENT (default 70, 0 = off) reads them back by itself: once memory use has stayed under that percent
for a minute, and ten minutes have passed since the release, the main helper loads again, so the next search does
not wait. It waits longer while the memory the helper held before would bring use within 5 points of --release-at
(memory the DigUp app's own helper holds is already in that use). Each reload is a line in the same log.
"""
import argparse
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client, Listener

from . import tools
from .util import IS_WIN, LfkError, abspath, iso_time

TASK_NAME = "LocalFileKit-Search"
IDLE_DEFAULT = 604800  # 7 days: the vectors stay loaded; memory pressure (RELEASE_DEFAULT) is what lets them go
RELEASE_DEFAULT = 80
RELOAD_DEFAULT = 70


def state_path():
    return os.path.join(tools.data_dir(), "serve.json")


def read_state():
    try:
        with open(state_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _normal_priority(pid=None):
    """Normal CPU and memory priority for this process (children inherit the class) or for the child `pid`."""
    if not IS_WIN:
        return
    import ctypes
    k32 = ctypes.WinDLL("kernel32")
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    k32.SetProcessInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
    handle = k32.OpenProcess(0x0200, False, pid) if pid else k32.GetCurrentProcess()  # PROCESS_SET_INFORMATION
    if not handle:
        return
    k32.SetPriorityClass(handle, 0x20)  # NORMAL_PRIORITY_CLASS
    level = ctypes.c_ulong(5)  # MEMORY_PRIORITY_NORMAL; the logon task leaves 2
    k32.SetProcessInformation(handle, 0, ctypes.byref(level), ctypes.sizeof(level))  # ProcessMemoryPriority
    if pid:
        k32.CloseHandle(ctypes.c_void_p(handle))


def _log_search(seconds, which):
    path = os.path.join(tools.data_dir(), "search-times.log")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{iso_time(time.time())}\t{seconds:.2f}\t{which}\n")
        if os.path.getsize(path) > 200_000:
            with open(path, encoding="utf-8") as f:
                keep = f.readlines()[-2000:]
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(keep)
    except OSError:
        pass


def memory_status():
    """(percent of the whole computer's memory in use, total bytes) on Windows; None elsewhere or when unreadable."""
    if not IS_WIN:
        return None
    import ctypes

    class Status(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    status = Status()
    status.dwLength = ctypes.sizeof(Status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.dwMemoryLoad), int(status.ullTotalPhys)


def memory_load():
    """Percent of the whole computer's memory in use (Windows only; None elsewhere or when it cannot be read)."""
    status = memory_status()
    return status[0] if status else None


def private_bytes(pid):
    """Memory the process `pid` holds for itself (Windows; None elsewhere or when unreadable)."""
    if not IS_WIN or not pid:
        return None
    import ctypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
            (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                           "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                           "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    k32 = ctypes.WinDLL("kernel32")
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        c = Counters()
        c.cb = ctypes.sizeof(Counters)
        if not k32.K32GetProcessMemoryInfo(handle, ctypes.byref(c), c.cb):
            return None
        return int(c.PagefileUsage)
    finally:
        k32.CloseHandle(ctypes.c_void_p(handle))


def _log_release(load, which):
    path = os.path.join(tools.data_dir(), "memory-release.log")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{iso_time(time.time())}\t{load}%\t{which}\n")
        if os.path.getsize(path) > 200_000:
            with open(path, encoding="utf-8") as f:
                keep = f.readlines()[-2000:]
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(keep)
    except OSError:
        pass


def release_check(services, percent, load=None, sizes=None):
    """One pass: when the computer's memory use is at `percent` or more, let go of every running helper
    (services: {name: _Service}). The next search starts it again. The memory each helper held is kept in
    `sizes` ({name: bytes}, the most seen) so a reload can first check that it fits. Returns the names released."""
    if not percent or percent <= 0:
        return []
    load = memory_load() if load is None else load
    if load is None or load < percent:
        return []
    released = []
    for name, service in services.items():
        if service and service.running():
            held = private_bytes(service.pid()) if sizes is not None else None
            if held:  # a helper let go before its vectors loaded holds less: keep the larger number
                sizes[name] = max(held, sizes.get(name, 0))
            service.quit()
            _log_release(load, name)
            released.append(name)
    return released


def reload_check(services, state, percent, load=None, now=None, calm_checks=4, wait=600,
                 release_at=None, total=None):
    """One pass after a release: when memory use has been under `percent` for `calm_checks` passes in a row and
    `wait` seconds have passed since the last release, load the main helper again (it was in state["waiting"]).
    It waits instead while loading it would bring memory use within 5 points of `release_at` (state["sizes"]
    holds what it took before, `total` the computer's memory), so it is not let go again right after. Memory the
    DigUp app's own helper holds is part of the use, so a second copy loads only when there is room for it.
    The code helper is never loaded here: a prewarm there would read the main vectors a second time; the next
    code search starts it. A helper a search already started is only taken off the list. Returns the names loaded."""
    waiting = state.setdefault("waiting", set())
    if not waiting or not percent or percent <= 0:
        state["calm"] = 0
        return []
    load = memory_load() if load is None else load
    now = time.monotonic() if now is None else now
    if load is None or load >= percent:
        state["calm"] = 0
        return []
    state["calm"] = state.get("calm", 0) + 1
    if state["calm"] < calm_checks or now - state.get("released_at", now - wait) < wait:
        return []
    service = services.get("main")
    if "main" in waiting and service and not service.running():
        need = state.get("sizes", {}).get("main")
        if release_at and total and need and load + need * 100 / total >= release_at - 5:
            return []  # it would be let go again soon after: wait for more room
        _quietly(service.ask, {"op": "prewarm"})
        _log_release(load, "main\treload")
        loaded = ["main"]
    else:
        loaded = []
    waiting.clear()
    state["calm"] = 0
    return loaded


def _release_loop(services, percent, reload_at=RELOAD_DEFAULT, every=15):
    state = {"sizes": {}}
    while True:
        time.sleep(every)
        try:
            released = release_check(services, percent, sizes=state["sizes"])
            if released:
                state.setdefault("waiting", set()).update(released)
                state["released_at"] = time.monotonic()
                state["calm"] = 0
            else:
                memory = memory_status()
                reload_check(services, state, min(reload_at, percent - 1), load=memory and memory[0],
                             release_at=percent, total=memory and memory[1])
        except Exception:  # never let a failed check end the watch
            pass


def ask(request, timeout=600):
    """The server's reply to one request, or None when no server is running."""
    state = read_state()
    if not state:
        return None
    try:
        conn = Client(state["address"], authkey=bytes.fromhex(state["key"]))
    except (OSError, EOFError, KeyError, ValueError, AuthenticationError):  # not running (a stale serve.json)
        return None
    try:
        conn.send_bytes(json.dumps(request, ensure_ascii=False).encode("utf-8"))
        if not conn.poll(timeout):
            raise LfkError("timeout", f"the search service did not answer in {timeout} s")
        reply = json.loads(conn.recv_bytes().decode("utf-8"))
    except (OSError, EOFError):
        return None
    finally:
        conn.close()
    reply["_state"] = state
    return reply


def ask_index(request, index=None, autostart=True, timeout=600):
    """ask() for a server of this index (None: DigUp's own). With autostart, a missing server for DigUp's own index is
    started first (LFK_NO_AUTOSERVE=1 turns that off), so a search never falls back to the slow digup search."""
    state = read_state()
    if state and os.path.normcase(state.get("index") or "") != os.path.normcase(index or ""):
        return None
    reply = ask(request, timeout=timeout)
    if (reply is None and index is None and autostart and os.environ.get("LFK_NO_AUTOSERVE") != "1"
            and tools.locate("digup")["found"] and start_detached()):
        reply = ask(request, timeout=timeout)
    return reply


class _Service:
    """`digup search-service` as a child: one JSON request per line, one reply per line (event lines skipped)."""

    def __init__(self, digup, index, idle, code_roots=(), code_skipped=()):
        self.cmd = [digup, "search-service", "--encoder-idle", str(idle)] + (["--index", index] if index else [])
        for root in code_roots:
            self.cmd += ["--code-root", root]
        for root in code_skipped:
            self.cmd += ["--code-exclude", root]
        self.env = dict(os.environ, DIGUP_DEVICE="cpu")  # a short query embeds in milliseconds; no graphics memory
        self.lock = threading.Lock()
        self.p = None
        self.next_id = 0

    def _start(self):
        kwargs = {"creationflags": 0x08000000} if IS_WIN else {}
        self.p = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  env=self.env, **kwargs)
        _normal_priority(self.p.pid)
        ready = self.p.stdout.readline()
        if not ready:
            self.p = None
            raise LfkError("tool_failed", "digup search-service did not start")

    def ask(self, request):
        deadline = request.get("_deadline")
        remaining = max(0., deadline - time.monotonic()) if deadline is not None else -1
        if not self.lock.acquire(timeout=remaining):
            raise LfkError("timeout", "search request expired while waiting for the helper")
        try:
            if deadline is not None and time.monotonic() >= deadline:
                raise LfkError("timeout", "search request expired before execution")
            request = {k: v for k, v in request.items() if k != "_deadline"}
            if self.p is None or self.p.poll() is not None:
                self._start()
            self.next_id += 1
            request = dict(request, id=self.next_id)
            try:
                self.p.stdin.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
                self.p.stdin.flush()
                while True:
                    line = self.p.stdout.readline()
                    if not line:
                        raise OSError("stopped")
                    reply = json.loads(line.decode("utf-8"))
                    if reply.get("id") == self.next_id:
                        return reply
            except (OSError, ValueError):
                self.p = None  # started again on the next request
                raise LfkError("tool_failed", "digup search-service stopped")
        finally:
            self.lock.release()

    def running(self):
        return self.p is not None and self.p.poll() is None

    def pid(self):
        return self.p.pid if self.running() else None

    def quit(self):
        with self.lock:
            if self.p and self.p.poll() is None:
                try:
                    self.p.stdin.write(b'{"op":"quit"}\n')
                    self.p.stdin.flush()
                    self.p.wait(timeout=20)
                except (OSError, subprocess.TimeoutExpired):
                    self.p.kill()


def _code_folders(index):
    """Reuse the app's existing code selection, never index or change settings.

    A custom index is isolated from the app's folders. A missing code database is
    not created just because the app has a folder selection.
    """
    if index:
        return [], []
    from . import refresh
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    app_name = "DigUp" if IS_WIN or sys.platform == "darwin" else "digup"
    index_name = "index.noindex" if sys.platform == "darwin" else "index"
    if not os.path.isfile(os.path.join(base, app_name, index_name, "code.sqlite")):
        return [], []
    try:
        with open(refresh.settings_path(), encoding="utf-8") as f:
            settings = json.load(f)
        return list(settings.get("codeFolders") or []), list(settings.get("codeSkipped") or [])
    except (OSError, ValueError):
        return [], []


def _run_server(args):
    if sys.stdout is None:  # pythonw (the logon task): no console to write to
        sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")
    running = ask({"op": "ping"}, timeout=10)
    if running:
        raise LfkError("already_running", "the search service is already running", pid=running.get("pid"))
    _normal_priority()
    digup = tools.require("digup")
    index = abspath(args.index) if args.index else None
    code_roots, code_skipped = _code_folders(index)
    service = _Service(digup, index, args.idle)
    service._start()
    # Each helper serializes its requests. Give code its own helper so the two
    # independent indexes can search together. Its main vectors stay unloaded.
    code_service = _Service(digup, index, args.idle, code_roots, code_skipped) if code_roots else None
    key = secrets.token_bytes(32)
    address = r"\\.\pipe\local-file-kit-" + secrets.token_hex(8) if IS_WIN else os.path.join(tools.data_dir(), "serve.sock")
    os.makedirs(tools.data_dir(), exist_ok=True)
    if not IS_WIN and os.path.exists(address):
        os.unlink(address)
    listener = Listener(address, authkey=key)
    state = {"address": address, "key": key.hex(), "pid": os.getpid(), "started": iso_time(time.time()),
             "index": index, "digup": digup, "idle": args.idle, "code": bool(code_roots)}
    fd = os.open(state_path(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f)
    time.sleep(2)  # two starts at once (parallel searches): the one whose serve.json was overwritten steps aside
    current = read_state()
    if current and current.get("pid") != os.getpid():
        service.quit()
        if code_service:
            code_service.quit()
        os._exit(0)
    counts = {"searches": 0}
    names = NameList()
    threading.Thread(target=names.keep_fresh, daemon=True).start()
    if IS_WIN and args.release_at > 0:
        threading.Thread(target=_release_loop,
                         args=({"main": service, "code": code_service}, args.release_at, getattr(args, "reload_at", RELOAD_DEFAULT)),
                         daemon=True).start()

    def stop():
        try:
            if read_state() == state:
                os.unlink(state_path())
        except OSError:
            pass
        service.quit()
        if code_service:
            code_service.quit()
        os._exit(0)

    def handle(conn):
        try:
            request = json.loads(conn.recv_bytes().decode("utf-8"))
            op = request.get("op")
            if op == "ping":
                reply = {"ok": True, "pid": os.getpid()}
            elif op == "stop":
                conn.send_bytes(json.dumps({"ok": True, "stopped": os.getpid()}).encode("utf-8"))
                conn.close()
                stop()
            elif op == "names":
                reply = names.find(request)
            elif op in ("search", "status", "text", "reload"):
                if op == "search":
                    counts["searches"] += 1
                started = time.monotonic()
                reply = _route_index(service, code_service, request)
                if op == "search":
                    _log_search(time.monotonic() - started, "code" if request.get("code") else "main")
                if op == "status":
                    reply["names"] = names.summary()
            else:
                reply = {"ok": False, "error": f"unknown op {op}"}
        except LfkError as e:
            reply = e.to_json()
        except (OSError, EOFError, ValueError):
            return
        try:
            reply.update(pid=os.getpid(), searches=counts["searches"])
            conn.send_bytes(json.dumps(reply, ensure_ascii=False).encode("utf-8"))
        except OSError:
            pass
        finally:
            conn.close()

    # Load the vectors now: the first search is quick, and the index is in the system's file cache for later loads.
    threading.Thread(target=lambda: _quietly(service.ask, {"op": "prewarm"}), daemon=True).start()
    while True:
        try:
            conn = listener.accept()
        except (OSError, EOFError, AuthenticationError):  # a client that failed the key check
            continue
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


def _route_index(service, code_service, request):
    op = request.get("op")
    if request.get("code") and op in ("search", "text"):
        if code_service:
            return code_service.ask(request)
        return {"hits": [], "meaning": False} if op == "search" else {"text": None}
    reply = service.ask(request)
    if code_service and op in ("status", "reload"):
        code_reply = code_service.ask(request)
        for key, value in code_reply.items():
            if key.startswith("code_"):
                reply[key] = value
        if op == "status":
            reply["code_encoder"] = code_reply.get("encoder")
    return reply


class NameList:
    """File names on drives Everything does not index (a cloud drive such as Google Drive's G:), walked now and every
    30 minutes, so 'q' finds names there too."""

    EVERY = 1800

    def __init__(self):
        self.items = []
        self.drives = []
        self.walked = None
        self.lock = threading.Lock()

    def keep_fresh(self):
        while True:
            try:
                self._walk()
            except Exception:  # a drive that went away mid-walk: try again next time
                pass
            time.sleep(self.EVERY)

    def _walk(self):
        from . import find
        from .quick import _compact
        es = tools.locate("everything")
        if not IS_WIN or not es.get("found"):
            return
        drives = [d + ":\\" for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.isdir(d + ":\\")]
        drives = [d for d in drives if not find._root_indexed(es["path"], d)]
        items = []
        for d in drives:
            stack = [d]
            while stack:
                folder = stack.pop()
                try:
                    with os.scandir(folder) as it:
                        for e in it:
                            try:
                                st = e.stat(follow_symlinks=False)
                                is_dir = e.is_dir(follow_symlinks=False)
                            except OSError:
                                continue
                            if is_dir and e.name.lower() not in find.SKIP_DIRS \
                                    and not getattr(st, "st_file_attributes", 0) & 0x400:
                                stack.append(e.path)
                            items.append((e.path, e.name.lower(), is_dir, None if is_dir else st.st_size, st.st_mtime,
                                          _compact(e.name), _compact(folder)))
                except OSError:
                    continue
        with self.lock:
            self.items, self.drives, self.walked = items, drives, time.time()

    def summary(self):
        with self.lock:
            return {"drives": self.drives, "entries": len(self.items), "walked": iso_time(self.walked)}

    def find(self, request):
        from .quick import _compact
        words = [_compact(w) for w in request.get("words", []) if w]
        exts = set(request.get("exts") or [])
        after, before = request.get("after"), request.get("before")
        with self.lock:
            items, drives, walked = self.items, self.drives, self.walked
        hits = []
        for path, name, is_dir, size, mtime, compact_name, compact_parent in items:
            n = sum(1 if w in compact_name else .4 if w in compact_parent else 0
                    for w in words)
            if not n:
                continue
            if exts and (is_dir or os.path.splitext(name)[1].lstrip(".") not in exts):
                continue
            if (after and mtime < after) or (before and mtime >= before):
                continue
            hits.append((n, mtime, path, is_dir, size))
        hits.sort(key=lambda h: (-h[0], -h[1]))
        return {"ok": True, "drives": drives, "walked": iso_time(walked),
                "items": [{"path": p, "is_dir": d, "size": z, "mtime": m} for n, m, p, d, z in hits[:request.get("limit", 300)]]}


def start_detached(wait=30):
    """Start 'lfk serve' in the background (no window) and wait until it answers. True when it does."""
    exe, argv = _task_command(argparse.Namespace(idle=IDLE_DEFAULT, release_at=RELEASE_DEFAULT, reload_at=RELOAD_DEFAULT, index=None))
    kwargs = {"creationflags": 0x00000008 | 0x00000200 | 0x08000000} if IS_WIN else {"start_new_session": True}
    try:
        subprocess.Popen([exe] + argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True, **kwargs)
    except OSError:
        return False
    end = time.time() + wait
    while time.time() < end:
        if ask({"op": "ping"}, timeout=5):
            return True
        time.sleep(0.3)
    return False


def _quietly(fn, *a):
    try:
        fn(*a)
    except LfkError:
        pass


# --------------------------------------------------------------------------------------------- autostart


def _task_command(args):
    exe = sys.executable
    if IS_WIN and os.path.basename(exe).lower() == "python.exe":
        windowless = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.isfile(windowless):
            exe = windowless
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lfk.py")
    return exe, ["-I", script, "serve", "--idle", str(args.idle), "--release-at", str(args.release_at), "--reload-at", str(getattr(args, "reload_at", RELOAD_DEFAULT))] + (["--index", abspath(args.index)] if args.index else [])


def _ps(script):
    p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                       creationflags=0x08000000, timeout=60)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def _quote(text):
    return "'" + text.replace("'", "''") + "'"


def _autostart(args):
    if not IS_WIN:
        raise LfkError("not_supported", "--autostart is for Windows; elsewhere start 'lfk.py serve' from a login item "
                       "(macOS) or a systemd user service (Linux)", exit_code=2)
    if args.autostart == "off":
        rc, out, err = _ps(f"Unregister-ScheduledTask -TaskName {_quote(TASK_NAME)} -Confirm:$false")
        return {"ok": True, "autostart": "off", "task": TASK_NAME, "removed": rc == 0}
    exe, argv = _task_command(args)
    arguments = subprocess.list2cmdline(argv)
    script = "\n".join([
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8",
        "$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name",
        f"$a = New-ScheduledTaskAction -Execute {_quote(exe)} -Argument {_quote(arguments)}",
        "$t = New-ScheduledTaskTrigger -AtLogOn -User $user",
        "$p = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited",
        "$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries "
        "-DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew",
        f"Register-ScheduledTask -TaskName {_quote(TASK_NAME)} -Action $a -Trigger $t -Principal $p -Settings $s "
        "-Description 'local-file-kit: keeps DigUp search ready (lfk.py serve)' -Force | Out-Null",
    ])
    rc, out, err = _ps(script)
    if rc != 0:
        raise LfkError("tool_failed", "could not add the logon task", stderr=err.strip()[-600:])
    return {"ok": True, "autostart": "on", "task": TASK_NAME, "runs": f"{exe} {arguments}",
            "note": f"starts at the next logon; to start it now: schtasks /Run /TN {TASK_NAME}"}


# --------------------------------------------------------------------------------------------- command


def cmd_serve(args):
    if args.autostart:
        return _autostart(args)
    if args.stop:
        reply = ask({"op": "stop"}, timeout=60)
        return {"ok": True, "stopped": bool(reply), **({} if reply else {"note": "it was not running"})}
    if args.status:
        reply = ask({"op": "status"}, timeout=60)
        if not reply:
            return {"ok": True, "running": False,
                    "start_with": "lfk.py serve  (or, on Windows, schtasks /Run /TN " + TASK_NAME + " after --autostart on)"}
        state = reply.pop("_state")
        return {"ok": True, "running": True, "pid": state["pid"], "started": state["started"], "idle": state["idle"],
                "index": state["index"] or "DigUp's own", "searches": reply.get("searches"),
                "vectors_loaded": reply.get("vectors"), "encoder": reply.get("encoder"), "files": reply.get("files"),
                "searchable": reply.get("searchable"), "code_vectors_loaded": reply.get("code_vectors"),
                "code_encoder": reply.get("code_encoder"),
                "code_enabled": state.get("code", False)}
    _run_server(args)
