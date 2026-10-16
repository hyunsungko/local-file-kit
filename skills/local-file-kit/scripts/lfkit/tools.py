"""Where each outside tool lives on this computer, and how to install it when it doesn't.

Search order for every tool (first hit wins):
  1. environment variable (LFK_ES, LFK_7Z, ...)
  2. config file "tools" section (see config_path())
  3. PATH
  4. usual install folders (Program Files, %LOCALAPPDATA%\\Programs, WinGet packages, /usr/bin, /opt, ...)
  5. Windows registry (uninstall entries, App Paths) unless LFK_NO_REGISTRY=1
"""
import glob
import json
import os
import re
import shutil

from .util import IS_MAC, IS_WIN, LfkError, run

PLATFORM = "windows" if IS_WIN else ("macos" if IS_MAC else "linux")


class Tool:
    def __init__(self, key, label, purpose, env, names, win_paths=(), unix_paths=(), registry=(),
                 platforms=("windows",), license="", homepage="", install=None, note=""):
        self.key = key
        self.label = label
        self.purpose = purpose
        self.env = env
        self.names = names            # {"windows": [...], "linux": [...], "macos": [...]}
        self.win_paths = win_paths    # templates with {ENVVAR}; globs allowed
        self.unix_paths = unix_paths  # globs; ~ allowed
        self.registry = registry      # uninstall DisplayName prefixes / App Paths exe names
        self.platforms = platforms
        self.license = license
        self.homepage = homepage
        self.install = install or {}
        self.note = note


WINGET_PKGS = r"{LOCALAPPDATA}\Microsoft\WinGet\Packages"

