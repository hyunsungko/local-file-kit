"""find: file and folder names. Everything (es.exe) when it can, a folder walk otherwise."""
import fnmatch
import json
import os
import re
import time

from . import tools
from .util import IS_WIN, LfkError, abspath, filetime_to_iso, iso_time, parse_date, parse_size, remove_quietly, run, temp_path

SKIP_DIRS = {"$recycle.bin", "system volume information", "$windows.~bt", "$windows.~ws", "node_modules", ".git"}


def _filters(args):
    exts = [e.strip().lstrip(".").lower() for e in (args.ext or "").split(",") if e.strip()]
    return {
        "exts": exts,
        "type": args.type,
        "min": parse_size(args.min_size) if args.min_size else None,
        "max": parse_size(args.max_size) if args.max_size else None,
        "after": parse_date(args.after) if args.after else None,
        "before": parse_date(args.before) if args.before else None,
    }


def _keep(item, f, mtime):
    if f["type"] == "file" and item["is_dir"]:
        return False
    if f["type"] == "folder" and not item["is_dir"]:
        return False
    if f["exts"] and (item["is_dir"] or os.path.splitext(item["name"])[1].lstrip(".").lower() not in f["exts"]):
        return False
    size = item.get("size")
    if f["min"] is not None and (size is None or size < f["min"]):
        return False
    if f["max"] is not None and (size is None or size > f["max"]):
        return False
    if f["after"] is not None and (mtime is None or mtime < f["after"]):
        return False
    if f["before"] is not None and (mtime is None or mtime >= f["before"]):
        return False
    return True


def _es_query(args, f):
    parts = []
    if f["type"] == "file":
        parts.append("file:")
    elif f["type"] == "folder":
        parts.append("folder:")
    if f["exts"]:
        parts.append("ext:" + ";".join(f["exts"]))
    if f["min"] is not None:
        parts.append(f"size:>={f['min']}")
    if f["max"] is not None:
        parts.append(f"size:<={f['max']}")
    if args.after:
        parts.append(f"dm:>={args.after[:10]}")
    if args.before:
        parts.append(f"dm:<{args.before[:10]}")
    return parts


def _es_run(es, root, words, limit, sort):
    out = temp_path(".json")
    cmd = [es]
    if root:
        cmd += ["-path", root]
    cmd += list(words)
    cmd += ["-size", "-dm", "-n", str(limit), "-export-json", out]
    if sort:
        cmd += ["-sort", sort]
    try:
        rc, _, err = run(cmd, timeout=120)
        if rc == 8:
            raise LfkError("everything_not_running", "Everything is installed but not running; start Everything "
                           "(it must stay running in the background) or use --engine walk with --root", exit_code=3)
        if rc != 0:
            raise LfkError("tool_failed", f"es.exe exited with code {rc}: {err.strip()[:300]}")
        try:
            with open(out, encoding="utf-8-sig") as fh:
                text = fh.read().strip()
        except FileNotFoundError:
            text = ""
        rows = json.loads(text) if text else []
    finally:
        remove_quietly(out)
    items = []
    for r in rows:
        p = r.get("filename", "")
        is_dir = p.endswith("\\") or p.endswith("/")
        p = p.rstrip("\\/") if is_dir else p
        mtime_iso = filetime_to_iso(r.get("date_modified"))
        items.append({"path": p, "name": os.path.basename(p), "is_dir": is_dir,
                      "size": r.get("size"),
                      "modified": mtime_iso, "_mtime": (int(r["date_modified"]) / 1e7 - 11644473600) if r.get("date_modified") else None})
    return items


def _root_indexed(es, root):
    """Everything returns nothing for folders it does not index (network, cloud, FAT). Detect that."""
    try:
        has_children = any(True for _ in os.scandir(root))
    except OSError:
        return True  # let es report whatever it reports
    if not has_children:
        return True
    return bool(_es_run(es, root, [], 1, None))


def _match_fn(query, regex, case):
    if regex is not None:
        rx = re.compile(regex, 0 if case else re.I)
        return lambda name, path: bool(rx.search(name))
    terms = [t for t in (query or "").split() if t]
    if not case:
        terms = [t.lower() for t in terms]

    def match(name, path):
        n = name if case else name.lower()
        p = path if case else path.lower()
        for t in terms:
            target = p if ("\\" in t or "/" in t) else n
            if any(c in t for c in "*?"):
                if not fnmatch.fnmatchcase(target, t):
                    return False
            elif t not in target:
                return False
        return True

    return match


