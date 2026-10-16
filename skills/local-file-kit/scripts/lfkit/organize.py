"""plan / move / trash / undo: tidy files safely.

- Everything previews by default. Only --execute changes files.
- Every executed move or trash is written, as it happens, to an undo log (CSV) whose path is returned.
- trash sends to the Recycle Bin (Windows), Trash (macOS) or the desktop trash (Linux, via gio); never deletes outright.
- System folders, drive roots and the home folder itself are refused.
"""
import csv
import datetime as _dt
import json
import os
import shutil
import struct
import tempfile

from . import tools
from .util import IS_MAC, IS_WIN, LfkError, abspath, remove_quietly, run, temp_path

KIND_EXTS = {
    "images": "jpg jpeg png gif bmp webp heic heif tif tiff raw dng cr2 cr3 nef arw svg ico",
    "videos": "mp4 mov m4v avi mkv wmv webm 3gp mts m2ts",
    "audio": "mp3 wav flac m4a aac ogg wma opus",
    "documents": "pdf doc docx hwp hwpx txt md rtf odt xls xlsx csv ppt pptx key pages numbers",
    "archives": "zip 7z rar tar gz bz2 xz tgz iso",
    "code": "py js ts java c cpp cs go rs rb php html css json xml yml yaml sh ps1 bat ipynb",
}
EXT_KIND = {e: k for k, exts in KIND_EXTS.items() for e in exts.split()}


# --------------------------------------------------------------------------------------------- safety


def _protected_roots():
    env = os.environ
    if IS_WIN:
        names = ["SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData"]
        under = [env[n] for n in names if env.get(n)]
        home = env.get("USERPROFILE") or os.path.expanduser("~")
        under += [os.path.join(home, "AppData")]
        exact = [home, os.path.dirname(home)]
    else:
        under = ["/bin", "/sbin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/proc", "/sys", "/usr", "/var",
                 "/System", "/Library", "/private", os.path.expanduser("~/Library")]
        exact = ["/", os.path.expanduser("~"), "/home", "/Users", "/Applications"]
    # each as written and resolved (8.3 short names like RUNNER~1, /var -> /private/var on macOS)
    both = lambda ps: sorted({_key(p) for p in ps} | {_key(os.path.realpath(p)) for p in ps})
    return both(under), both(exact)


def _key(path):
    """A comparable spelling of a path: absolute, no \\\\?\\ prefix, case-folded (Windows and macOS ignore case)."""
    p = os.path.abspath(path)
    if IS_WIN:
        if p.startswith("\\\\?\\UNC\\"):
            p = "\\\\" + p[8:]
        elif p.startswith("\\\\?\\"):
            p = p[4:]
    return os.path.normcase(p).rstrip("\\/").casefold()


def protected_reason(path):
    """Why a path must not be moved or trashed, or None. Checked as written and with links/short names resolved."""
    for candidate in (path, os.path.realpath(path)):
        reason = _protected_reason(candidate)
        if reason:
            return reason
    return None


def _protected_reason(path):
    p = _key(path)
    drive, rest = os.path.splitdrive(p)
    if not rest.strip("\\/"):
        return "drive root"
    under, exact = _protected_roots()
    if p in exact:
        return "home or system folder itself"
    tmp = _key(os.path.realpath(tempfile.gettempdir()))
    if p.startswith(tmp + os.sep) or p.startswith(_key(tempfile.gettempdir()) + os.sep):
        return None  # things inside the temp folder may go, even though it sits in AppData
    for u in under:
        if p == u or p.startswith(u + os.sep):
            return f"inside a system folder ({u})"
    low = p.lower()
    if "$recycle.bin" in low or "system volume information" in low:
        return "system folder"
    return None


# --------------------------------------------------------------------------------------------- undo log


class UndoLog:
    FIELDS = ["time", "action", "source", "destination"]

    def __init__(self, path, action):
        if not path:
            folder = os.path.join(tools.data_dir(), "undo")
            os.makedirs(folder, exist_ok=True)
            stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            path = os.path.join(folder, f"{stamp}-{action}.csv")
        self.path = abspath(path)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        new = not os.path.exists(self.path)
        self.f = open(self.path, "a", encoding="utf-8-sig" if new else "utf-8", newline="")
        self.w = csv.writer(self.f)
        if new:
            self.w.writerow(self.FIELDS)
            self.f.flush()

    def add(self, action, source, destination=""):
        self.w.writerow([_dt.datetime.now().isoformat(timespec="seconds"), action, source, destination])
        self.f.flush()

    def close(self):
        self.f.close()


