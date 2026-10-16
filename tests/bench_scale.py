"""Speed checks behind docs/SPECS.md. Prints numbers only, never file names.

  python tests/bench_scale.py docs <empty work folder> [--count 1000] [--cpu]
      make <count> made-up Korean text files (1-3 KB) and time DigUp indexing them into a separate index
  python tests/bench_scale.py walk <folder>
      time size/find/dupes with and without the outside tools on a real folder (counts and seconds only)
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "skills", "local-file-kit", "scripts"))
LFK = os.path.join(HERE, "..", "skills", "local-file-kit", "scripts", "lfk.py")

from korean_eval_data import DOCS  # noqa: E402
from lfkit import tools  # noqa: E402
from lfkit.util import run  # noqa: E402


def make_docs(folder, count, seed=1):
    rnd = random.Random(seed)
    paras = [p for ps in DOCS.values() for p in ps]
    os.makedirs(folder, exist_ok=True)
    total = 0
    for i in range(count):
        body = "\n\n".join(rnd.sample(paras, rnd.randint(6, 18)))
        sub = os.path.join(folder, f"묶음 {i // 100:02d}")
        os.makedirs(sub, exist_ok=True)
        with open(os.path.join(sub, f"메모 {i:05d}.txt"), "w", encoding="utf-8") as f:
            f.write(body)
        total += len(body.encode("utf-8"))
    return total


def bench_docs(a):
    digup = tools.require("digup")
    docs = os.path.join(a.work, "docs")
    total = make_docs(docs, a.count)
    out = {"files": a.count, "mb": round(total / 1e6, 2), "runs": []}
    for cpu in ([False, True] if a.cpu else [False]):
        env = dict(os.environ)
        if cpu:
            env["DIGUP_DEVICE"] = "cpu"
        idx = os.path.join(a.work, "idx-cpu" if cpu else "idx-auto")
        t = time.perf_counter()
        rc, so, se = run([digup, "index", docs, "--index", idx], timeout=7200, env=env)
        secs = time.perf_counter() - t
        size = os.path.getsize(os.path.join(idx, "index.sqlite"))
        out["runs"].append({"device": "cpu" if cpu else "auto", "ok": rc == 0, "seconds": round(secs, 1),
                            "files_per_minute": round(a.count / secs * 60), "index_mb": round(size / 1e6, 1)})
    print(json.dumps(out, ensure_ascii=False, indent=1))


def lfk_time(*args, env=None):
    t = time.perf_counter()
    p = subprocess.run([sys.executable, LFK, *args], capture_output=True, env=env)
    secs = time.perf_counter() - t
    d = json.loads(p.stdout.decode("utf-8"))
    return round(secs, 2), d


def bench_walk(a):
    root = os.path.abspath(a.folder)
    res = {}
    for engine in ("wiztree", "walk"):
        if engine == "wiztree" and not tools.locate("wiztree")["found"]:
            continue
        secs, d = lfk_time("size", root, "--engine", engine, "--top", "1")
        res[f"size_{engine}"] = {"seconds": secs, "files": d.get("files"), "gb": round((d.get("total_bytes") or 0) / 1e9, 2)}
    for engine in ("everything", "walk"):
        if engine == "everything" and not tools.locate("everything")["found"]:
            continue
        secs, d = lfk_time("find", "zzzz-no-such-name", "--root", root, "--engine", engine, "--max-seconds", "3600")
        res[f"find_{engine}"] = {"seconds": secs, "walked_entries": d.get("walked_entries")}
    for engine in ("czkawka", "python"):
        if engine == "czkawka" and not tools.locate("czkawka")["found"]:
            continue
        secs, d = lfk_time("dupes", root, "--engine", engine, "--min-size", "100k", "--limit", "1")
        res[f"dupes_{engine}"] = {"seconds": secs, "groups": d.get("groups")}
    print(json.dumps(res, indent=1))


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # CI consoles (cp1252) cannot print Korean otherwise
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("docs")
    s.add_argument("work")
    s.add_argument("--count", type=int, default=1000)
    s.add_argument("--cpu", action="store_true")
    s = sub.add_parser("walk")
    s.add_argument("folder")
    a = ap.parse_args()
    if a.cmd == "docs":
        if os.path.exists(a.work) and os.listdir(a.work):
            raise SystemExit(f"{a.work} is not empty")
        bench_docs(a)
    else:
        bench_walk(a)


if __name__ == "__main__":
    main()
