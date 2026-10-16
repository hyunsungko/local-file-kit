"""copy: copy a folder (or one file) to another place. Robocopy on Windows, Python elsewhere.

Preview by default; --execute copies. It never deletes anything (no /MIR, /PURGE or /MOV) and, unless
--overwrite-changed is given, never replaces a file that already exists at the destination.
"""
import os
import re
import shutil

from . import tools
from .util import IS_WIN, LfkError, abspath, remove_quietly, run, temp_path


def cmd_copy(args):
    src = abspath(args.source)
    dst = abspath(args.dest)
    if not os.path.exists(src):
        raise LfkError("not_found", f"no such file or folder: {src}", exit_code=2)
    if os.path.isdir(src) and _inside(dst, src):
        raise LfkError("bad_argument", "the destination is inside the source folder", exit_code=2)
    if os.path.isfile(src) and os.path.isdir(os.path.join(dst, os.path.basename(src))):
        raise LfkError("conflict", f"{os.path.join(dst, os.path.basename(src))} is a folder; the file cannot be copied "
                       "there", exit_code=2)
    loc = tools.locate("robocopy") if IS_WIN else {"found": False}
    if loc["found"]:
        res = _robocopy(loc["path"], src, dst, args)
    else:
        res = _python(src, dst, args)
    res["mode"] = "executed" if args.execute else "preview"
    if not args.execute:
        res["next_step"] = "Nothing was copied. Run again with --execute to copy."
    return res


def _inside(path, folder):
    p = os.path.normcase(path)
    f = os.path.normcase(folder.rstrip("\\/"))
    return p == f or p.startswith(f + os.sep)


def _robocopy(exe, src, dst, args):
    if os.path.isfile(src):
        cmd = [exe, os.path.dirname(src), dst, os.path.basename(src)]
    else:
        cmd = [exe, src, dst, "/E"]
    cmd += ["/R:1", "/W:1", "/NP", "/NJH", "/NJS", "/NDL", "/NC", "/BYTES", "/FP", "/XJ", "/COPY:DAT", "/DCOPY:DAT"]
    if not args.overwrite_changed:
        cmd += ["/XC", "/XN", "/XO"]
    if not args.execute:
        cmd.append("/L")
    log = temp_path(".log")
    cmd.append("/UNILOG:" + log)
    try:
        rc, _, err = run(cmd, timeout=args.max_seconds)
        try:
            with open(log, encoding="utf-16") as f:
                text = f.read()
        except (FileNotFoundError, UnicodeError):
            text = ""
    finally:
        remove_quietly(log)
    files = []
    total = 0
    errors = []
    for line in text.splitlines():
        m = re.match(r"^\s*(\d+)\t(.+)$", line.strip("\r"))
        if m and not m.group(2).endswith("\\"):
            size = int(m.group(1))
            files.append({"path": m.group(2).strip(), "size": size})
            total += size
        elif re.search(r"(ERROR|오류)\s+\d+", line):
            errors.append(line.strip())
    res = {"ok": rc < 8, "engine": "robocopy", "source": src, "dest": dst, "files": len(files), "bytes": total,
           "list": files[:args.limit], "exit_code": rc}
    if len(files) > args.limit:
        res["truncated"] = f"listing {args.limit} of {len(files)} files"
    if errors:
        res["errors"] = errors[:50]
    if rc >= 8:
        res.update(error="tool_failed", message=f"robocopy reported failures (exit code {rc})")
    elif rc & 4:
        res.update(ok=False, error="mismatch", message="some names are a file on one side and a folder on the other; "
                   "those were not copied (the list may include them)")
    return res


def _python(src, dst, args):
    plan = []
    if os.path.isfile(src):
        pairs = [(src, os.path.join(dst, os.path.basename(src)))]
    else:
        pairs = []
        for d, dirs, files in os.walk(src):
            dirs[:] = [x for x in dirs if not os.path.islink(os.path.join(d, x))]
            rel = os.path.relpath(d, src)
            for f in files:
                pairs.append((os.path.join(d, f), os.path.normpath(os.path.join(dst, rel, f))))
    for s, t in pairs:
        if os.path.exists(t):
            if not args.overwrite_changed:
                continue
            ss, ts = os.stat(s), os.stat(t)
            if ss.st_size == ts.st_size and int(ss.st_mtime) == int(ts.st_mtime):
                continue
        plan.append((s, t, os.path.getsize(s)))
    errors = []
    if args.execute:
        for s, t, _ in plan:
            try:
                os.makedirs(os.path.dirname(t), exist_ok=True)
                shutil.copy2(s, t)
            except OSError as e:
                errors.append(f"{s}: {e}")
    res = {"ok": not errors, "engine": "python", "source": src, "dest": dst, "files": len(plan),
           "bytes": sum(p[2] for p in plan), "list": [{"path": s, "size": n} for s, _, n in plan[:args.limit]]}
    if len(plan) > args.limit:
        res["truncated"] = f"listing {args.limit} of {len(plan)} files"
    if errors:
        res["errors"] = errors[:50]
    return res
