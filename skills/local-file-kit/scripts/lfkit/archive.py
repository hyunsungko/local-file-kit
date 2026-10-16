"""archive: create, list, test and extract archives. 7-Zip when installed; Python's zipfile for .zip otherwise.

Nothing here deletes or overwrites: create refuses an existing archive, extract skips files that already exist.
"""
import os
import re
import shutil
import zipfile

from . import tools
from .util import IS_WIN, LfkError, abspath, run


def _seven():
    loc = tools.locate("7zip")
    return loc["path"] if loc["found"] else None


def _check_7z(rc, err, what):
    if rc == 1:
        return "7-Zip finished with warnings (some files may have been locked or unreadable)"
    if rc != 0:
        raise LfkError("tool_failed", f"7-Zip {what} failed with exit code {rc}", stderr=err.strip()[-500:])
    return None


def cmd_archive(args):
    return {"create": _create, "list": _list, "test": _test, "extract": _extract}[args.action](args)


def _create(args):
    out = abspath(args.archive)
    sources = [abspath(s) for s in args.sources]
    if not sources:
        raise LfkError("bad_argument", "give one or more files or folders to put in the archive", exit_code=2)
    for s in sources:
        if not os.path.exists(s):
            raise LfkError("not_found", f"no such file or folder: {s}", exit_code=2)
    ext = os.path.splitext(out)[1].lower()
    if not ext:
        # 7-Zip would add ".7z" itself and then update an existing archive of that name
        raise LfkError("bad_argument", f"give the archive an extension, e.g. {out}.7z or {out}.zip", exit_code=2)
    if os.path.exists(out):
        raise LfkError("exists", f"{out} already exists; choose another name (archives are never overwritten)", exit_code=2)
    for s in sources:
        if os.path.isdir(s) and _inside(out, s):
            raise LfkError("bad_argument", "put the archive outside the folders being archived "
                           "(it would try to pack itself)", exit_code=2)
    seven = _seven()
    if seven:
        rc, so, err = run([seven, "a", "-sccUTF-8", "-bso0", "-bsp0", "-y", out] + sources, timeout=args.max_seconds)
        warn = _check_7z(rc, err, "create")
        res = {"ok": True, "engine": "7zip", "archive": out, "bytes": os.path.getsize(out)}
        if warn:
            res["warning"] = warn
        return res
    if ext != ".zip":
        tools.require("7zip")
    count = 0
    with zipfile.ZipFile(out, "x", zipfile.ZIP_DEFLATED) as z:
        for s in sources:
            base = os.path.dirname(s.rstrip("\\/"))
            if os.path.isfile(s):
                z.write(s, os.path.relpath(s, base))
                count += 1
                continue
            for d, _, files in os.walk(s):
                z.write(d, os.path.relpath(d, base))
                for f in files:
                    p = os.path.join(d, f)
                    z.write(p, os.path.relpath(p, base))
                    count += 1
    return {"ok": True, "engine": "zipfile", "archive": out, "files": count, "bytes": os.path.getsize(out),
            "note": "7-Zip not found: made a .zip with Python. " + " / ".join(tools.install_advice("7zip")["install"])}


def _list(args):
    arc = abspath(args.archive)
    if not os.path.isfile(arc):
        raise LfkError("not_found", f"no such archive: {arc}", exit_code=2)
    seven = _seven()
    if seven:
        rc, out, err = run([seven, "l", "-slt", "-ba", "-sccUTF-8", arc], timeout=args.max_seconds)
        _check_7z(rc, err, "list")
        entries = []
        for block in re.split(r"\r?\n\r?\n", out.strip()):
            kv = dict(l.split(" = ", 1) for l in block.splitlines() if " = " in l)
            if "Path" not in kv:
                continue
            entries.append({"path": kv["Path"], "is_dir": "D" in kv.get("Attributes", ""),
                            "size": int(kv["Size"]) if kv.get("Size", "").isdigit() else None,
                            "modified": kv.get("Modified") or None, "encrypted": kv.get("Encrypted") == "+"})
        engine = "7zip"
    else:
        if not zipfile.is_zipfile(arc):
            tools.require("7zip")
        with zipfile.ZipFile(arc) as z:
            entries = [{"path": i.filename, "is_dir": i.is_dir(), "size": i.file_size,
                        "modified": "%04d-%02d-%02d %02d:%02d:%02d" % i.date_time, "encrypted": bool(i.flag_bits & 1)}
                       for i in z.infolist()]
        engine = "zipfile"
    total = len(entries)
    return {"ok": True, "engine": engine, "archive": arc, "entries": total,
            "files": entries[:args.limit], **({"truncated": f"showing {args.limit} of {total}"} if total > args.limit else {})}


def _test(args):
    arc = abspath(args.archive)
    if not os.path.isfile(arc):
        raise LfkError("not_found", f"no such archive: {arc}", exit_code=2)
    seven = _seven()
    if seven:
        rc, out, err = run([seven, "t", "-sccUTF-8", "-bsp0", arc], timeout=args.max_seconds)
        return {"ok": True, "engine": "7zip", "archive": arc, "intact": rc == 0,
                **({"detail": (err or out).strip()[-500:]} if rc != 0 else {})}
    if not zipfile.is_zipfile(arc):
        tools.require("7zip")
    with zipfile.ZipFile(arc) as z:
        bad = z.testzip()
    return {"ok": True, "engine": "zipfile", "archive": arc, "intact": bad is None, **({"first_bad": bad} if bad else {})}


def _extract(args):
    arc = abspath(args.archive)
    if not os.path.isfile(arc):
        raise LfkError("not_found", f"no such archive: {arc}", exit_code=2)
    if not args.to:
        raise LfkError("bad_argument", "give --to <folder> to extract into", exit_code=2)
    dest = abspath(args.to)
    os.makedirs(dest, exist_ok=True)
    seven = _seven()
    if seven:
        rc, out, err = run([seven, "x", "-sccUTF-8", "-bso0", "-bsp0", "-aos", f"-o{dest}", arc], timeout=args.max_seconds)
        warn = _check_7z(rc, err, "extract")
        res = {"ok": True, "engine": "7zip", "archive": arc, "to": dest, "existing_files": "skipped (never overwritten)"}
        if warn:
            res["warning"] = warn
        return res
    if not zipfile.is_zipfile(arc):
        tools.require("7zip")
    done = skipped = 0
    with zipfile.ZipFile(arc) as z:
        for info in z.infolist():
            target = _safe_target(dest, info.filename)
            if target is None:
                continue
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            try:
                with z.open(info) as src, open(target, "xb") as dst:  # "x": never write over an existing file
                    shutil.copyfileobj(src, dst)
                done += 1
            except FileExistsError:
                skipped += 1
    return {"ok": True, "engine": "zipfile", "archive": arc, "to": dest, "extracted": done, "skipped_existing": skipped}


def _safe_target(dest, name):
    """Where a zip entry goes inside dest: '.', '..' and drive parts dropped, characters Windows forbids replaced."""
    parts = [p for p in re.split(r"[\\/]", name) if p not in ("", ".", "..")]
    if IS_WIN:
        parts = [re.sub(r'[:<>|"?*]', "_", p).rstrip(" .") for p in parts]
        parts = [p for p in parts if p]
    return os.path.join(dest, *parts) if parts else None


def _inside(path, folder):
    p = os.path.normcase(os.path.abspath(path))
    f = os.path.normcase(os.path.abspath(folder)).rstrip("\\/")
    return p.startswith(f + os.sep)
