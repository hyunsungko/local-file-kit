"""search --root: text first. Read the words straight out of the files in a folder - no DigUp index needed.

1. Walk the folder and read the text of every file that has text (txt, md, docx, hwpx, pptx, xlsx, odt, html, rtf,
   and PDFs made by programs). Pictures, scans, audio and video are counted and left for DigUp's index.
2. Rank paragraphs by meaning with EmbeddingGemma 2 (the model inside DigUp, run as `digup worker`), or by shared
   words when DigUp is not installed.
3. Paragraph vectors are cached per file (path, size, time) so the next search in the same folder only reads what
   changed. The cache holds numbers, not the text.
"""
import os
import re
import sqlite3
import struct
import time
from math import sqrt
from operator import mul

from . import content, textread, tools
from .util import IS_WIN, LfkError, iso_time

MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif", ".tif", ".tiff",
              ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".mp4", ".mov", ".mkv", ".avi", ".webm"}
NO_TEXT_HERE = {".hwp", ".doc", ".xls", ".ppt"}
SKIP_DIRS = {"node_modules", "$recycle.bin", "system volume information", "__pycache__"}


# --------------------------------------------------------------------------------------------- files


def _walk(roots, max_files):
    files, media, unread, cloud = [], 0, {}, 0
    truncated = False
    for root in roots:
        stack = [root]
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
                            if (e.name.startswith(".") or e.name.lower() in SKIP_DIRS
                                    or (IS_WIN and getattr(st, "st_file_attributes", 0) & 0x400)):
                                continue
                            stack.append(e.path)
                            continue
                        if not e.is_file(follow_symlinks=False):
                            continue
                        ext = os.path.splitext(e.name)[1].lower()
                        if ext in MEDIA_EXTS:
                            media += 1
                            continue
                        if ext in NO_TEXT_HERE:
                            unread[ext] = unread.get(ext, 0) + 1
                            continue
                        if ext not in textread.READABLE:
                            continue
                        st = e.stat(follow_symlinks=False)
                        if IS_WIN and getattr(st, "st_file_attributes", 0) & (0x400000 | 0x1000):
                            cloud += 1  # cloud-only: reading it would download it
                            continue
                        files.append((e.path, st.st_size, st.st_mtime_ns))
                        if len(files) >= max_files:
                            truncated = True
                            stack = []
                            break
                    except OSError:
                        continue
    files.sort(key=lambda f: f[2], reverse=True)  # newest first: the most likely ones get read first
    return files, media, unread, cloud, truncated


def _passages(path):
    try:
        text = textread.read_text(path)
    except OSError:
        return None
    if text is None:
        return None
    return textread.passages(text)


# --------------------------------------------------------------------------------------------- cache


class Cache:
    def __init__(self, model_id):
        folder = tools.data_dir()
        os.makedirs(folder, exist_ok=True)
        self.db = sqlite3.connect(os.path.join(folder, "text-vectors.sqlite"))
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER, "
                        "n INTEGER, dim INTEGER, vecs BLOB)")
        row = self.db.execute("SELECT value FROM meta WHERE key='model'").fetchone()
        if row and row[0] != model_id:  # a different model: old numbers mean nothing
            self.db.execute("DELETE FROM files")
        self.db.execute("INSERT OR REPLACE INTO meta VALUES ('model', ?)", (model_id,))
        self.db.commit()

    def get(self, path, size, mtime):
        row = self.db.execute("SELECT size, mtime, n, dim, vecs FROM files WHERE path=?", (path,)).fetchone()
        if not row or row[0] != size or row[1] != mtime:
            return None
        n, dim, blob = row[2], row[3], row[4]
        if n == 0:
            return []
        flat = struct.unpack("<%df" % (n * dim), blob)
        return [flat[i * dim:(i + 1) * dim] for i in range(n)]

    def put(self, path, size, mtime, vecs):
        dim = len(vecs[0]) if vecs else 0
        blob = b"".join(struct.pack("<%df" % dim, *v) for v in vecs)
        self.db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?)", (path, size, mtime, len(vecs), dim, blob))

    def close(self):
        self.db.commit()
        self.db.close()


