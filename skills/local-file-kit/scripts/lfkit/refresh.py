"""refresh: bring the DigUp app's index up to date with the folders chosen in the app - only what changed - without
the app running. It runs the helper the app runs for this (`digup index-service --backfill`, same folders and skips),
then tells 'serve' to reload. Nothing is indexed from scratch: unchanged files are left as they are, and a folder that
is not there (an unplugged drive) keeps what was indexed from it.
"""
import argparse
import json
import os
import subprocess
import threading
import time

from . import content, serve, tools
from .util import IS_MAC, IS_WIN, LfkError, iso_time

TASK_NAME = "LocalFileKit-IndexRefresh"


def settings_path():
    if IS_WIN:
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming"),
                            "com.abdurrahim.DigUp", "settings.json")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                        "com.abdurrahim.DigUp", "settings.json")


def last_path():
    return os.path.join(tools.data_dir(), "refresh-last.json")


def _arguments(settings):
    args = ["index-service", "--backfill", "--linger", "5"]
    for folder in settings.get("skipped") or []:
        args += ["--exclude", folder]
    for ext in settings.get("skipTypes") or []:
        args += ["--exclude-ext", ext]
    for folder in settings.get("codeFolders") or []:
        args += ["--code-root", folder]
    for folder in settings.get("codeSkipped") or []:
        args += ["--code-exclude", folder]
    return args + list(settings.get("folders") or [])


def _refresh(args):
    if IS_MAC:
        raise LfkError("not_supported", "on macOS the DigUp app keeps its index current itself", exit_code=2)
    digup = tools.require("digup")
    try:
        with open(settings_path(), encoding="utf-8") as f:
            settings = json.load(f)
    except (OSError, ValueError):
        raise LfkError("not_found", "the DigUp app's settings were not found: choose folders in the DigUp app first",
                       exit_code=2, looked_in=settings_path())
    if not settings.get("folders"):
        raise LfkError("not_found", "no folders are chosen in the DigUp app", exit_code=2)
    if content.app_running():
        return {"ok": True, "skipped": "the DigUp app is running and keeps its index current itself"}
    started = time.time()
    kwargs = {"creationflags": 0x08000000 | 0x00004000} if IS_WIN else {}  # no window, below-normal priority
    p = subprocess.Popen([digup] + _arguments(settings), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, **kwargs)
    report = {"syncs": [], "states": {}, "rest": {}, "files": 0, "errors": [], "missing": []}
    stop_reason = []

    def watch():  # stop at the time limit, or when the app starts (it indexes the same folders itself)
        deadline = started + args.max_hours * 3600
        while p.poll() is None:
            time.sleep(60)
            why = "time limit" if time.time() > deadline else ("the DigUp app started" if content.app_running() else None)
            if why:
                stop_reason.append(why)
                try:
                    p.stdin.write(b"stop\n")
                    p.stdin.flush()
                    p.wait(timeout=600)
                except (OSError, ValueError):  # ValueError: the main thread already closed stdin
                    pass
                except subprocess.TimeoutExpired:  # it did not stop: do not run past the limit
                    p.kill()
                return

    threading.Thread(target=watch, daemon=True).start()
    events = 0
    for line in p.stdout:  # stdin stays open: its end would stop the helper
        try:
            event = json.loads(line.decode("utf-8"))
        except ValueError:
            continue
        events += 1
        kind = event.get("event")
        if kind == "sync":
            report["syncs"].append({k: event.get(k) for k in ("code", "added", "changed", "moved", "removed",
                                                              "unchanged", "ms")})
        elif kind == "file":
            report["files"] += 1
        elif kind == "summary":
            target = report["rest"] if event.get("rest") else report["states"]
            for state, n in (event.get("states") or {}).items():
                target[state] = target.get(state, 0) + n
        elif kind == "error":
            report["errors"].append(str(event.get("message"))[:300])
        elif kind == "missing" and (event.get("folders") or event.get("unreadable")):
            report["missing"] = (event.get("folders") or []) + (event.get("unreadable") or [])
        elif kind == "exit":
            break
    try:
        p.stdin.close()
        p.wait(timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        p.kill()
    if not events and p.returncode:
        report["errors"].append(f"digup index-service ended with code {p.returncode} before it reported anything")
    reload = serve.ask({"op": "reload"}, timeout=600)
    out = {"ok": not report["errors"], "started": iso_time(started),
           "minutes": round((time.time() - started) / 60, 1), **report,
           "service_reloaded": bool(reload and reload.get("ok")),
           "note": "files that changed are read again; unchanged ones are kept"}
    if stop_reason:
        out["stopped"] = stop_reason[0] + " (the rest is done next time)"
    if not report["missing"]:
        out.pop("missing")
    return out


def cmd_refresh(args):
    if args.autostart:
        return _autostart(args)
    if args.last:
        try:
            with open(last_path(), encoding="utf-8") as f:
                return {"ok": True, "last": json.load(f)}
        except (OSError, ValueError):
            return {"ok": True, "last": None, "note": "no refresh has run yet"}
    try:
        out = _refresh(args)
    except LfkError as e:
        out = e.to_json()
        _save(out)
        raise
    if "skipped" not in out:  # keep the last real run for --last
        _save(out)
    return out


def _save(out):
    try:
        os.makedirs(tools.data_dir(), exist_ok=True)
        with open(last_path(), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
    except OSError:
        pass


def _autostart(args):
    if not IS_WIN:
        raise LfkError("not_supported", "--autostart is for Windows; elsewhere run 'lfk.py refresh' from cron",
                       exit_code=2)
    if args.autostart == "off":
        rc, _, _ = serve._ps(f"Unregister-ScheduledTask -TaskName {serve._quote(TASK_NAME)} -Confirm:$false")
        return {"ok": True, "autostart": "off", "task": TASK_NAME, "removed": rc == 0}
    exe, argv = serve._task_command(argparse.Namespace(idle=0, release_at=0, index=None))
    argv = argv[:2] + ["refresh", "--max-hours", str(args.max_hours)]
    arguments = subprocess.list2cmdline(argv)
    script = "\n".join([
        "$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name",
        f"$a = New-ScheduledTaskAction -Execute {serve._quote(exe)} -Argument {serve._quote(arguments)}",
        f"$t = New-ScheduledTaskTrigger -Daily -At {serve._quote(args.at)}",
        "$p = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited",
        f"$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours {args.max_hours + 1}) "
        "-StartWhenAvailable -MultipleInstances IgnoreNew",
        f"Register-ScheduledTask -TaskName {serve._quote(TASK_NAME)} -Action $a -Trigger $t -Principal $p -Settings $s "
        "-Description 'local-file-kit: index what changed in the DigUp folders (lfk.py refresh)' -Force | Out-Null",
    ])
    rc, _, err = serve._ps(script)
    if rc != 0:
        raise LfkError("tool_failed", "could not add the daily task", stderr=err.strip()[-600:])
    return {"ok": True, "autostart": "on", "task": TASK_NAME, "at": args.at, "runs": f"{exe} {arguments}",
            "check_with": "lfk.py refresh --last"}