TOOLS = {
    "everything": Tool(
        "everything", "Everything + ES (es.exe)", "find files by name across NTFS drives in milliseconds",
        "LFK_ES", {"windows": ["es.exe"]},
        win_paths=[WINGET_PKGS + r"\voidtools.Everything.Cli_*\es.exe", r"{LOCALAPPDATA}\Microsoft\WinGet\Links\es.exe",
                   r"{ProgramFiles}\Everything\es.exe", r"{ProgramFiles(x86)}\Everything\es.exe",
                   r"{ProgramFiles}\Everything 1.5a\es.exe"],
        registry=[("uninstall", "ES (Everything CLI)", "es.exe"), ("uninstall", "Everything", "es.exe")],
        license="MIT", homepage="https://www.voidtools.com/downloads/",
        install={"windows": ["winget install voidtools.Everything", "winget install voidtools.Everything.Cli"],
                 "choco": ["choco install everything es"]},
        note="es.exe only answers while Everything itself is running. Everything indexes local NTFS/ReFS drives; "
             "network, FAT/exFAT and cloud-drive folders must be added under Options > Folders."),
    "digup": Tool(
        "digup", "DigUp (helper CLI)", "search file contents by meaning (EmbeddingGemma 2, on this computer)",
        "LFK_DIGUP", {"windows": ["digup.exe"], "linux": ["digup"], "macos": ["digup"]},
        win_paths=[r"{LOCALAPPDATA}\DigUp\helper\digup.exe", r"{ProgramFiles}\DigUp\helper\digup.exe"],
        unix_paths=["/usr/lib/DigUp/helper/digup", "/opt/DigUp/helper/digup",
                    "/Applications/DigUp.app/Contents/Helpers/digup", "~/Applications/DigUp.app/Contents/Helpers/digup"],
        registry=[("uninstall", "DigUp", r"helper\digup.exe")],
        platforms=("windows", "linux", "macos"), license="MIT", homepage="https://github.com/ARahim3/DigUp/releases",
        install={"windows": ["Download the Windows installer from https://github.com/ARahim3/DigUp/releases, run it, "
                             "open DigUp once so it fetches its model (about 865 MB)"],
                 "linux": ["Install the .deb or AppImage from https://github.com/ARahim3/DigUp/releases"],
                 "macos": ["Download DigUp for Apple Silicon (macOS 14+) from https://github.com/ARahim3/DigUp/releases"]},
        note="The helper CLI ships inside the DigUp app and is not a documented public interface; "
             "its commands may change between DigUp releases."),
    "wiztree": Tool(
        "wiztree", "WizTree", "folder and drive size breakdown (fast MFT scan when run as admin on NTFS)",
        "LFK_WIZTREE", {"windows": ["WizTree64.exe", "WizTree.exe"]},
        win_paths=[r"{ProgramFiles}\WizTree\WizTree64.exe", r"{ProgramFiles(x86)}\WizTree\WizTree64.exe",
                   r"{LOCALAPPDATA}\Programs\WizTree\WizTree64.exe"],
        registry=[("uninstall", "WizTree", "WizTree64.exe")],
        license="Proprietary freeware (free for personal use; business use needs a supporter/enterprise licence)",
        homepage="https://diskanalyzer.com/download",
        install={"windows": ["winget install AntibodySoftware.WizTree"], "choco": ["choco install wiztree"]},
        note="Business use of WizTree requires its own licence (see its EULA)."),
    "czkawka": Tool(
        "czkawka", "Czkawka CLI", "duplicate files, similar images, empty folders and files",
        "LFK_CZKAWKA",
        {"windows": ["windows_czkawka_cli.exe", "czkawka_cli.exe"],
         "linux": ["czkawka_cli", "linux_czkawka_cli_x86_64", "linux_czkawka_cli_arm64", "linux_czkawka_cli"],
         "macos": ["czkawka_cli", "mac_czkawka_cli_arm64", "mac_czkawka_cli"]},
        win_paths=[WINGET_PKGS + r"\qarmin.czkawka.cli_*\windows_czkawka_cli.exe",
                   r"{LOCALAPPDATA}\Microsoft\WinGet\Links\windows_czkawka_cli.exe"],
        unix_paths=["~/.local/bin/czkawka_cli", "/usr/local/bin/czkawka_cli"],
        registry=[("uninstall", "Czkawka", "windows_czkawka_cli.exe")],
        platforms=("windows", "linux", "macos"), license="MIT (CLI)",
        homepage="https://github.com/qarmin/czkawka/releases",
        install={"windows": ["winget install qarmin.czkawka.cli"],
                 "linux": ["Download linux_czkawka_cli_x86_64 from https://github.com/qarmin/czkawka/releases, "
                           "chmod +x it and put it on PATH as czkawka_cli"],
                 "macos": ["Download mac_czkawka_cli_arm64 from https://github.com/qarmin/czkawka/releases, "
                           "chmod +x it and put it on PATH as czkawka_cli"]}),
    "exiftool": Tool(
        "exiftool", "ExifTool", "photo and video metadata (date taken, camera, GPS, duration)",
        "LFK_EXIFTOOL", {"windows": ["exiftool.exe"], "linux": ["exiftool"], "macos": ["exiftool"]},
        win_paths=[r"{LOCALAPPDATA}\Programs\ExifTool\ExifTool.exe", r"{ProgramFiles}\ExifTool\ExifTool.exe",
                   WINGET_PKGS + r"\OliverBetz.ExifTool_*\ExifTool.exe"],
        registry=[("uninstall", "ExifTool", "ExifTool.exe")],
        platforms=("windows", "linux", "macos"), license="Perl licence (GPL-1.0+ or Artistic)",
        homepage="https://exiftool.org/",
        install={"windows": ["winget install OliverBetz.ExifTool"], "choco": ["choco install exiftool"],
                 "linux": ["sudo apt install libimage-exiftool-perl"], "macos": ["brew install exiftool"]}),
    "7zip": Tool(
        "7zip", "7-Zip", "create, list, test and extract archives (7z, zip and more)",
        "LFK_7Z", {"windows": ["7z.exe"], "linux": ["7zz", "7z", "7za"], "macos": ["7zz", "7z", "7za"]},
        win_paths=[r"{ProgramFiles}\7-Zip\7z.exe", r"{ProgramW6432}\7-Zip\7z.exe", r"{ProgramFiles(x86)}\7-Zip\7z.exe"],
        registry=[("7zip", "", "7z.exe"), ("apppath", "7zFM.exe", "7z.exe"), ("uninstall", "7-Zip", "7z.exe")],
        platforms=("windows", "linux", "macos"), license="LGPL-2.1+ (parts BSD; unRAR restriction)",
        homepage="https://www.7-zip.org/",
        install={"windows": ["winget install 7zip.7zip"], "choco": ["choco install 7zip"],
                 "linux": ["sudo apt install 7zip   (older distributions: p7zip-full)"], "macos": ["brew install sevenzip"]},
        note="Without 7-Zip, 'archive' still works for .zip files using Python's zipfile."),
    "robocopy": Tool(
        "robocopy", "Robocopy", "copy folders robustly (restartable, long paths, preview with /L)",
        "LFK_ROBOCOPY", {"windows": ["robocopy.exe"]},
        win_paths=[r"{SystemRoot}\System32\Robocopy.exe"],
        license="Part of Windows",
        homepage="https://learn.microsoft.com/windows-server/administration/windows-commands/robocopy",
        install={"windows": ["Built into Windows; nothing to install."]},
        note="Without robocopy (macOS/Linux), 'copy' uses Python's shutil."),
}