LAYOUT = "file+paragraphs v1"  # what a cached row holds; changing it invalidates the cache


def _model_id(info):
    return f"{info.get('model')}@{info.get('revision')}|{info.get('dtype')}|{info.get('dim')}|{LAYOUT}"


def _embed_file(emb, path, parts):
    """[vector of the whole file (first 2,000 characters), vector of each paragraph...], or [] when no text.
    The whole-file vector catches questions about what a short note is about as a whole."""
    if not parts:
        return []
    title = os.path.basename(path)
    texts = [content.document_prompt(title, p) for p in parts]
    if len(parts) > 1:
        texts.insert(0, content.document_prompt(title, "\n".join(parts)[:2000]))
    vecs = [_unit(v) for v in emb.embed(texts)]
    return vecs if len(parts) > 1 else vecs * 2


def _unit(v):
    n = sqrt(sum(x * x for x in v)) or 1.0
    return tuple(x / n for x in v)


def _dot(a, b):
    return sum(map(mul, a, b))


# --------------------------------------------------------------------------------------------- words


def _grams(s):
    s = re.sub(r"\s+", "", s.lower())
    return {s[i:i + 2] for i in range(len(s) - 1)} or ({s} if s else set())


def _word_score(qgrams, words, passage):
    if not qgrams:
        return 0.0
    low = passage.lower()
    score = len(qgrams & _grams(passage)) / len(qgrams)
    return score + 0.5 * sum(1 for w in words if w in low) / max(1, len(words))


# --------------------------------------------------------------------------------------------- search


def _model_ready():
    loc = tools.locate("digup")
    if not loc["found"]:
        return None, "DigUp not installed: ranked by shared words, not meaning"
    return loc["path"], None  # if the model is missing the worker fails to start and words are used instead


def cmd_search_text(args, roots):
    start = time.monotonic()
    budget = args.max_seconds
    files, media, unread, cloud, truncated = _walk(roots, args.max_files)
    digup, note = (None, "ranked by shared words (--words)") if args.words else _model_ready()
    out = {"ok": True, "engine": "text", "query": args.query, "roots": roots, "files_with_text": len(files)}
    if media:
        out["pictures_audio_video"] = media
    if unread:
        out["not_readable_as_text"] = unread
    if cloud:
        out["cloud_only_skipped"] = cloud
    if truncated:
        out["truncated"] = f"stopped listing at {args.max_files} files; narrow --root or raise --max-files"

    scored = []          # (score, path, size, mtime, passage index)
    read_now = cached = no_text = 0
    incomplete = 0
    if digup:
        try:
            emb = content.Embedder(digup, env=content._env(args))
        except LfkError as e:
            if e.code != "tool_failed":
                raise
            emb = None
            note = "DigUp's model could not start (run doctor): ranked by shared words, not meaning"
        if emb:
            info = emb.info
            model_id = _model_id(info)
            cache = None if args.no_cache else Cache(model_id)
            try:
                q = _unit(emb.embed([content.query_prompt(args.query)])[0])
                for path, size, mtime in files:
                    vecs = cache.get(path, size, mtime) if cache else None
                    if vecs is None:
                        if time.monotonic() - start > budget:
                            incomplete += 1
                            continue
                        parts = _passages(path)
                        if parts is None:
                            continue
                        vecs = _embed_file(emb, path, parts)
                        if cache:
                            cache.put(path, size, mtime, vecs)
                        read_now += 1
                    else:
                        cached += 1
                    if not vecs:
                        no_text += 1
                        continue
                    # vecs[0] is the whole file (its start), the rest are its paragraphs
                    per = [(_dot(q, v), i) for i, v in enumerate(vecs[1:])]
                    scored.append((max(_dot(q, vecs[0]), max(per)[0]), path, size, mtime, per))
                out["ranking"] = "meaning (EmbeddingGemma 2)"
            finally:
                emb.close()
                if cache:
                    cache.close()
    if not scored and not out.get("ranking"):
        out["ranking"] = "shared words"
        qg = _grams(args.query)
        words = [w.lower() for w in args.query.split() if len(w) > 1]
        for path, size, mtime in files:
            if time.monotonic() - start > budget:
                incomplete += 1
                continue
            parts = _passages(path)
            read_now += 1
            if not parts:
                no_text += 1 if parts == [] else 0
                continue
            sc = [(_word_score(qg, words, p), i) for i, p in enumerate(parts)]
            best = max(sc)
            if best[0] > 0:
                scored.append((best[0], path, size, mtime, sc))
    if note:
        out["note"] = note

    scored.sort(key=lambda s: s[0], reverse=True)
    results = []
    for score, path, size, mtime, per in scored[:args.limit]:
        per = sorted(per, reverse=True)
        item = {"path": path, "kind": "text", "score": round(score, 4), "loc": per[0][1] + 1, "size": size,
                "modified": iso_time(mtime / 1e9)}
        if not args.no_excerpt or args.passages:
            parts = _passages(path) or []
            if not args.no_excerpt and per[0][1] < len(parts):
                item["excerpt"] = parts[per[0][1]][:400]
            if args.passages:
                item["passages"] = [{"rank": k + 1, "score": round(s, 4), "index": i,
                                     **({} if args.no_excerpt or i >= len(parts) else {"text": parts[i]})}
                                    for k, (s, i) in enumerate(per[:args.passages])]
        results.append(item)
    out.update(count=len(results), results=results, files_read_now=read_now, files_from_cache=cached,
               seconds=round(time.monotonic() - start, 1))
    if no_text:
        out["files_without_text"] = no_text
        out["hint_no_text"] = ("Some files have no text inside (scanned PDFs, empty files). To search those by what "
                               "they show, index the folder with DigUp: index DIR --media-only --estimate")
    if media:
        out["hint_media"] = ("Pictures, audio and video are not read here. If DigUp has indexed them: "
                             "search \"...\" --engine digup --root DIR")
    if incomplete:
        out.update(incomplete=incomplete, hint_incomplete=(
            f"Time limit ({budget} s) reached: {incomplete} files not read yet. What was read is kept, so running "
            "the same search again continues; or raise --max-seconds, or narrow --root."))
    return out