# --------------------------------------------------------------------------------------------- plan


def cmd_plan(args):
    src = abspath(args.source)
    dest = abspath(args.to)
    if not os.path.isdir(src):
        raise LfkError("not_found", f"not a folder: {src}", exit_code=2)
    files = []
    if args.recursive:
        for d, dirs, names in os.walk(src):
            # skip already sorted files, hidden folders (.git ...) and tool folders
            dirs[:] = [x for x in dirs if not _inside(os.path.join(d, x), dest) and not x.startswith(".")
                       and x.lower() not in ("node_modules", "$recycle.bin", "system volume information")]
            files += [os.path.join(d, n) for n in names if os.path.isfile(os.path.join(d, n))]
    else:
        files = [e.path for e in os.scandir(src) if e.is_file(follow_symlinks=False)]
    dates = {}
    if args.by in ("year", "month") and args.exif:
        dates = _exif_dates(files)
    rows = []
    for f in sorted(files):
        name = os.path.basename(f)
        ext = os.path.splitext(name)[1].lstrip(".").lower()
        if args.by == "ext":
            folder = ext or "no-extension"
        elif args.by == "kind":
            folder = EXT_KIND.get(ext, "others")
        else:
            when = dates.get(f)
            if when is None:
                try:
                    when = _dt.datetime.fromtimestamp(os.path.getmtime(f))
                except OSError:
                    continue  # vanished or unreadable: leave it out of the plan
            folder = f"{when.year:04d}" if args.by == "year" else os.path.join(f"{when.year:04d}", f"{when.month:02d}")
        target = os.path.join(dest, folder, name)
        if _key(target) != _key(f):
            rows.append((f, target))
    out_path = abspath(args.save) if args.save else os.path.join(
        tools.data_dir(), "plans", _dt.datetime.now().strftime("%Y%m%d-%H%M%S") + f"-by-{args.by}.csv")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["source", "destination"])
        w.writerows(rows)
    folders = {}
    for _, t in rows:
        k = os.path.relpath(os.path.dirname(t), dest)
        folders[k] = folders.get(k, 0) + 1
    return {"ok": True, "plan": out_path, "moves": len(rows), "by": args.by, "folders": folders,
            "sample": [{"source": s, "destination": t} for s, t in rows[:20]],
            "next_step": f"Review or edit the CSV, then preview: move --plan \"{out_path}\" ; execute with --execute"}


