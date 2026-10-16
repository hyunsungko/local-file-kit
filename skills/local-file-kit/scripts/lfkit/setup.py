"""setup: install the missing outside tools in one go - only after the user has seen the list and said yes.

Windows: winget (or Chocolatey when winget is missing). macOS/Linux: prints the brew/apt commands to run.
DigUp is never installed here (no package manager carries it): its download page is shown instead.
WizTree is never part of --all: it is free for personal use only, so it must be named with --tools wiztree.
"""
import os
import shutil
import subprocess

from . import tools
from .util import IS_WIN, LfkError, run

PACKAGES = {
    "everything": {"winget": ["voidtools.Everything", "voidtools.Everything.Cli"], "choco": ["everything", "es"]},
    "czkawka": {"winget": ["qarmin.czkawka.cli"]},
    "exiftool": {"winget": ["OliverBetz.ExifTool"], "choco": ["exiftool"]},
    "7zip": {"winget": ["7zip.7zip"], "choco": ["7zip"]},
    "wiztree": {"winget": ["AntibodySoftware.WizTree"], "choco": ["wiztree"]},
}
EXPLICIT_ONLY = {"wiztree"}


def _installer():
    """('winget'|'choco', path) on Windows, or (None, None)."""
    if not IS_WIN:
        return None, None
    for name in ("winget", "choco"):
        path = shutil.which(name)
        if path:
            return name, path
    return None, None


def _commands(key, manager):
    ids = PACKAGES.get(key, {}).get(manager)
    if not ids:
        return None
    if manager == "winget":
        return [["winget", "install", "--id", i, "--exact", "--silent", "--accept-package-agreements",
                 "--accept-source-agreements", "--disable-interactivity"] for i in ids]
    return [["choco", "install", i, "-y", "--no-progress"] for i in ids]


def _missing():
    out = []
    for key, tool in tools.TOOLS.items():
        if key == "robocopy" or tools.PLATFORM not in tool.platforms:
            continue
        if tools.locate(key)["found"]:
            continue
        out.append(key)
    return out


def cmd_setup(args):
    manager, manager_path = _installer()
    missing = _missing()
    wanted = None
    if args.tools:
        wanted = [t.strip().lower() for t in args.tools.split(",") if t.strip()]
        unknown = [t for t in wanted if t not in tools.TOOLS or t == "robocopy"]
        if unknown:
            raise LfkError("bad_argument", f"unknown tool(s) {unknown}; choose from "
                           + ", ".join(k for k in tools.TOOLS if k != "robocopy"), exit_code=2)
    elif args.all:
        wanted = [k for k in missing if k not in EXPLICIT_ONLY]

    plan = []
    for key in missing:
        tool = tools.TOOLS[key]
        cmds = _commands(key, manager) if manager else None
        entry = {"tool": key, "label": tool.label, "purpose": tool.purpose, "license": tool.license,
                 "homepage": tool.homepage}
        if cmds:
            entry["how"] = manager
            entry["commands"] = [" ".join(c) for c in cmds]
        else:
            entry["how"] = "manual"
            entry["commands"] = tools.install_advice(key)["install"]
        if key in EXPLICIT_ONLY:
            entry["note"] = "Free for personal use only; business use needs a WizTree licence. Not part of --all."
        elif key == "digup":
            entry["note"] = "Not in a package manager: download it from the homepage, open it once to fetch its model."
        plan.append(entry)
    result = {"ok": True, "platform": tools.PLATFORM, "installer": manager, "missing": plan}
    if not missing:
        result.update(mode="nothing to do", message="Every supported tool is already installed.")
        return result

    if not args.yes or not wanted:
        result["mode"] = "preview"
        result["next_step"] = ("Nothing was installed. Show this list (and its licences) to the user; after a clear yes, "
                               "run setup --all --yes (everything except WizTree) or setup --tools a,b --yes.")
        if not IS_WIN:
            result["next_step"] = "Automatic install is Windows-only here: run the commands shown, then doctor."
        return result

    if not IS_WIN:
        raise LfkError("not_supported", "automatic install is Windows-only; run the commands in 'missing' yourself",
                       exit_code=2, missing=plan)
    if not manager:
        raise LfkError("no_installer", "neither winget nor Chocolatey was found; install the tools by hand from the "
                       "homepages listed, or install winget (App Installer) from the Microsoft Store", exit_code=3,
                       missing=plan)

    done = []
    for key in wanted:
        if key not in missing:
            done.append({"tool": key, "status": "already installed"})
            continue
        cmds = _commands(key, manager)
        if not cmds:
            done.append({"tool": key, "status": "manual", "commands": tools.install_advice(key)["install"]})
            continue
        codes = []
        for c in cmds:
            rc, out, err = run([manager_path] + c[1:], timeout=args.max_seconds, encoding="utf-8")
            codes.append(rc)
        done.append({"tool": key, "status": "ran", "exit_codes": codes})

    tools._cache.clear()  # look again: the installers just put things in place
    started = _start_everything_if_needed() if "everything" in wanted else None
    for d in done:
        if d["status"] == "ran":
            info = tools.probe(d["tool"])
            d["found"] = info.get("found", False)
            d["path"] = info.get("path")
            d["status"] = "installed" if info.get("found") else "failed (see exit_codes; try the command by hand)"
    result.update(mode="executed", results=done)
    if started:
        result["everything_started"] = started
    result["ok"] = all(d["status"] in ("installed", "already installed") for d in done)
    result["next_step"] = "Run doctor to see what every feature now uses."
    return result


def _start_everything_if_needed():
    """es.exe answers only while Everything runs; after a fresh install it may not be running yet."""
    es = tools.locate("everything")
    if not es["found"]:
        return None
    rc, _, _ = run([es["path"], "-get-everything-version"], timeout=15)
    if rc == 0:
        return None
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        exe = os.path.join(base or "", "Everything", "Everything.exe")
        if base and os.path.isfile(exe):
            subprocess.Popen([exe, "-startup"], creationflags=0x00000008)  # DETACHED_PROCESS
            return exe
    return None
