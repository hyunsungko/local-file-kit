"""search / index / status: file contents by meaning, through DigUp's helper CLI (official 0.7.0-beta.1 commands only).

The "passages" step pairs DigUp with EmbeddingGemma 2 directly: DigUp finds the files (one best spot per file),
then `digup worker --text-only` embeds every paragraph of those files so the best few paragraphs come back too.
"""
import base64
import json
import math
import os
import re
import struct
import subprocess

from . import textread, tools
from .util import IS_MAC, IS_WIN, LfkError, abspath, iso_time, run

NEEDED = ("search", "index", "status", "estimate", "worker")
MODEL_FILES = ("embeddinggemma-2-Q8_0.gguf", "mmproj-embeddinggemma-2-Q8_0.gguf")
KINDS = ("screenshot", "image", "pdf", "doc", "audio", "video")
TEXT_DOC_EXTS = "txt,md,markdown,rtf,docx,odt,html,htm"  # what official DigUp reads as documents


def query_prompt(text):
    return "task: search result | query: " + text


def document_prompt(title, text):
    return "title: " + (title or "none") + " | text: " + text


def app_dir(helper):
    """The DigUp app folder: the helper lives in <app>/helper/ (Windows, Linux) or <app>/Contents/Helpers/ (macOS)."""
    return os.path.dirname(os.path.dirname(helper))


def model_dirs(helper):
    if os.environ.get("DIGUP_MODELS"):
        return [os.environ["DIGUP_MODELS"]]
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
        return [os.path.join(base, "DigUp", "Models")]
    if IS_MAC:
        return [os.path.expanduser("~/Library/Application Support/DigUp/Models")]
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return [os.path.join(base, "digup", "Models")]


def probe_digup(path):
    info = {}
    rc, out, err = run([path, "--help"], timeout=30)
    text = out + err
    missing = [c for c in NEEDED if not re.search(r"^\s*digup " + c + r"\b", text, re.M)]
    info["commands_ok"] = not missing
    if missing:
        info["problem"] = "this DigUp helper lacks commands local-file-kit uses: " + ", ".join(missing)
    if IS_WIN:
        info["version"] = tools.file_version(os.path.join(app_dir(path), "DigUp.exe"))
    models = None
    for d in model_dirs(path):
        if all(os.path.isfile(os.path.join(d, f)) for f in MODEL_FILES):
            models = d
    info["model_found"] = bool(models)
    info["model_dir"] = models
    if not models:
        info["model_note"] = ("EmbeddingGemma 2 files not found in DigUp's Models folder. Open the DigUp app once, "
                              "or run the helper's 'download-model' command (about 865 MB): "
                              f'"{path}" download-model')
    info["ready"] = info["commands_ok"]
    info["app_running"] = app_running()
    return info


def app_running():
    """Is the DigUp desktop app running (it indexes on its own)? None when unknown."""
    if not IS_WIN:
        return None
    try:
        rc, out, _ = run(["tasklist", "/FI", "IMAGENAME eq DigUp.exe", "/FO", "CSV", "/NH"], timeout=15,
                         encoding="mbcs")
    except LfkError:
        return None
    # tasklist matches image names case-insensitively, so the helper digup.exe shows up too: count rows only
    return out.count('"DigUp.exe"') > 0 if rc == 0 else None


def _env(args):
    env = dict(os.environ)
    if getattr(args, "cpu", False):
        env["DIGUP_DEVICE"] = "cpu"
    return env


def _index_args(args):
    return ["--index", abspath(args.index)] if getattr(args, "index", None) else []


# --------------------------------------------------------------------------------------------- search