def _exif_dates(files):
    loc = tools.locate("exiftool")
    if not loc["found"] or not files:
        return {}
    argfile = temp_path(".args")
    with open(argfile, "w", encoding="utf-8") as f:
        f.write("\n".join(["-j", "-charset", "filename=utf8", "-d", "%Y-%m-%d %H:%M:%S", "-DateTimeOriginal",
                           "-CreateDate", "-EXIF:ModifyDate"] + files) + "\n")
    try:
        rc, out, _ = run([loc["path"], "-@", argfile], timeout=1800)
    finally:
        remove_quietly(argfile)
    dates = {}
    for r in (json.loads(out) if out.strip() else []):
        v = r.get("DateTimeOriginal") or r.get("CreateDate") or r.get("ModifyDate")
        try:
            dates[os.path.normpath(r["SourceFile"])] = _dt.datetime.strptime(str(v), "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError, KeyError):
            continue
    return dates


def _inside(path, folder):
    p, f = _key(path), _key(folder)
    return p == f or p.startswith(f + os.sep)


def _move_logged(src, dst, log, action="move"):
    """Move src to dst, never replacing anything, and log it. Returns a status word; raises OSError on failure.

    A move to another drive copies then deletes; if the delete fails, the copy is logged anyway so undo can find it.
    """
    if os.path.lexists(dst):
        raise FileExistsError(f"destination appeared after the preview: {dst}")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        shutil.move(src, dst)
    except OSError as e:
        if os.path.lexists(dst):
            log.add(action, src, dst)
            raise OSError(f"{e} (copied to the destination but the original could not be fully removed; "
                          "logged for undo, check both places)")
        raise
    log.add(action, src, dst)


# --------------------------------------------------------------------------------------------- move


def _read_plan(path):
    rows = []
    with open(abspath(path), encoding="utf-8-sig", newline="") as f:
        for i, rec in enumerate(csv.reader(f)):
            if not rec or (i == 0 and rec[0].strip().lower() in ("source", "src")):
                continue
            if len(rec) < 2:
                raise LfkError("bad_plan", f"line {i + 1} of the plan needs two columns: source,destination", exit_code=2)
            rows.append((abspath(rec[0].strip()), abspath(rec[1].strip())))
    return rows


def _unique(path, claimed=()):
    """'name (1).ext', 'name (2).ext', ... : the first that neither exists nor is taken by an earlier move."""
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.lexists(f"{base} ({n}){ext}") or _key(f"{base} ({n}){ext}") in claimed:
        n += 1
    return f"{base} ({n}){ext}"


def _check_move(src, dst, on_conflict, claimed):
    if not os.path.lexists(src):
        return "missing", dst
    reason = protected_reason(src) or protected_reason(os.path.dirname(dst) or dst)
    if reason:
        return "protected: " + reason, dst
    if _key(src) == _key(dst):
        return "same place", dst
    if os.path.isdir(src) and _inside(dst, src):
        return "destination is inside the source", dst
    if os.path.lexists(dst) or _key(dst) in claimed:
        if on_conflict == "rename":
            dst = _unique(dst, claimed)
        else:
            return "conflict: destination exists", dst
    return "ok", dst


def cmd_move(args):
    if args.plan:
        pairs = _read_plan(args.plan)
    else:
        if not args.to or not args.paths:
            raise LfkError("bad_argument", "give files/folders and --to <folder>, or --plan <csv>", exit_code=2)
        to = abspath(args.to)
        pairs = [(abspath(p), os.path.join(to, os.path.basename(abspath(p).rstrip("\\/")))) for p in args.paths]
    ops, claimed = [], set()
    for src, dst in pairs:
        status, final = _check_move(src, dst, args.on_conflict, claimed)
        if status == "ok":
            claimed.add(_key(final))
        ops.append({"source": src, "destination": final, "status": status})
    ready = [o for o in ops if o["status"] == "ok"]
    res = {"ok": True, "mode": "executed" if args.execute else "preview", "total": len(ops), "ready": len(ready),
           "blocked": len(ops) - len(ready)}
    if args.execute and ready:
        log = UndoLog(args.log, "move")
        done = failed = 0
        try:
            for o in ready:
                try:
                    _move_logged(o["source"], o["destination"], log)
                    o["status"] = "moved"
                    done += 1
                except OSError as e:
                    o["status"] = f"failed: {e}"
                    failed += 1
        finally:
            log.close()
        res.update(moved=done, failed=failed, undo_log=log.path,
                   undo_with=f"undo \"{log.path}\" (preview) then add --execute")
        res["ok"] = failed == 0
    elif not args.execute:
        res["next_step"] = "Nothing was moved. Check 'operations', then run again with --execute."
    res["operations"] = ops[:args.limit]
    if len(ops) > args.limit:
        res["truncated"] = f"listing {args.limit} of {len(ops)} operations"
    return res


# --------------------------------------------------------------------------------------------- trash


def _recycle_windows(path):
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE = 3
    # ALLOWUNDO (recycle) | NOCONFIRMATION | SILENT | NOERRORUI | WANTNUKEWARNING (ask before anything would be
    # deleted for good, e.g. too big for the Recycle Bin or a drive without one)
    flags = 0x0040 | 0x0010 | 0x0004 | 0x0400 | 0x4000
    op = SHFILEOPSTRUCTW(None, FO_DELETE, path + "\0", None, flags, False, None, None)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0:
        raise OSError(f"SHFileOperation error 0x{rc:x}")
    if op.fAnyOperationsAborted:
        raise OSError("cancelled")


def _trash_one(path):
    if IS_WIN:
        _recycle_windows(path)
        return "Recycle Bin"
    try:
        import send2trash  # optional
        send2trash.send2trash(path)
        return "Trash (send2trash)"
    except ImportError:
        pass
    if IS_MAC:
        script = 'tell application "Finder" to delete (POSIX file "%s")' % path.replace("\\", "\\\\").replace('"', '\\"')
        rc, _, err = run(["osascript", "-e", script], timeout=60)
        if rc != 0:
            raise OSError(err.strip() or f"osascript exit {rc}")
        return "Trash"
    if shutil.which("gio"):
        rc, _, err = run(["gio", "trash", path], timeout=60)
        if rc != 0:
            raise OSError(err.strip() or f"gio exit {rc}")
        return "Trash (gio)"
    raise LfkError("trash_unavailable", "no way to reach the desktop trash here: install 'gio' (glib) or "
                   "'pip install send2trash'. Files were not deleted.", exit_code=3)


def _drive_has_recycle_bin(path):
    if not IS_WIN:
        return True
    import ctypes
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    if not drive or drive.startswith("\\\\"):
        return False
    return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == 3  # DRIVE_FIXED


def cmd_trash(args):
    items = []
    for p in args.paths:
        path = os.path.realpath(abspath(p))  # long names, as the Recycle Bin records them
        if not os.path.lexists(path):
            status = "missing"
        elif protected_reason(path):
            status = "protected: " + protected_reason(path)
        elif not _drive_has_recycle_bin(path):
            status = "refused: this drive has no Recycle Bin (network or removable), the file would be lost for good"
        else:
            status = "ok"
        size = None
        if status == "ok" and os.path.isfile(path):
            size = os.path.getsize(path)
        items.append({"path": path, "status": status, "is_dir": os.path.isdir(path), "size": size})
    ready = [i for i in items if i["status"] == "ok"]
    res = {"ok": True, "mode": "executed" if args.execute else "preview", "total": len(items), "ready": len(ready),
           "blocked": len(items) - len(ready)}
    if args.execute and ready:
        log = UndoLog(args.log, "trash")
        done = failed = 0
        try:
            for i in ready:
                try:
                    where = _trash_one(i["path"])
                    if os.path.lexists(i["path"]):
                        raise OSError("still there after the trash call")
                    log.add("trash", i["path"], where)
                    i["status"] = "trashed"
                    done += 1
                except OSError as e:
                    i["status"] = f"failed: {e}"
                    failed += 1
        finally:
            log.close()
        res.update(trashed=done, failed=failed, undo_log=log.path,
                   undo_with=f"undo \"{log.path}\" (preview) then add --execute; or restore from the Recycle Bin")
        res["ok"] = failed == 0
    elif not args.execute:
        res["next_step"] = "Nothing was deleted. Check 'items', then run again with --execute (goes to the Recycle Bin)."
    res["items"] = items[:args.limit]
    if len(items) > args.limit:
        res["truncated"] = f"listing {args.limit} of {len(items)}"
    return res


# --------------------------------------------------------------------------------------------- undo


def cmd_undo(args):
    path = abspath(args.log_file)
    if not os.path.isfile(path):
        raise LfkError("not_found", f"no such undo log: {path}", exit_code=2)
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    ops, claimed = [], set()
    for r in reversed(rows):
        if r.get("action") == "move":
            back_from, back_to = r["destination"], r["source"]
            reason = protected_reason(back_from) or protected_reason(back_to)
            if reason:
                status = "protected: " + reason
            elif not os.path.lexists(back_from):
                status = "missing: the moved file is no longer at its new place"
            elif os.path.lexists(back_to) or _key(back_to) in claimed:
                status = "conflict: something now exists at the original place"
            else:
                status = "ok"
                claimed.add(_key(back_to))
            ops.append({"action": "move back", "from": back_from, "to": back_to, "status": status})
        elif r.get("action") == "trash":
            original = r["source"]
            if protected_reason(original):
                ops.append({"action": "restore", "to": original, "status": "protected: " + protected_reason(original)})
                continue
            found = find_in_trash(original, r.get("time"))
            if found is None:
                ops.append({"action": "restore", "to": original, "status": "manual: not found in the trash here "
                            "(emptied, or restore it yourself from " + (r.get("destination") or "the Recycle Bin") + ")"})
                continue
            item, meta = found
            if os.path.lexists(original) or _key(original) in claimed:
                status = "conflict: something now exists at the original place"
            else:
                status = "ok"
                claimed.add(_key(original))
            ops.append({"action": "restore", "from": item, "to": original, "meta": meta, "status": status})
    ready = [o for o in ops if o["status"] == "ok"]
    res = {"ok": True, "mode": "executed" if args.execute else "preview", "log": path, "total": len(ops),
           "ready": len(ready)}
    if args.execute and ready:
        log = UndoLog(None, "undo")
        failed = 0
        try:
            for o in ready:
                try:
                    if o["action"] == "restore":
                        if os.path.lexists(o["to"]):
                            raise FileExistsError(f"something appeared at the original place: {o['to']}")
                        os.makedirs(os.path.dirname(o["to"]), exist_ok=True)
                        shutil.move(o["from"], o["to"])
                        os.remove(o["meta"])  # the trash's note about the item; the item itself is back
                        o["status"] = "restored"
                    else:
                        _move_logged(o["from"], o["to"], log)
                        o["status"] = "moved back"
                except OSError as e:
                    o["status"] = f"failed: {e}"
                    failed += 1
        finally:
            log.close()
        res.update(failed=failed, undo_log=log.path)
        res["ok"] = failed == 0
    elif not args.execute:
        res["next_step"] = "Nothing was changed. Run again with --execute to move files back."
    res["operations"] = ops[:args.limit]
    return res


def _windows_trash(original):
    """Recycle Bin entries for a path, from its $I records: [(deleted epoch, item, record)]."""
    drive = os.path.splitdrive(original)[0]
    base = drive + "\\$Recycle.Bin"
    found = []
    try:
        sids = os.listdir(base)
    except OSError:
        return found
    want = _key(os.path.realpath(original))  # 8.3 short names (C:/Users/RUNNER~1) -> long
    for sid in sids:
        folder = os.path.join(base, sid)
        try:
            names = [n for n in os.listdir(folder) if n.startswith("$I")]
        except OSError:
            continue  # another user's bin
        for n in names:
            rec = os.path.join(folder, n)
            try:
                with open(rec, "rb") as f:
                    data = f.read(4096)
                version, _, deleted = struct.unpack_from("<qqq", data, 0)
                if version == 2:
                    chars = struct.unpack_from("<i", data, 24)[0]
                    orig = data[28:28 + chars * 2].decode("utf-16-le").rstrip("\0")
                else:
                    orig = data[24:24 + 520].decode("utf-16-le").split("\0")[0]
            except (OSError, struct.error, UnicodeDecodeError):
                continue
            item = os.path.join(folder, "$R" + n[2:])
            if _key(os.path.realpath(orig)) == want and os.path.lexists(item):
                found.append((deleted / 10_000_000 - 11_644_473_600, item, rec))  # FILETIME (UTC) -> epoch
    return found


def _linux_trash(original):
    """freedesktop.org home trash: info/<name>.trashinfo records Path= and DeletionDate=, files/<name> holds the item."""
    from urllib.parse import unquote
    home = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "Trash")
    info_dir = os.path.join(home, "info")
    found = []
    try:
        names = [n for n in os.listdir(info_dir) if n.endswith(".trashinfo")]
    except OSError:
        return found
    for n in names:
        rec = os.path.join(info_dir, n)
        try:
            with open(rec, encoding="utf-8") as f:
                kv = dict(l.strip().split("=", 1) for l in f if "=" in l)
            when = _dt.datetime.fromisoformat(kv.get("DeletionDate", "")).timestamp()  # local time
        except (OSError, ValueError):
            continue
        item = os.path.join(home, "files", n[:-len(".trashinfo")])
        if unquote(kv.get("Path", "")) == original and os.path.lexists(item):
            found.append((when, item, rec))
    return found


def find_in_trash(original, logged_at, window=120):
    """The trash entry for `original` deleted closest to when the undo log recorded it (within `window` seconds).

    Matching the time, not just the path, keeps undo from restoring a different file deleted from the same place.
    """
    if IS_MAC:
        return None  # macOS keeps no original-path record we can read safely
    try:
        logged = _dt.datetime.fromisoformat(logged_at).timestamp()
    except (TypeError, ValueError):
        return None
    entries = _windows_trash(original) if IS_WIN else _linux_trash(original)
    close = [(abs(when - logged), item, rec) for when, item, rec in entries if abs(when - logged) <= window]
    return min(close)[1:] if close else None