def _walk(roots, query, regex, case, f, limit, max_seconds):
    match = _match_fn(query, regex, case)
    found, scanned, truncated = [], 0, None
    start = time.monotonic()
    stack = list(roots)
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                scanned += 1
                if scanned % 2000 == 0 and time.monotonic() - start > max_seconds:
                    truncated = f"stopped after {max_seconds} s; narrow --root or raise --max-seconds"
                    stack = []
                    break
                try:
                    is_dir = e.is_dir(follow_symlinks=False)
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if is_dir:
                    if e.name.lower() in SKIP_DIRS or (IS_WIN and getattr(st, "st_file_attributes", 0) & 0x400):
                        pass  # do not descend into reparse points (junctions, cloud mounts)
                    else:
                        stack.append(e.path)
                if not match(e.name, e.path):
                    continue
                item = {"path": e.path, "name": e.name, "is_dir": is_dir, "size": None if is_dir else st.st_size,
                        "modified": iso_time(st.st_mtime)}
                if _keep(item, f, st.st_mtime):
                    found.append(item)
                    if len(found) >= limit:
                        truncated = f"limit {limit} reached"
                        stack = []
                        break
    return found, scanned, truncated


SORTS = {"name": "name", "path": "path", "size": "size-descending", "modified": "date-modified-descending"}


def _sort(items, how):
    if how == "name":
        items.sort(key=lambda i: i["name"].lower())
    elif how == "path":
        items.sort(key=lambda i: i["path"].lower())
    elif how == "size":
        items.sort(key=lambda i: i.get("size") or -1, reverse=True)
    elif how == "modified":
        items.sort(key=lambda i: i.get("modified") or "", reverse=True)


def cmd_find(args):
    f = _filters(args)
    roots = [os.path.realpath(abspath(r)) for r in (args.root or [])]  # long names, as the tools report them
    for r in roots:
        if not os.path.isdir(r):
            raise LfkError("not_found", f"--root is not a folder: {r}", exit_code=2)
    engine = args.engine
    notes = []
    es_loc = tools.locate("everything") if engine in ("auto", "everything") else {"found": False}
    walk_roots = []
    items = []
    used = None
    if es_loc.get("found"):
        es = es_loc["path"]
        if args.regex:  # Everything's regex: function, so the filters below still narrow the search inside Everything
            # es.exe splits a search on spaces even inside quotes; \x20 is a space to the regex engine
            words = ["regex:" + args.query.replace(" ", "\\x20")]
        else:
            words = args.query.split() if args.query else []
        if args.case:
            words = ["-case"] + words
        words += _es_query(args, f)
        targets = roots or [None]
        try:
            for r in targets:
                if r and engine == "auto" and not _root_indexed(es, r):
                    walk_roots.append(r)
                    notes.append(f"Everything does not index {r} (network, cloud or non-NTFS); walked it instead")
                    continue
                got = _es_run(es, r, words, args.limit, SORTS.get(args.sort))
                items += [i for i in got if _keep(i, f, i.get("_mtime"))]
            used = "everything"
        except LfkError as e:
            if engine == "everything" or e.code != "everything_not_running" or not roots:
                raise
            notes.append(e.message + " -> walked the folders instead")
            walk_roots = roots
            items = []
    elif engine == "everything":
        tools.require("everything")
    else:
        if not roots:
            adv = tools.install_advice("everything")
            raise LfkError("need_root", "Everything is not available here, so give one or more --root folders to walk "
                           "(walking a whole drive is slow)", exit_code=2, everything=adv)
        walk_roots = roots
        if tools.PLATFORM == "windows" and engine == "auto":
            notes.append("Everything not found: walked the folders (much slower). " + " / ".join(tools.install_advice("everything")["install"]))
    scanned = None
    truncated = None
    if walk_roots:
        got, scanned, truncated = _walk(walk_roots, args.query, args.query if args.regex else None, args.case, f,
                                        args.limit, args.max_seconds)
        items += got
        used = "walk" if used is None else used + "+walk"
    _sort(items, args.sort)
    if len(items) > args.limit:
        items = items[:args.limit]
        truncated = truncated or f"limit {args.limit} reached"
    for i in items:
        i.pop("_mtime", None)
    out = {"ok": True, "engine": used, "query": args.query, "roots": roots or None, "count": len(items), "results": items}
    if scanned is not None:
        out["walked_entries"] = scanned
    if truncated:
        out["truncated"] = truncated
    if notes:
        out["notes"] = notes
    return out
