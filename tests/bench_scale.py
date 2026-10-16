"""Speed checks behind docs/SPECS.md. Prints numbers only, never file names.

  python tests/bench_scale.py docs <empty work folder> [--count 1000] [--pdfs 100] [--cpu]
      make <count> made-up Korean text files (1-3 KB) and <pdfs> 3-page PDFs; time DigUp indexing them into a
      separate index, and the first and second text-first search (search --root) on the same files
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


def make_pdfs(folder, count, pages=3, seed=2):
    """Simple program-made PDFs (Helvetica, English text), `pages` pages each."""
    rnd = random.Random(seed)
    paras = [p for name, ps in DOCS.items() if name.isascii() for p in ps]
    os.makedirs(folder, exist_ok=True)
    for n in range(count):
        objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
        kids = []
        for _ in range(pages):
            lines = []
            for p in rnd.sample(paras, 4):
                lines += [p[i:i + 80] for i in range(0, len(p), 80)] + [""]
            text = "BT /F1 11 Tf 60 760 Td 14 TL " + " ".join(
                "(%s) Tj T*" % l.replace("\\", "").replace("(", "").replace(")", "") for l in lines) + " ET"
            objs.append(f"<< /Length {len(text)} >>\nstream\n{text}\nendstream")
            objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {len(objs)} 0 R "
                        "/Resources << /Font << /F1 3 0 R >> >> >>")
            kids.append(f"{len(objs)} 0 R")
        objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {pages} >>"
        out, offsets = b"%PDF-1.4\n", []
        for i, o in enumerate(objs, 1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
        xref = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
        out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        with open(os.path.join(folder, f"report {n:04d}.pdf"), "wb") as f:
            f.write(out)


def compare(digup, folder, work, label, env, count):
    """DigUp index vs. text-first first search on the same folder."""
    idx = os.path.join(work, "idx-" + label)
    t = time.perf_counter()
    rc, so, se = run([digup, "index", folder, "--index", idx], timeout=7200, env=env)
    secs = time.perf_counter() - t
    size = os.path.getsize(os.path.join(idx, "index.sqlite"))
    tenv = dict(env, LFK_DATA=os.path.join(work, "lfk-data-" + label))
    first, _ = lfk_time("search", "deposit refund", "--root", folder, "--engine", "text", "--max-seconds", "7200",
                        env=tenv)
    again, _ = lfk_time("search", "deposit refund", "--root", folder, "--engine", "text", env=tenv)
    return {"files": count, "digup_index_seconds": round(secs, 1), "digup_index_ok": rc == 0,
            "digup_index_mb": round(size / 1e6, 1), "text_first_search_seconds": first,
            "text_next_search_seconds": again,
            "text_cache_mb": round(os.path.getsize(os.path.join(tenv["LFK_DATA"], "text-vectors.sqlite")) / 1e6, 1)}


def bench_docs(a):
    """Korean text notes, and program-made PDFs: DigUp index time vs. text-first first search, per device."""
    digup = tools.require("digup")
    docs = os.path.join(a.work, "docs")
    pdfs = os.path.join(a.work, "pdfs")
    total = make_docs(docs, a.count)
    make_pdfs(pdfs, a.pdfs)
    out = {"text_files": a.count, "text_mb": round(total / 1e6, 2), "pdf_files": a.pdfs, "pdf_pages": a.pdfs * 3,
           "runs": []}
    for cpu in ([False, True] if a.cpu else [False]):
        env = dict(os.environ)
        if cpu:
            env["DIGUP_DEVICE"] = "cpu"
        tag = "cpu" if cpu else "auto"
        out["runs"].append({"device": tag,
                            "text_notes": compare(digup, docs, a.work, "docs-" + tag, env, a.count),
                            "pdfs": compare(digup, pdfs, a.work, "pdfs-" + tag, env, a.pdfs)})
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
    s.add_argument("--count", type=int, default=1000, help="Korean text notes")
    s.add_argument("--pdfs", type=int, default=100, help="3-page PDFs")
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
