"""doctor: what this computer has, what each feature can use, and what to install for the rest."""
from . import __version__, sysinfo, tools
from .util import IS_WIN

FEATURES = [
    # name, tool, fallback without the tool (None = feature unavailable)
    ("find", "everything", "walks the folders you name with --root (slow on whole drives)"),
    ("search", "digup", None),
    ("index", "digup", None),
    ("size", "wiztree", "walks the folder with Python (slower on big drives)"),
    ("dupes", "czkawka", "compares files with Python (slower)"),
    ("similar", "czkawka", None),
    ("empty", "czkawka", "Python"),
    ("exif", "exiftool", None),
    ("archive", "7zip", ".zip only, with Python's zipfile"),
    ("copy", "robocopy", "Python's shutil (no restart, plain copy)"),
    ("plan/move/trash/undo", None, None),
]


def cmd_doctor(args):
    hw = sysinfo.all_info()
    tool_info = {k: tools.probe(k) for k in tools.TOOLS}
    features = {}
    for name, key, fallback in FEATURES:
        if key is None:
            features[name] = {"available": True, "via": "python"}
            continue
        t = tool_info[key]
        if t.get("found") and t.get("ready", True):
            features[name] = {"available": True, "via": key}
        elif fallback and t.get("unsupported_platform"):
            features[name] = {"available": True, "via": "fallback", "fallback": fallback,
                              "note": f"{t['label']} is not available on {tools.PLATFORM}"}
        elif fallback:
            features[name] = {"available": True, "via": "fallback", "fallback": fallback,
                              "better_with": t["label"], "install": t.get("install")}
        else:
            reason = t.get("problem") or t.get("unsupported_platform") or f"{t['label']} not found"
            features[name] = {"available": False, "reason": reason, "install": t.get("install")}
    return {"ok": True, "version": __version__, "platform": tools.PLATFORM, "system": hw, "tools": tool_info,
            "features": features, "advice": _advice(hw, tool_info), "config_file": tools.config_path(),
            "undo_logs": tools.data_dir()}


def _advice(hw, t):
    out = []
    ram = (hw.get("memory") or {}).get("total_gb")
    if ram is not None and ram < 8:
        out.append(f"Only {ram} GB of memory: DigUp's model needs about 1.5 GB on top of what is running; "
                   "index while little else is open.")
    gpus = [g for g in hw.get("gpus", []) if (g.get("vram_gb") or 0) >= 2]
    if t["digup"].get("found") and not gpus and not any(g.get("shared_memory") for g in hw.get("gpus", [])):
        out.append("No graphics card with 2 GB+ memory found: DigUp indexes on the CPU, which is much slower for "
                   "pictures, screenshots and scanned PDFs (text documents are less affected).")
    for g in hw.get("gpus", []):
        if g.get("vram_used_gb") and g.get("vram_gb") and g["vram_gb"] - g["vram_used_gb"] < 1.5:
            out.append(f"{g['name']} has under 1.5 GB of free graphics memory now; DigUp indexing may fall back to "
                       "slow shared memory until other GPU programs close (then restart DigUp).")
    d = t["digup"]
    if d.get("found") and d.get("model_found") is False:
        out.append(d.get("model_note"))
    if d.get("found") and d.get("commands_ok") is False:
        out.append(d.get("problem"))
    e = t["everything"]
    if IS_WIN and e.get("found") and e.get("ready") is False:
        out.append("es.exe found but Everything is not running: start Everything (and let it run at sign-in).")
    missing = [k for k, v in t.items() if not v.get("found") and not v.get("unsupported_platform")]
    if missing:
        out.append("Missing: " + ", ".join(missing) + ". 'setup' lists how to install them; 'setup --all --yes' "
                   "installs them on Windows once the user agrees.")
    if IS_WIN and t["wiztree"].get("found"):
        out.append("WizTree is free for personal use only; business use needs a WizTree licence.")
    return out