def config_path():
    if os.environ.get("LFK_CONFIG"):
        return os.environ["LFK_CONFIG"]
    if IS_WIN:
        base = os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "local-file-kit", "config.json")


def data_dir():
    """Where undo logs go (per user)."""
    if os.environ.get("LFK_DATA"):
        return os.environ["LFK_DATA"]
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    else:
        base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "local-file-kit")


def _load_config():
    p = config_path()
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise LfkError("bad_config", f"cannot read config file {p}: {e}")


def _expand_win(template):
    names = re.findall(r"\{([^}]+)\}", template)
    out = template
    for n in names:
        v = os.environ.get(n)
        if not v:
            return None
        out = out.replace("{" + n + "}", v)
    return out


def _registry_candidates(tool):
    if not IS_WIN or os.environ.get("LFK_NO_REGISTRY") == "1":
        return []
    import winreg
    found = []

    def read(root, sub, value=""):
        try:
            with winreg.OpenKey(root, sub) as k:
                return winreg.QueryValueEx(k, value)[0]
        except OSError:
            return None

    roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    for kind, name, exe in tool.registry:
        if kind == "7zip":
            for v in ("Path64", "Path"):
                for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    d = read(root, r"SOFTWARE\7-Zip", v)
                    if d:
                        found.append(os.path.join(d, exe))
        elif kind == "apppath":
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                p = read(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + name)
                if p:
                    found.append(os.path.join(os.path.dirname(p.strip('"')), exe))
        elif kind == "uninstall":
            for root, sub in roots:
                try:
                    with winreg.OpenKey(root, sub) as k:
                        i = 0
                        while True:
                            try:
                                child = winreg.EnumKey(k, i)
                            except OSError:
                                break
                            i += 1
                            dn = read(root, sub + "\\" + child, "DisplayName") or ""
                            if not dn.startswith(name):
                                continue
                            for value in ("InstallLocation", "DisplayIcon"):
                                d = (read(root, sub + "\\" + child, value) or "").strip().strip('"')
                                if not d:
                                    continue
                                if value == "DisplayIcon":
                                    d = os.path.dirname(d.split(",")[0])
                                found.append(os.path.join(d, exe))
                except OSError:
                    continue
    return found


_cache = {}


def locate(key):
    """Return {"found": bool, "path": str|None, "source": str} for a tool key."""
    if key in _cache:
        return _cache[key]
    tool = TOOLS[key]
    result = {"found": False, "path": None, "source": None}
    if PLATFORM not in tool.platforms:
        result["unsupported_platform"] = PLATFORM
        _cache[key] = result
        return result

    def hit(path, source):
        if path and os.path.isfile(path):
            result.update(found=True, path=os.path.abspath(path), source=source)
            return True
        return False

    env = os.environ.get(tool.env)
    if env:
        if not hit(env, "env:" + tool.env):
            result["warning"] = f"{tool.env} points to a missing file: {env}"
    if not result["found"]:
        cfg = (_load_config().get("tools") or {}).get(key)
        if cfg:
            if not hit(os.path.expandvars(os.path.expanduser(cfg)), "config"):
                result["warning"] = f"config file entry for {key} points to a missing file: {cfg}"
    if not result["found"]:
        for name in tool.names.get(PLATFORM, []):
            if hit(shutil.which(name), "PATH"):
                break
    if not result["found"]:
        templates = tool.win_paths if IS_WIN else tool.unix_paths
        for t in templates:
            pattern = _expand_win(t) if IS_WIN else os.path.expanduser(t)
            if not pattern:
                continue
            matches = sorted(glob.glob(pattern), reverse=True) if any(c in pattern for c in "*?") else [pattern]
            if any(hit(m, "default location") for m in matches):
                break
    if not result["found"]:
        for p in _registry_candidates(tool):
            if hit(p, "registry"):
                break
    _cache[key] = result
    return result


