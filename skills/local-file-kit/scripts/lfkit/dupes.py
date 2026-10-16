"""dupes / similar / empty: duplicate files, look-alike images, empty folders and files.

Czkawka CLI does the work when installed. Without it, 'dupes' and 'empty' fall back to Python (slower);
'similar' needs Czkawka.
"""
import hashlib
import json
import os
import time

from . import tools
from .util import IS_WIN, LfkError, abspath, fix_case_prefix, iso_time, remove_quietly, run, temp_path


def _roots(paths):
    roots = [os.path.realpath(abspath(p)) for p in paths]  # long names (not C:\Users\RUNNER~1), as Czkawka reports them
    for r in roots:
        if not os.path.isdir(r):
            raise LfkError("not_found", f"not a folder: {r}", exit_code=2)
    return roots


def _czkawka(sub, roots, extra, timeout):
    exe = tools.require("czkawka")
    out = temp_path(".json")
    cmd = [exe, sub]
    for r in roots:
        cmd += ["-d", r]
    cmd += extra + ["-C", out, "-N", "-M", "-W"]
    try:
        rc, _, err = run(cmd, timeout=timeout)
        if rc not in (0, 11):
            raise LfkError("tool_failed", f"czkawka {sub} exited with code {rc}", stderr=err.strip()[-500:])
        try:
            with open(out, encoding="utf-8-sig") as f:
                text = f.read().strip()
        except FileNotFoundError:
            text = ""
        return json.loads(text) if text else []
    finally:
        remove_quietly(out)


def _walk_files(roots, max_seconds):
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
                try:
                    if e.is_dir(follow_symlinks=False):
                        st = e.stat(follow_symlinks=False)
                        if not (IS_WIN and getattr(st, "st_file_attributes", 0) & 0x400):
                            stack.append(e.path)
                        continue
                    if e.is_file(follow_symlinks=False):
                        yield e.path, e.stat(follow_symlinks=False)
                except OSError:
                    continue
        if time.monotonic() - start > max_seconds:
            raise TimeoutError


def _hash(path, limit=None):
    h = hashlib.blake2b(digest_size=20)
    with open(path, "rb") as f:
        if limit:
            h.update(f.read(limit))
        else:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
    return h.hexdigest()


def _drop_hardlinks(items):
    seen, out = set(), []
    for p, m in items:
        try:
            st = os.stat(p)  # os.stat, not DirEntry.stat: only it fills st_ino on Windows
        except OSError:
            continue
        key = (st.st_dev, st.st_ino)
        if st.st_ino and key in seen:
            continue
        seen.add(key)
        out.append((p, m))
    return out


def _py_dupes(roots, min_size, max_seconds):
    by_size = {}
    truncated = None
    try:
        for path, st in _walk_files(roots, max_seconds):
            if st.st_size >= min_size and st.st_size > 0:
                if IS_WIN and getattr(st, "st_file_attributes", 0) & (0x400000 | 0x1000):
                    continue  # cloud-only placeholder: reading would download it
                by_size.setdefault(st.st_size, []).append((path, st.st_mtime))
    except TimeoutError:
        truncated = f"stopped listing after {max_seconds} s; results are partial"
    groups = []
    for size, items in by_size.items():
        if len(items) < 2:
            continue
        items = _drop_hardlinks(items)  # hard links share one copy on disk: not duplicates (Czkawka agrees)
        if len(items) < 2:
            continue
        by_head = {}
        for p, m in items:
            try:
                by_head.setdefault(_hash(p, 64 * 1024), []).append((p, m))
            except OSError:
                continue
        for same_head in by_head.values():
            if len(same_head) < 2:
                continue
            by_full = {}
            for p, m in same_head:
                try:
                    key = _hash(p) if size > 64 * 1024 else "head"
                except OSError:
                    continue
                by_full.setdefault(key, []).append((p, m))
            for h, members in by_full.items():
                if len(members) >= 2:
                    groups.append({"size": size, "files": [{"path": p, "modified": iso_time(m)} for p, m in sorted(members)]})
    return groups, truncated