def cmd_search(args):
    roots = [os.path.realpath(abspath(r)) for r in (args.root or [])]  # long names, as the tools report them
    engine = args.engine
    if engine == "auto":
        engine = "text" if roots else "digup"
    if engine == "text":
        from . import textsearch
        if not roots:
            raise LfkError("need_root", "text search reads the files of a folder: give --root DIR "
                           "(without --root, search uses the DigUp index)", exit_code=2)
        for r in roots:
            if not os.path.isdir(r):
                raise LfkError("not_found", f"not a folder: {r}", exit_code=2)
        if args.estimate:
            return textsearch.cmd_estimate_text(args, roots)
        return textsearch.cmd_search_text(args, roots)
    if args.estimate:
        raise LfkError("bad_argument", "--estimate is for text search (--root); for the DigUp index use "
                       "index DIR --estimate", exit_code=2)
    digup = tools.require("digup")
    n = args.limit * (5 if roots else 1)
    cmd = [digup, "search", *args.query.split(), "--json", "-n", str(n)] + _index_args(args)
    if args.kind:
        bad = [k for k in args.kind.split(",") if k not in KINDS]
        if bad:
            raise LfkError("bad_argument", f"unknown kind(s) {bad}; use {','.join(KINDS)}", exit_code=2)
        cmd += ["--kind", args.kind]
    if args.zgate is not None:
        cmd += ["--zgate", str(args.zgate)]
    rc, out, err = run(cmd, timeout=600, env=_env(args))
    if rc != 0:
        _fail("search", rc, err, digup)
    try:
        rows = json.loads(out) if out.strip() else []
    except ValueError:
        raise LfkError("tool_failed", "digup search did not return JSON", stdout=out[:500])
    results = []
    for r in rows:
        path = r.get("path", "").replace("/", os.sep) if IS_WIN else r.get("path", "")
        if roots and not any(_under(path, root) for root in roots):
            continue
        item = {"path": path, "kind": r.get("kind"), "z": _round(r.get("z")), "cosine": _round(r.get("cosine")),
                "segment": r.get("segment"), "loc": r.get("loc"), "size": r.get("size"),
                "modified": iso_time(r.get("modified"))}
        if not args.no_excerpt and r.get("excerpt"):
            item["excerpt"] = r["excerpt"]
        results.append(item)
        if len(results) >= args.limit:
            break
    out_obj = {"ok": True, "engine": "digup", "query": args.query, "count": len(results), "results": results}
    if not results:
        out_obj["hint"] = ("Nothing stood out. DigUp hides weak matches (z below 2.0): try other words, "
                           "--zgate 0 to see everything ranked, or check 'status' that the folder is indexed.")
    if args.passages and results:
        _add_passages(digup, args, results)
    return out_obj


def _fail(what, rc, err, digup):
    if "embeddinggemma-2" in err and ("not found" in err or "no " in err):
        raise LfkError("model_missing", "DigUp's model (EmbeddingGemma 2, about 865 MB) is not downloaded yet",
                       exit_code=3, fix=["Open the DigUp app once and let it finish setup",
                                         f'or run: "{digup}" download-model'], stderr=err.strip()[-400:])
    raise LfkError("tool_failed", f"digup {what} exited with code {rc}", stderr=err.strip()[-800:])


def _under(path, root):
    p = os.path.normcase(os.path.abspath(path))
    r = os.path.normcase(root.rstrip("\\/"))
    return p == r or p.startswith(r + os.sep)


def _round(x):
    return round(x, 4) if isinstance(x, float) else x


# --------------------------------------------------------------------------------------------- passages


