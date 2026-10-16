"""CI only: run `setup` for real on a throw-away machine and check that doctor then finds the tools.

  python tests/ci_setup_check.py everything,czkawka,exiftool

Do not run this on your own PC: it installs software (that is what it tests).
"""
import json
import os
import subprocess
import sys

LFK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "local-file-kit", "scripts", "lfk.py")


def lfk(*args):
    p = subprocess.run([sys.executable, LFK, *args], capture_output=True)
    out = json.loads(p.stdout.decode("utf-8"))
    print("$ lfk.py", " ".join(args), "-> exit", p.returncode)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:4000])
    return p.returncode, out


def main():
    if not os.environ.get("CI"):
        raise SystemExit("refusing to run outside CI: this installs software")
    wanted = sys.argv[1].split(",")
    rc, preview = lfk("setup")
    assert rc == 0 and preview["mode"] in ("preview", "nothing to do"), preview
    forced = os.environ.get("LFK_INSTALLER")
    if forced and preview.get("installer") != forced:
        raise SystemExit(f"expected installer {forced}, got {preview.get('installer')}")
    rc, done = lfk("setup", "--tools", ",".join(wanted), "--yes")
    rc, doc = lfk("doctor")
    missing = [t for t in wanted if not doc["tools"][t]["found"]]
    if missing:
        raise SystemExit(f"setup did not install: {missing}")
    print("all installed:", wanted, "via", preview.get("installer"))


if __name__ == "__main__":
    main()