def cmd_dupes(args):
    roots = _roots(args.paths)
    min_size = args.min_size
    engine = args.engine
    loc = tools.locate("czkawka") if engine in ("auto", "czkawka") else {"found": False}
    notes = []
    truncated = None
    if loc.get("found"):
        data = _czkawka("dup", roots, ["-m", str(max(1, min_size))], args.max_seconds)
        groups = []
        for size_key, size_groups in (data.items() if isinstance(data, dict) else []):
            for g in size_groups:
                groups.append({"size": g[0]["size"] if g else int(size_key),
                               "files": [{"path": fix_case_prefix(f["path"], roots), "modified": iso_time(f.get("modified_date"))}
                                         for f in g]})
        used = "czkawka"
    elif engine == "czkawka":
        tools.require("czkawka")
    else:
        groups, truncated = _py_dupes(roots, max(1, min_size), args.max_seconds)
        used = "python"
        notes.append("Czkawka not found: compared files with Python (slower). " +
                     " / ".join(tools.install_advice("czkawka")["install"]))
    groups.sort(key=lambda g: g["size"] * (len(g["files"]) - 1), reverse=True)
    wasted = sum(g["size"] * (len(g["files"]) - 1) for g in groups)
    total_groups = len(groups)
    out = {"ok": True, "engine": used, "roots": roots, "groups": total_groups, "wasted_bytes": wasted,
           "duplicates": groups[:args.limit]}
    if total_groups > args.limit:
        out["truncated"] = f"showing {args.limit} of {total_groups} groups (largest waste first)"
    if truncated:
        out["truncated"] = truncated
    if notes:
        out["notes"] = notes
    out["next_step"] = "To remove copies: 'trash <paths>' (preview first). Keep at least one file per group."
    return out


def cmd_similar(args):
    roots = _roots(args.paths)
    extra = ["-m", str(args.min_size), "-s", str(args.max_difference), "-c", str(args.hash_size), "-g", args.hash_alg]
    data = _czkawka("image", roots, extra, args.max_seconds)
    groups = []
    for g in data:
        members = []
        for f in g:
            members.append({"path": fix_case_prefix(f.get("path", ""), roots), "size": f.get("size"),
                            "width": f.get("width"), "height": f.get("height"),
                            "modified": iso_time(f.get("modified_date")), "difference": f.get("difference")})
        groups.append(members)
    out = {"ok": True, "engine": "czkawka", "roots": roots, "groups": len(groups), "similar": groups[:args.limit],
           "settings": {"max_difference": args.max_difference, "hash_size": args.hash_size, "hash_alg": args.hash_alg}}
    if not groups:
        out["hint"] = ("None found. Edited copies (brightness, resize) can need looser settings, e.g. "
                       "--hash-alg Mean --hash-size 8 --max-difference 10")
    return out


def cmd_empty(args):
    roots = _roots(args.paths)
    engine = args.engine
    loc = tools.locate("czkawka") if engine in ("auto", "czkawka") else {"found": False}
    if loc.get("found"):
        folders = [fix_case_prefix(p if isinstance(p, str) else p.get("path", ""), roots)
                   for p in _czkawka("empty-folders", roots, [], args.max_seconds)]
        files = [fix_case_prefix(f["path"], roots) for f in _czkawka("empty-files", roots, [], args.max_seconds)] if args.files else None
        used = "czkawka"
    elif engine == "czkawka":
        tools.require("czkawka")
    else:
        folders, files = _py_empty(roots, args.files)
        used = "python"
    out = {"ok": True, "engine": used, "roots": roots, "empty_folders": sorted(folders)}
    if files is not None:
        out["empty_files"] = sorted(files)
    out["note"] = "A folder counts as empty when it holds only empty folders; the outermost such folder is listed."
    return out


def _py_empty(roots, want_files):
    empty_files = []
    empty_dirs = set()
    for root in roots:
        for d, subdirs, files in os.walk(root, topdown=False):
            if want_files:
                for f in files:
                    p = os.path.join(d, f)
                    try:
                        if os.path.getsize(p) == 0:
                            empty_files.append(p)
                    except OSError:
                        pass
            if d != root and not files and all(os.path.join(d, s) in empty_dirs for s in subdirs):
                empty_dirs.add(d)
    outermost = [d for d in empty_dirs if os.path.dirname(d) not in empty_dirs]
    return outermost, (empty_files if want_files else None)