class Embedder:
    """`digup worker --text-only` as a child process: JSON lines in, base64 float32 vectors out."""

    def __init__(self, digup, env=None):
        kwargs = {"creationflags": 0x08000000} if IS_WIN else {}
        self.p = subprocess.Popen([digup, "worker", "--text-only"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, env=env, **kwargs)
        self.next_id = 0
        ready = self._read()
        if not ready.get("ready"):
            self.close()
            raise LfkError("tool_failed", "digup worker did not start", detail=ready)
        self.info = ready.get("info", {})

    def _read(self):
        line = self.p.stdout.readline()
        if not line:
            raise LfkError("tool_failed", "digup worker stopped (is the model installed? run doctor)")
        return json.loads(line.decode("utf-8"))

    def embed(self, texts, batch=16):
        vecs = []
        for i in range(0, len(texts), batch):
            self.next_id += 1
            req = {"id": self.next_id, "op": "text", "inputs": texts[i:i + batch]}
            self.p.stdin.write((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
            self.p.stdin.flush()
            resp = self._read()
            if not resp.get("ok"):
                raise LfkError("tool_failed", "digup worker failed", detail=resp)
            raw = base64.b64decode(resp["vectors"])
            dim = resp["dim"]
            flat = struct.unpack("<%df" % (len(raw) // 4), raw)
            for j in range(resp["count"]):
                vecs.append(flat[j * dim:(j + 1) * dim])
        return vecs

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _add_passages(digup, args, results, max_per_file=200):
    todo = []
    for r in results:
        path = r["path"]
        if not os.path.isfile(path):
            r["passages_skipped"] = "file not found"
            continue
        ext = os.path.splitext(path)[1].lower()
        if ext not in textread.READABLE:
            r["passages_skipped"] = f"{ext or 'this kind of file'} has no text to read here (DigUp's excerpt is the best spot)"
            continue
        try:
            text = textread.read_text(path)
        except OSError as e:
            r["passages_skipped"] = f"cannot read: {e}"
            continue
        parts = textread.passages(text or "")[:max_per_file]
        if not parts:
            r["passages_skipped"] = "no text inside (a scan or picture-only file)"
            continue
        todo.append((r, parts))
    if not todo:
        return
    with Embedder(digup, env=_env(args)) as emb:
        q = emb.embed([query_prompt(args.query)])[0]
        for r, parts in todo:
            title = os.path.basename(r["path"])
            vecs = emb.embed([document_prompt(title, p) for p in parts])
            scored = sorted(((cosine(q, v), i) for i, v in enumerate(vecs)), reverse=True)[:args.passages]
            r["passages"] = [{"rank": k + 1, "cosine": round(s, 4), "index": i,
                              **({} if args.no_excerpt else {"text": parts[i]})} for k, (s, i) in enumerate(scored)]
            r["passages_total"] = len(parts)


# --------------------------------------------------------------------------------------------- index / status


def cmd_index(args):
    digup = tools.require("digup")
    folders = [abspath(f) for f in args.folders]
    for f in folders:
        if not os.path.isdir(f):
            raise LfkError("not_found", f"not a folder: {f}", exit_code=2)
    extra = []
    for d in args.exclude or []:
        extra += ["--exclude", abspath(d)]
    if args.media_only:  # text documents are cheaper to search as text (search --root); index the rest
        extra += ["--exclude-ext", TEXT_DOC_EXTS + (",pdf" if args.no_pdf else "")]
    elif args.no_pdf:
        raise LfkError("bad_argument", "--no-pdf goes with --media-only", exit_code=2)
    if args.estimate:
        rc, out, err = run([digup, "estimate", *folders, "--json"] + _index_args(args) + extra, timeout=3600, env=_env(args))
        if rc != 0:
            _fail("estimate", rc, err, digup)
        est = json.loads(out)
        return {"ok": True, "estimate": _slim_estimate(est)}
    if not args.index and app_running() and not args.force:
        raise LfkError("digup_app_running", "The DigUp app is running and keeps its own index up to date. Add the "
                       "folder in the DigUp app instead, or pass --index DIR for a separate index, or --force.",
                       exit_code=2)
    if args.limit:
        extra += ["--limit", str(args.limit)]
    rc, out, err = run([digup, "index", *folders] + _index_args(args) + extra, timeout=args.timeout, env=_env(args))
    if rc != 0 and "embeddinggemma-2" in err:
        _fail("index", rc, err, digup)
    text = out + "\n" + err
    summary = {"ok": rc == 0, "folders": folders}
    m = re.search(r"^sync: (.+)$", text, re.M)
    if m:
        summary["sync"] = m.group(1).strip()
    m = re.search(r"^done in (.+)$", text, re.M)
    if m:
        summary["done"] = m.group(1).strip()
    failed = [l.strip() for l in text.splitlines() if re.search(r"\]\s+\w+\s+(failed|error)", l)]
    if failed:
        summary["failed"] = failed[:50]
    skipped = len(re.findall(r"\]\s+\w+\s+skipped", text))
    if skipped:
        summary["skipped_files"] = skipped
    if rc != 0:
        summary.update(error="tool_failed", message=f"digup index exited with code {rc}", tail=text.strip()[-1500:])
    return summary


def _slim_estimate(est):
    keep = ("files", "bytes", "seconds", "later_seconds", "pdf_pages", "long_files", "skipped", "calibrated", "readable",
            "audio_seconds", "video_seconds")
    out = {k: est.get(k) for k in keep if k in est}
    if est.get("seconds") is not None:
        out["minutes"] = round(est["seconds"] / 60, 1)
    out["note"] = ("DigUp's own estimate. 'calibrated': false means it is scaled from DigUp's reference machine, "
                   "not measured on this computer (run 'digup speed --model' once to calibrate).")
    return out


def cmd_status(args):
    digup = tools.require("digup")
    rc, out, err = run([digup, "status"] + _index_args(args), timeout=120, env=_env(args))
    if rc != 0:
        _fail("status", rc, err, digup)
    status = {"ok": True, "kinds": {}}
    for line in out.splitlines():
        m = re.match(r"^index:\s*(.+)$", line)
        if m:
            status["index"] = m.group(1).strip()
        m = re.match(r"^vectors:\s*(\d+)", line)
        if m:
            status["vectors"] = int(m.group(1))
        m = re.match(r"^\s+(screenshot|image|pdf|doc|audio|video|code)\s+(\d+)\s+(.*)$", line)
        if m:
            status["kinds"][m.group(1)] = {"files": int(m.group(2)), "state": m.group(3).strip()}
        m = re.match(r"^size:\s*(.+)$", line)
        if m:
            status["size"] = m.group(1).strip()
        m = re.match(r"^built with:\s*(.+)$", line)
        if m:
            status["model"] = m.group(1).strip()
    status["app_running"] = app_running()
    return status