def cmd_estimate_text(args, roots):
    """How much text a folder holds and how long the first text search will take (later ones use the cache)."""
    files, media, unread, cloud, truncated = _walk(roots, args.max_files)
    digup, note = _model_ready()
    uncached = list(files)
    if digup and not args.no_cache:
        try:
            emb = content.Embedder(digup, env=content._env(args))
        except LfkError:
            emb = None
        if emb:
            info = emb.info
            model_id = _model_id(info)
            cache = Cache(model_id)
            uncached = [f for f in files if cache.get(*f) is None]
            cache.close()
            sample, t0 = [], time.monotonic()
            passages_total = 0
            for path, size, mtime in uncached:
                parts = _passages(path) or []
                passages_total += len(parts) + (1 if len(parts) > 1 else 0)
                if len(sample) < 48:
                    sample += [content.document_prompt(os.path.basename(path), p) for p in parts[:48 - len(sample)]]
                if time.monotonic() - t0 > args.max_seconds:
                    break
            rate = None
            if sample:
                t1 = time.monotonic()
                emb.embed(sample)
                rate = len(sample) / max(1e-6, time.monotonic() - t1)
            emb.close()
            est = round(passages_total / rate) if rate else 0
            return {"ok": True, "engine": "text", "estimate": {
                "files_with_text": len(files), "files_to_read": len(uncached), "paragraphs_to_read": passages_total,
                "paragraphs_per_second": round(rate, 1) if rate else None, "seconds": est, "minutes": round(est / 60, 1),
                "pictures_audio_video": media, "not_readable_as_text": unread, "cloud_only_skipped": cloud,
                "note": "Only the first search reads everything; later searches reuse the stored numbers."}}
    return {"ok": True, "engine": "text", "estimate": {
        "files_with_text": len(files), "pictures_audio_video": media, "not_readable_as_text": unread,
        "cloud_only_skipped": cloud, "note": note or "ranked by shared words: no model work, reading only"}}
