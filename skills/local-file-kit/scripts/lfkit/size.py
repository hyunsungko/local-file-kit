"""size: what takes up the space in a folder or drive. WizTree when it is installed, a folder walk otherwise."""
import csv
import heapq
import os
import time

from . import tools
from .util import IS_WIN, LfkError, abspath, iso_time, remove_quietly, run, temp_path


def _wiztree(exe, root, timeout):
    out = temp_path(".csv")
    try:
        rc, _, err = run([exe, root, f"/export={out}", "/admin=0", "/exportfolders=1", "/exportfiles=1",
                          "/exportdrivecapacity=0"], timeout=timeout)
        if not os.path.isfile(out):
            raise LfkError("tool_failed", f"WizTree wrote no CSV (exit code {rc})", stderr=err.strip()[:300])
        rows = []
        with open(out, encoding="utf-8-sig", newline="") as f:
            for rec in csv.reader(f):
                # first lines are a banner and a header in the user's language; data rows start with a quoted path
                if len(rec) < 7 or not (rec[0][1:3] == ":\\" or rec[0].startswith("\\\\")):
                    continue
                try:
                    rows.append({"path": rec[0], "size": int(rec[1]), "allocated": int(rec[2] or 0),
                                 "modified": (rec[3] or "").replace(" ", "T") or None, "files": int(rec[5] or 0), "folders": int(rec[6] or 0)})
                except ValueError:
                    continue
        return rows
    finally:
        remove_quietly(out)


def _summarize_rows(rows, root, top):
    root_n = root.rstrip("\\") + "\\"
    total = None
    children, files = [], []
    for r in rows:
        p = r["path"]
        is_dir = p.endswith("\\")
        clean = p.rstrip("\\")
        if p.lower() == root_n.lower() or clean.lower() == root.rstrip("\\").lower():
            total = r
            continue
        parent = os.path.dirname(clean)
        if parent.lower().rstrip("\\") == root.rstrip("\\").lower():
            children.append({"path": clean, "is_dir": is_dir, "size": r["size"], "files": r["files"] if is_dir else None})
        if not is_dir:
            files.append((r["size"], clean, r["modified"]))
    children.sort(key=lambda c: c["size"], reverse=True)
    largest = heapq.nlargest(top, files)
    out = {"total_bytes": total["size"] if total else sum(c["size"] for c in children),
           "files": total["files"] if total else len(files), "folders": total["folders"] if total else None,
           "children": children[:top], "largest_files": [{"path": p, "size": s, "modified": m} for s, p, m in largest]}
    return out


def _walk(root, top, max_seconds):
    start = time.monotonic()
    child_sizes = {}
    child_files = {}
    largest = []
    files = folders = 0
    truncated = None
    skipped = 0
    try:
        entries = list(os.scandir(root))
    except OSError as e:
        raise LfkError("not_readable", f"cannot list {root}: {e}")
    for top_entry in entries:
        if truncated:
            break
        name = top_entry.path
        try:
            is_dir = top_entry.is_dir(follow_symlinks=False)
        except OSError:
            continue
        if not is_dir:
            try:
                st = top_entry.stat(follow_symlinks=False)
            except OSError:
                skipped += 1
                continue
            child_sizes[name] = (False, st.st_size)
            files += 1
            _push(largest, top, st.st_size, name, st.st_mtime)
            continue
        folders += 1
        total = n = 0
        stack = [name]
        while stack:
            d = stack.pop()
            try:
                it = os.scandir(d)
            except OSError:
                skipped += 1
                continue
            with it:
                for e in it:
                    try:
                        st = e.stat(follow_symlinks=False)
                        sub_dir = e.is_dir(follow_symlinks=False)
                    except OSError:
                        skipped += 1
                        continue
                    if sub_dir:
                        folders += 1
                        if not (IS_WIN and getattr(st, "st_file_attributes", 0) & 0x400):
                            stack.append(e.path)
                        continue
                    total += st.st_size
                    n += 1
                    _push(largest, top, st.st_size, e.path, st.st_mtime)
            if time.monotonic() - start > max_seconds:
                truncated = f"stopped after {max_seconds} s; numbers are partial (install WizTree, or raise --max-seconds)"
                stack = []
        child_sizes[name] = (True, total)
        child_files[name] = n
        files += n
    children = sorted(({"path": p, "is_dir": d, "size": s, "files": child_files.get(p)} for p, (d, s) in child_sizes.items()),
                      key=lambda c: c["size"], reverse=True)
    out = {"total_bytes": sum(s for _, s in child_sizes.values()), "files": files, "folders": folders,
           "children": children[:top],
           "largest_files": [{"path": p, "size": s, "modified": iso_time(m)} for s, p, m in sorted(largest, reverse=True)]}
    if skipped:
        out["unreadable_entries"] = skipped
    if truncated:
        out["truncated"] = truncated
    return out


def _push(heap, top, size, path, mtime):
    item = (size, path, mtime)
    if len(heap) < top:
        heapq.heappush(heap, item)
    elif size > heap[0][0]:
        heapq.heapreplace(heap, item)


def cmd_size(args):
    root = os.path.realpath(abspath(args.path))
    if not os.path.isdir(root):
        raise LfkError("not_found", f"not a folder: {root}", exit_code=2)
    if IS_WIN and len(root) == 2 and root[1] == ":":
        root += "\\"
    engine = args.engine
    loc = tools.locate("wiztree") if engine in ("auto", "wiztree") else {"found": False}
    notes = []
    if loc.get("found"):
        rows = _wiztree(loc["path"], root, args.max_seconds)
        result = _summarize_rows(rows, root, args.top)
        used = "wiztree"
        notes.append("WizTree is free for personal use only; business use needs its own licence.")
    elif engine == "wiztree":
        tools.require("wiztree")
    else:
        result = _walk(root, args.top, args.max_seconds)
        used = "walk"
        if tools.PLATFORM == "windows":
            notes.append("WizTree not found: walked the folder (slower on big drives). " +
                         " / ".join(tools.install_advice("wiztree")["install"]))
    out = {"ok": True, "engine": used, "path": root, **result}
    if notes:
        out["notes"] = notes
    return out
