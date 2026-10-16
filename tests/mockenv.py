"""A pretend user profile with no tools installed (or only some), for testing on a machine that has them.

The profile lives under a user name with a space and Korean letters (e.g. ...\\Users\\김 철수\\...), PATH is cut
down to the system folders, and registry lookups are switched off (LFK_NO_REGISTRY=1). Tools can be "installed"
into the pretend profile by copying them where a real installer would put them.
"""
import os
import shutil
import sys

USER = "김 철수"


def make(base, tools=()):
    """Create the pretend profile under base and return the environment to run lfk.py in."""
    home = os.path.join(base, "Users", USER)
    env = {}
    for k in ("SystemRoot", "SystemDrive", "windir", "ComSpec", "PATHEXT", "TEMP", "TMP", "NUMBER_OF_PROCESSORS",
              "PROCESSOR_ARCHITECTURE", "OS", "LANG", "LC_ALL", "TMPDIR"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    if os.name == "nt":
        sysroot = os.environ.get("SystemRoot", r"C:\Windows")
        dirs = {"USERPROFILE": home, "HOME": home, "APPDATA": os.path.join(home, "AppData", "Roaming"),
                "LOCALAPPDATA": os.path.join(home, "AppData", "Local"),
                "ProgramFiles": os.path.join(base, "Program Files"),
                "ProgramFiles(x86)": os.path.join(base, "Program Files (x86)"),
                "ProgramW6432": os.path.join(base, "Program Files"), "ProgramData": os.path.join(base, "ProgramData")}
        env["PATH"] = os.pathsep.join([os.path.join(sysroot, "System32"), sysroot])
    else:
        dirs = {"HOME": home, "XDG_CONFIG_HOME": os.path.join(home, ".config"),
                "XDG_STATE_HOME": os.path.join(home, ".local", "state"),
                "XDG_DATA_HOME": os.path.join(home, ".local", "share")}
        env["PATH"] = os.path.join(base, "bin")  # empty: tools in /usr/bin (apt, brew) stay hidden
        os.makedirs(env["PATH"], exist_ok=True)
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    env.update(dirs)
    env["LFK_NO_REGISTRY"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    for name in tools:
        install(env, name)
    return env


def _copy_tree(src, dst):
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)


def install(env, name):
    """Copy a tool from this machine into the pretend profile, at its usual install location."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "local-file-kit", "scripts"))
    from lfkit import tools
    real = tools.locate(name)
    if not real["found"]:
        raise RuntimeError(f"{name} is not installed on this machine, cannot copy it")
    src = real["path"]
    if name == "7zip":
        _copy_tree(os.path.dirname(src), os.path.join(env["ProgramFiles"], "7-Zip"))
    elif name == "czkawka":
        _copy_tree(src, os.path.join(env["LOCALAPPDATA"], "Microsoft", "WinGet", "Packages",
                                     "qarmin.czkawka.cli_Microsoft.Winget.Source_8wekyb3d8bbwe", os.path.basename(src)))
    elif name == "exiftool":
        _copy_tree(os.path.dirname(src), os.path.join(env["LOCALAPPDATA"], "Programs", "ExifTool"))
    elif name == "digup":
        _copy_tree(os.path.dirname(src), os.path.join(env["LOCALAPPDATA"], "DigUp", "helper"))
    elif name == "wiztree":
        _copy_tree(os.path.dirname(src), os.path.join(env["ProgramFiles"], "WizTree"))
    elif name == "everything":
        _copy_tree(src, os.path.join(env["LOCALAPPDATA"], "Microsoft", "WinGet", "Packages",
                                     "voidtools.Everything.Cli_Microsoft.Winget.Source_8wekyb3d8bbwe", "es.exe"))
    else:
        raise ValueError(name)


if __name__ == "__main__":
    print(make(sys.argv[1], sys.argv[2:]))