def require(key):
    """Path of a tool, or raise tool_missing with install advice."""
    loc = locate(key)
    if loc["found"]:
        return loc["path"]
    raise LfkError("tool_missing", f"{TOOLS[key].label} is not installed or not found", exit_code=3,
                   tool=key, **install_advice(key))


def install_advice(key):
    tool = TOOLS[key]
    adv = {"purpose": tool.purpose, "homepage": tool.homepage, "license": tool.license,
           "set_path_with": f"environment variable {tool.env}, or \"tools\": {{\"{key}\": \"<path>\"}} in {config_path()}"}
    if PLATFORM not in tool.platforms:
        adv["install"] = []
        adv["unsupported_platform"] = f"{tool.label} is not available on {PLATFORM}"
    else:
        cmds = list(tool.install.get(PLATFORM, []))
        if IS_WIN and tool.install.get("choco"):
            cmds += tool.install["choco"]
        adv["install"] = cmds
    if tool.note:
        adv["note"] = tool.note
    return adv


def file_version(path):
    """Windows file version resource (e.g. '4.32.0.0'), or None."""
    if not IS_WIN:
        return None
    import ctypes
    from ctypes import wintypes
    ver = ctypes.WinDLL("version")
    size = ver.GetFileVersionInfoSizeW(path, None)
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    if not ver.GetFileVersionInfoW(path, 0, size, buf):
        return None
    ptr = ctypes.c_void_p()
    length = wintypes.UINT()
    if not ver.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(length)) or not length.value:
        return None
    lang, cp = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD * 2)).contents
    key = "\\StringFileInfo\\%04x%04x\\ProductVersion" % (lang, cp)
    if ver.VerQueryValueW(buf, key, ctypes.byref(ptr), ctypes.byref(length)) and length.value:
        return ctypes.wstring_at(ptr, length.value - 1) or None
    return None


def probe(key):
    """Locate a tool and ask it for its version and readiness. Never raises."""
    loc = dict(locate(key))
    tool = TOOLS[key]
    info = {"label": tool.label, "purpose": tool.purpose, **loc}
    if not loc["found"]:
        info.update(install_advice(key))
        return info
    path = loc["path"]
    try:
        if key == "everything":
            _, out, _ = run([path, "-version"], timeout=10)
            info["version"] = out.strip() or None
            rc, out, _ = run([path, "-get-everything-version"], timeout=10)
            info["ready"] = rc == 0
            if rc == 0:
                info["everything_version"] = out.strip()
            else:
                info["problem"] = "Everything is not running (es.exe needs the Everything app running in the background)"
        elif key == "czkawka":
            _, out, _ = run([path, "--version"], timeout=20)
            m = re.search(r"(\d+\.\d+\.\d+)", out)
            info["version"] = m.group(1) if m else None
            info["ready"] = True
        elif key == "exiftool":
            _, out, _ = run([path, "-ver"], timeout=30)
            info["version"] = out.strip() or None
            info["ready"] = bool(info["version"])
        elif key == "7zip":
            _, out, _ = run([path], timeout=20)
            m = re.search(r"7-Zip[^\d]*(\d+\.\d+)", out)
            info["version"] = m.group(1) if m else None
            info["ready"] = True
        elif key == "wiztree":
            info["version"] = file_version(path)
            info["ready"] = True
            info["note"] = tool.note
        elif key == "robocopy":
            info["ready"] = True
        elif key == "digup":
            from . import content
            info.update(content.probe_digup(path))
    except LfkError as e:
        info["ready"] = False
        info["problem"] = e.message
    return info
