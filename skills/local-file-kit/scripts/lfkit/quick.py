"""q: one question, both searches. File names (Everything, plus drives it does not index through 'serve') and what
files say (the DigUp index through 'serve') run at the same time; the results are merged, copies of one file are folded
into one line, and a content match comes with the passage and where it is.
"""
import datetime as _dt
from functools import lru_cache
import json
import math
import os
import re
import threading
import time

from . import find, serve, tools
from .util import IS_WIN, LfkError, abspath, iso_time, parse_date

# Words that only say when: they set --after/--before instead of being searched for.
DAY = 86400
EXPANSION_SECONDS = 2.5
MERGE_RESERVE_SECONDS = 1.
_expansion_gate = threading.BoundedSemaphore(1)
EXPANSION_NOTE = "expansion time budget limited retrieval; returning completed results (some candidates may be missing)"


def _remaining(out, default=120):
    deadline = out.get("_deadline")
    if deadline is None:
        return default
    left = deadline - time.monotonic()
    if left <= 0:
        raise LfkError("expansion_timeout", "expansion time limit reached")
    return left


def _es_search(out, *args):
    return find._es_run(*args, **({"timeout": _remaining(out)} if "_deadline" in out else {}))


JOSA = ("에서", "으로", "에게", "까지", "부터", "이랑", "하고", "을", "를", "은", "는", "에", "의")
AMBIGUOUS_JOSA = ("이나", "이", "가", "와", "과")
FILLER = {"찾아", "찾아줘", "찾아봐", "줘", "좀", "파일", "문서", "자료", "관련", "관련된", "거", "것", "그", "내가", "제가",
          "쓴", "만든", "했던", "있는", "대한", "대해", "어디", "어딨어", "있어", "있나", "the", "a", "an", "of", "file", "files"}
# Words that name a kind of file: they narrow nothing by themselves but count for a name with that extension.
TYPE_WORDS = {
    "pdf": {"pdf"}, "hwp": {"hwp", "hwpx"}, "hwpx": {"hwp", "hwpx"}, "한글": {"hwp", "hwpx"}, "한글파일": {"hwp", "hwpx"},
    "엑셀": {"xls", "xlsx", "xlsm", "csv"}, "excel": {"xls", "xlsx", "xlsm", "csv"}, "xlsx": {"xls", "xlsx"},
    "워드": {"doc", "docx"}, "word": {"doc", "docx"}, "docx": {"doc", "docx"}, "ppt": {"ppt", "pptx"},
    "pptx": {"ppt", "pptx"}, "피피티": {"ppt", "pptx"}, "발표자료": {"ppt", "pptx", "pdf"},
    "사진": {"jpg", "jpeg", "png", "heic", "webp"}, "그림": {"jpg", "jpeg", "png", "webp", "gif", "bmp", "svg"},
    "이미지": {"jpg", "jpeg", "png", "webp", "gif", "bmp", "svg"}, "캡처": {"png", "jpg"}, "스크린샷": {"png", "jpg"},
    "스캔": {"pdf", "jpg", "jpeg", "png", "tif", "tiff"}, "영상": {"mp4", "mov", "mkv", "avi", "webm"},
    "동영상": {"mp4", "mov", "mkv", "avi", "webm"}, "녹음": {"m4a", "mp3", "wav"},
    "글": {"txt", "md", "mdx", "pdf", "doc", "docx", "hwp", "hwpx", "html", "htm", "rtf", "odt"},
    "코드": {"py", "js", "jsx", "ts", "tsx", "swift", "rs", "go", "java", "kt", "c", "cpp", "h", "cs",
             "rb", "php", "sh", "ps1", "sql", "vue", "svelte", "html", "css", "mdx"},
}
KIND_EXTS = {
    "image": {"jpg", "jpeg", "png", "gif", "bmp", "webp", "heic", "tif", "tiff", "svg"},
    "screenshot": {"png", "jpg", "jpeg"}, "pdf": {"pdf"},
    "doc": {"doc", "docx", "hwp", "hwpx", "txt", "md", "mdx", "rtf", "odt", "ppt", "pptx", "xls", "xlsx", "csv", "html"},
    "audio": {"mp3", "m4a", "wav", "flac", "ogg"}, "video": {"mp4", "mov", "mkv", "avi", "webm"},
    "code": {"py", "js", "jsx", "ts", "tsx", "swift", "rs", "go", "java", "kt", "kts", "c", "h", "cpp", "hpp",
             "cs", "rb", "php", "sh", "ps1", "sql", "vue", "svelte", "html", "css", "scss", "json", "yaml", "yml"},
}
# Places whose files are rarely what a person is looking for: ranked lower, never hidden.
SYSTEM_PARTS = ("\\windows\\", "\\program files", "\\programdata\\", "\\appdata\\", "\\node_modules\\", "\\.git\\",
                "\\site-packages\\", "\\__pycache__\\", "\\$recycle.bin", "\\.cache\\", "\\.venv\\", "\\venv\\")
# Places that usually hold a second copy: the other copy is shown first.
COPY_PARTS = ("backup", "백업", "worktree", "\\tmp\\", "\\temp\\", "\\.claude\\", "\\old\\", "legacy",
              "보관", "사본", "\\copy\\", "copy of ")
COPY_SUFFIX = re.compile(r"(\s*\(\d+\)|\s*-\s*복사본(\s*\(\d+\))?|\s*-\s*copy(\s*\(\d+\))?|\s+copy)$", re.I)


def _dates_from_words(text, today=None):
    """'오늘', '어제', '이번 주', '지난주', '이번 달', '올해', '작년' -> (text without them, after, before)."""
    today = today or _dt.date.today()
    rules = [
        (r"오늘|today", today, today + _dt.timedelta(1)),
        (r"어제|yesterday", today - _dt.timedelta(1), today),
        (r"이번\s*주|this week", today - _dt.timedelta(today.weekday()), today + _dt.timedelta(1)),
        (r"지난\s*주|last week", today - _dt.timedelta(today.weekday() + 7), today - _dt.timedelta(today.weekday())),
        (r"이번\s*달|this month", today.replace(day=1), today + _dt.timedelta(1)),
        (r"올해|this year", today.replace(month=1, day=1), today + _dt.timedelta(1)),
        (r"작년|last year", today.replace(year=today.year - 1, month=1, day=1), today.replace(month=1, day=1)),
    ]
    for i, (pattern, after, before) in enumerate(rules):
        m = re.search(r"(?<!\S)(" + pattern + r")(에|에서|의)?(?!\S)", text, re.I)
        if m:
            text = (text[:m.start()] + " " + text[m.end():]).strip()
            return re.sub(r"\s+", " ", text), after, before, i < 4  # a day or a week: a filter; a month or year: a hint
    return text, None, None, False


def _words(text):
    """The words a name may hold: fillers and one-letter words out, a trailing particle off."""
    words, types = [], set()
    for raw in re.split(r"[\s,·/]+", text.lower()):
        w = raw.strip("\"'()[]{}<>?!.~")
        if not w or w in FILLER:
            continue
        variants = _word_variants(w)
        typed = set().union(*(TYPE_WORDS.get(v, set()) for v in variants))
        if typed:
            types |= typed
            continue
        if len(w) >= 3 and w.endswith(("한", "된", "던", "하는", "있는", "없는")):  # 설명한, 정리된: says how, not a name
            continue
        if len(w) >= 2 and w not in words:
            words.append(w)
    return words[:12], types


def _word_variants(word):
    """Keep the literal spelling as well: a final syllable may belong to the noun."""
    variants = [word]
    for suffix in JOSA + AMBIGUOUS_JOSA + ("한", "된", "던", "하는"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 2:
            variants.append(word[:-len(suffix)])
    if re.fullmatch(r"\d+[년월일]", word):
        variants.append(word[:-1])
    return list(dict.fromkeys(variants))


def _compact(text):
    return re.sub(r"[\W_]+", "", text.lower())


def _coverage(words, name):
    name = _compact(name)
    return sum(any(_compact(v) in name for v in _word_variants(w)) for w in words) / len(words) if words else 1.0


def _path_coverage(groups, name, parent, prepared=None, compact=_compact):
    """Alternatives replace, rather than dilute, the original query's evidence."""
    compact_name, compact_parent = compact(name), compact(parent)
    best = (0., 0., 0.)
    prepared = prepared or [[([_compact(v) for v in _word_variants(w)], 1.) for w in words] for words in groups]
    for terms in prepared:
        if not terms:
            continue
        filename = folder = 0
        total = sum(weight for variants, weight in terms)
        for variants, weight in terms:
            if any(v in compact_name for v in variants):
                filename += weight
            elif any(v in compact_parent for v in variants):
                folder += weight
        evidence = ((filename + .4 * folder) / total, filename / total, folder / total)
        best = max(best, evidence)
    return best if any(groups) else (1., 1., 0.)


def _es_term(word):
    # ES parses the raw Windows command line itself; embedded quoted argv is not
    # portable across ES versions. Only literal token characters reach its grammar.
    variants = [re.sub(r"[^\w.-]", "", v) for v in _word_variants(word)]
    return "<" + "|".join(v for v in variants if v) + ">"


def _epoch(d):
    return time.mktime(d.timetuple()) if d else None


# --------------------------------------------------------------------------------------------- names


def _es_filters(exts, after, before, file_only=False):
    parts = ["file:"] if file_only else []
    if exts:
        parts.append("ext:" + ";".join(sorted(exts)))
    if after:
        parts.append("dm:>=" + after.isoformat())
    if before:
        parts.append("dm:<" + before.isoformat())
    return parts


def _names(words, exts, after, before, unders, out):
    """Bounded literal-word queries: a conversational word cannot hide the useful noun."""
    prior = out.get("_prior_names")
    if prior:
        out.update(prior)
        out.setdefault("profile", {})["names_reused"] = True
        return
    es = tools.locate("everything")
    if not words and not (exts or after):
        out["names_engine"] = None
        return
    if not es.get("found"):
        out["names_engine"] = "none"
        return
    if not words:  # only a kind of file and/or a date ("오늘 만든 영상"): the newest such files
        rows = []
        for under in unders or [None]:
            rows += _es_search(out, es["path"], under, _es_filters(exts, after, before, file_only=True), 200,
                                 "date-modified-descending")
        out["names_engine"] = "everything"
        out["names"] = [{"path": r["path"], "is_dir": False, "size": r.get("size"), "mtime": r.get("_mtime")} for r in rows]
        return
    terms = [_es_term(w) for w in words]
    # One OR per scope keeps process and query costs bounded. Rank the returned
    # names locally; a conversational word must not exclude the useful nouns.
    expanded = out.get("expanded", False)
    expression = "<" + "|".join(terms) + ">"
    groups = [(expression, 2000)]
    if expanded:
        # A separate quota prevents a common term from consuming the entire
        # expanded pool. Pairs may span a parent folder and its filename.
        groups = [(term, 1000) for term in terms]
    found = {}
    lock = threading.Lock()
    errors = []

    def one(group, under):
        try:
            expression, limit = group
            rows = _es_search(out, es["path"], under, expression.split() + _es_filters(exts, after, before, file_only=True),
                                limit, None if expanded else "date-modified-descending")
            if len(rows) >= limit:
                out["names_truncated"] = True
        except LfkError as e:
            errors.append(e)
            if e.code in ("timeout", "expansion_timeout"):
                out["timed_out"] = True
            return
        with lock:
            for r in rows:
                found.setdefault(r["path"], r)

    threads = [threading.Thread(target=one, args=(g, u), daemon=True) for g in groups for u in (unders or [None])]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if expanded and not found:
        # If no name term matches, the words may describe only the folder.
        # Avoid a global full-path disjunction on every ordinary name query.
        expression = "path:<" + " ".join(terms) + ">"
        for under in unders or [None]:
            one((expression, 3000), under)
    if expanded and not found:
        # A joined word with no literal candidates may be a spaced filename.
        # Bound regex work; applying it to every conversational word is costly.
        spaced = sorted({v for w in words for v in _word_variants(w)
                         if re.fullmatch(r"[가-힣]{3,12}", v)}, key=lambda v: (-len(v), v))[:2]
        if spaced:
            expression = "<" + "|".join("regex:" + r"[\x20_.-]*".join(v) for v in spaced) + ">"
            for under in unders or [None]:
                one((expression, 1000), under)
    if errors:
        out["names_error"] = errors[0].message
    out["names_engine"] = "everything"
    out["names"] = [{"path": r["path"], "is_dir": r["is_dir"], "size": r.get("size"), "mtime": r.get("_mtime")}
                    for r in found.values()]


def _names_elsewhere(words, exts, after, before, out):
    """Drives Everything does not index, from the list 'serve' keeps."""
    if not words:
        return
    variants = list(dict.fromkeys(v for w in words for v in _word_variants(w)))
    reply = serve.ask({"op": "names", "words": variants, "exts": sorted(exts) if exts else None,
                       "after": _epoch(after), "before": _epoch(before),
                       "limit": 1500 if out.get("expanded") else 300}, timeout=_remaining(out, 30))
    if reply and reply.get("ok"):
        out["other_drives"] = reply.get("drives") or []
        out["other_names"] = reply.get("items", [])
        out["other_walked"] = reply.get("walked")


# --------------------------------------------------------------------------------------------- content


def _content(query, kinds, unders, limit, out):
    replies = {}
    def search(code):
        label = "code" if code else "semantic"
        # Do not repeat a search that already took longer than the remaining
        # expansion budget. Its first-pass hits remain usable, with a note.
        previous = out.get("_prior_profile", {}).get(label, 0)
        if previous and previous >= max(0., out.get("_deadline", float("inf")) - time.monotonic()):
            replies[code] = {"hits": [h for h in out.get("_prior_hits", []) if bool(h.get("_code")) == code],
                             "meaning": out.get("meaning", False)}
            out.setdefault("profile", {})[label + "_reused"] = True
            out["timed_out"] = True
            return
        request = {"op": "search", "q": query, "limit": limit, "code": code}
        if kinds and not code:
            request["kinds"] = [k for k in kinds if k != "code"]
        if unders:
            request["under"] = unders
        try:
            began = time.monotonic()
            if "_deadline" in out:
                request["_deadline"] = out["_deadline"]
                reply = serve.ask_index(request, timeout=_remaining(out), autostart=False)
            else:
                reply = serve.ask_index(request)
        except LfkError as e:
            reply = {"error": e.message}
            if e.code in ("timeout", "expansion_timeout"):
                out["timed_out"] = True
        out.setdefault("profile", {})[label] = round(time.monotonic() - began, 4)
        if reply and reply.get("ms"):
            out.setdefault("engine_ms", {})[label] = reply["ms"]
        if not reply or "hits" not in reply:
            out["content_error"] = (reply or {}).get("error") or "DigUp search service is not available"
            return
        replies[code] = reply
    jobs = [threading.Thread(target=search, args=(code,), daemon=True) for code in (False, True)
            if not kinds or not ((code and "code" not in kinds) or (not code and kinds == ["code"]))]
    for job in jobs:
        job.start()
    for job in jobs:
        job.join()
    out["hits"] = []
    # Thread completion order must never change ranking or segment namespaces.
    for code in (False, True):
        reply = replies.get(code, {})
        hits = [dict(h, _rank=i, _code=code, **({"kind": "code"} if code else {}))
                for i, h in enumerate(reply.get("hits", []))]
        out["hits"] += hits
        out["meaning"] = bool(out.get("meaning") or reply.get("meaning"))


# --------------------------------------------------------------------------------------------- merge


def _norm(path):
    return path.replace("/", "\\") if IS_WIN else path


def _copy_key(path, size):
    stem, ext = os.path.splitext(os.path.basename(path).lower())
    return COPY_SUFFIX.sub("", stem).strip() + ext, size


def _place_rank(path):
    low = path.lower()
    return (any(p in low for p in SYSTEM_PARTS), sum(p in low for p in COPY_PARTS), len(path))


def _present(path):
    return os.path.exists(path)


def _weak(results):
    """Rank fusion scores are not confidence: a perfect content-only hit used
    to be capped below the threshold. Use filename coverage or the selected
    passage's semantic evidence instead. These are heuristics, not probabilities.
    """
    if not results:
        return True
    top = results[0]
    if top.get("_type_mismatch"):
        return True
    if top.get("name_words", 0) >= .75 and top.get("_score", 0) >= .4:
        return False
    evidence = top.get("_evidence") or {}
    z, cosine = evidence.get("z") or 0, evidence.get("cosine") or 0
    if evidence.get("rank", 999) <= 1:
        if evidence.get("code"):
            return not (z >= 6 and cosine >= .8)
        if evidence.get("rank") == 0 and cosine >= .75:
            # A matching folder alone is weaker than a matching filename.
            if (top.get("name_words", 0) >= .25 and z >= 2) or (top.get("path_words", 0) >= .25 and z >= 4.5):
                return False
        if (z >= 6.5 and cosine >= .78) or (evidence.get("rank") == 0 and z >= 3.5 and cosine >= .82):
            return False
    return True


def _live_results(results, limit):
    """Everything may retain an unplugged drive or a deleted file. Check only
    the leading candidates; never read their bodies or walk the filesystem.
    """
    live, stale = [], 0
    for result in results[:max(50, limit * 4)]:
        paths = result.get("_copy_paths") or [result["path"]] + result.get("other_places", [])
        paths = [p for p in paths if _present(p)]
        if not paths:
            stale += 1
            continue
        result = dict(result, path=paths[0])
        result.pop("copies", None)
        result.pop("other_places", None)
        if len(paths) > 1:
            result.update(copies=len(paths), other_places=paths[1:6])
        live.append(result)
        if len(live) >= limit:
            break
    return live, stale


def cmd_q(args):
    if args.limit < 1:
        raise LfkError("bad_argument", "--limit must be positive", exit_code=2)
    started = time.monotonic()
    out = _query_once(args)
    fast_seconds = time.monotonic() - started
    initial_weak = out["weak"]
    profiles = {"fast": out.pop("profile", {})}
    side = out.pop("_candidates")
    expansion_seconds = 0.
    if initial_weak:
        expanded_at = time.monotonic()
        completed, errors = [], []
        # The outer guard includes merging, excerpt lookup and unresponsive IPC.
        # One outstanding worker per process prevents a stalled service from
        # accumulating expansion work in callers that reuse this module.
        def expand():
            try:
                completed.append(_query_once(args, expanded=True, prior=side,
                                             deadline=expanded_at + EXPANSION_SECONDS))
            except Exception as e:
                errors.append(e)
            finally:
                _expansion_gate.release()
        if _expansion_gate.acquire(blocking=False):
            worker = threading.Thread(target=expand, daemon=True)
            worker.start()
            worker.join(max(0., expanded_at + EXPANSION_SECONDS - time.monotonic()))
        if errors:
            raise errors[0]
        if completed:
            out = completed[0]
            profiles["expansion"] = out.pop("profile", {})
            out.pop("_candidates")
        else:
            # Keep the already merged first pass if the expansion cannot even
            # finish merging within its budget. No worker mutates this result.
            out.setdefault("notes", []).append(EXPANSION_NOTE)
            profiles["expansion"] = {"timed_out": True}
        expansion_seconds = time.monotonic() - expanded_at
    out["timing"] = {"fast_seconds": round(fast_seconds, 3), "expansion_seconds": round(expansion_seconds, 3)}
    out["timing"]["stages"] = profiles
    out["expanded"] = initial_weak
    out["seconds"] = round(time.monotonic() - started, 2)
    return out


def _query_once(args, expanded=False, prior=None, deadline=None):
    started = time.time()
    query = args.query.strip()
    if not query:
        raise LfkError("bad_argument", "what to look for?", exit_code=2)
    text, after, before, hard = _dates_from_words(query)
    dates_from_query = after is not None
    hint = None
    if dates_from_query and not hard:  # "작년에 쓴 ...": files from then rank higher, others still count
        hint, after, before = (_epoch(after), _epoch(before)), None, None
    if args.after:
        after = _dt.date.fromtimestamp(parse_date(args.after))
    if args.before:
        before = _dt.date.fromtimestamp(parse_date(args.before))
    words, type_exts = _words(text)
    alternatives = [a.strip() for a in (getattr(args, "also", None) or []) if a.strip()]
    groups = [words] + [_words(a)[0] for a in alternatives]
    search_words = list(dict.fromkeys(w for g in groups for w in g))
    exts = {e.strip().lstrip(".").lower() for e in (args.ext or "").split(",") if e.strip()}
    kinds = [k for k in (args.kind or "").split(",") if k]
    bad = [k for k in kinds if k not in KIND_EXTS]
    if bad:
        raise LfkError("bad_argument", f"unknown kind(s) {bad}; use {','.join(KIND_EXTS)}", exit_code=2)
    kind_exts = set()
    for k in kinds:
        kind_exts |= KIND_EXTS[k]
    name_exts = exts & kind_exts if exts and kinds else (exts or kind_exts)
    if exts and kinds and not name_exts:
        return {"ok": True, "query": query, "count": 0, "results": [],
                "seconds": round(time.time() - started, 2),
                "weak": True, "_candidates": {},
                "notes": ["--ext and --kind have no file types in common", "못 찾았을 수 있음"]}
    unders = [os.path.realpath(abspath(u)) for u in (args.under or [])]
    for u in unders:
        if not os.path.isdir(u):
            raise LfkError("not_found", f"--under is not a folder: {u}", exit_code=2)
    filtered = bool(exts or after or before)

    side = {"expanded": expanded, "profile": {}}
    if deadline is not None:
        side["_deadline"] = deadline - MERGE_RESERVE_SECONDS
    if prior:
        side["_prior_hits"] = prior.get("hits", [])
        side["_prior_profile"] = prior.get("profile", {})
        side["meaning"] = prior.get("meaning", False)
        if prior.get("names") and not prior.get("names_truncated") and not prior.get("names_error"):
            side["_prior_names"] = {k: prior[k] for k in ("names", "names_engine") if k in prior}
    def timed(label, fn, *values):
        began = time.monotonic()
        try:
            fn(*values)
        except LfkError as e:
            side[label + "_error"] = e.message
            if e.code in ("timeout", "expansion_timeout"):
                side["timed_out"] = True
        finally:
            side["profile"][label] = round(time.monotonic() - began, 4)
    content_text = " ".join([text or query] + alternatives)
    jobs = [threading.Thread(target=timed, args=("names", _names, search_words, name_exts, after, before, unders, side), daemon=True),
            threading.Thread(target=_content, args=(content_text, kinds, unders,
                                                    max(args.limit, 5) * (20 if expanded else 6 if filtered else 3), side), daemon=True)]
    if not unders:
        jobs.append(threading.Thread(target=timed, args=("other_names", _names_elsewhere, search_words, name_exts, after, before, side), daemon=True))
    for t in jobs:
        t.start()
    for t in jobs:
        t.join()
    merge_at = time.monotonic()
    if prior:
        for key in ("names", "other_names", "hits"):
            side[key] = side.get(key, []) + prior.get(key, [])

    # Opt-in diagnostics contain metadata only, never indexed passages or text.
    if os.environ.get("LFK_Q_DUMP"):
        snapshot = {k: v for k, v in side.items() if not k.startswith("_")}
        for key in ("hits",):
            if key in side:
                snapshot[key] = [{k: v for k, v in h.items() if k in
                                 {"path", "kind", "size", "modified", "z", "score", "cosine", "keyword_rank", "_rank", "_code"}}
                                for h in side[key]]
        with open(os.environ["LFK_Q_DUMP"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"query": query, "side": snapshot}, ensure_ascii=False) + "\n")

    # Names: how many of the words each name holds; files before folders; the person's own places first.
    entries = {}
    name_rows = side.get("names", []) + side.get("other_names", [])
    # A filename is evidence regardless of which engine returned it.
    name_rows += [dict(path=h["path"], size=h.get("size"), mtime=h.get("modified"), is_dir=False)
                  for h in side.get("hits", []) if h.get("path")]
    lo_after, lo_before = _epoch(after), _epoch(before)
    scored = []
    # Rare terms distinguish a named project from generic words such as
    # 'results'. Count distinct names so backup copies do not distort rarity.
    # Repeated basenames and shared parent paths need normalizing only once in
    # this merge. The cache is local to the query and never written to disk.
    compact = lru_cache(maxsize=None)(_compact)
    corpus = {compact(os.path.basename(r['path'])) for r in name_rows}
    prepared = []
    for group in groups:
        terms = []
        for word in group:
            variants = [_compact(v) for v in _word_variants(word)]
            df = sum(any(v in name for v in variants) for name in corpus)
            weight = min(3., 1. + math.log((len(corpus) + 1) / (df + 1))) if df else 1.
            terms.append((variants, weight))
        prepared.append(terms)
    seen_names = set()
    for r in name_rows:
        path = _norm(r["path"])
        key = os.path.normcase(path)
        if key in seen_names:
            continue
        seen_names.add(key)
        if unders and not any(_under(path, u) for u in unders):
            continue
        name = os.path.basename(path).lower()
        ext = os.path.splitext(name)[1].lstrip(".")
        mtime = r.get("mtime")
        if name_exts and (r.get("is_dir") or ext not in name_exts):
            continue
        if (lo_after and (mtime or 0) < lo_after) or (lo_before and (mtime or 0) >= lo_before):
            continue
        coverage, filename_coverage, folder_coverage = _path_coverage(groups, name, os.path.dirname(path), prepared, compact)
        if words and not coverage:
            continue
        typed = bool(type_exts) and ext in type_exts
        scored.append(((-coverage, -typed, r["is_dir"], _place_rank(path)[0], -(r.get("mtime") or 0), path.lower()),
                       path, r, coverage, typed, filename_coverage, folder_coverage))
    scored.sort(key=lambda s: s[0])
    name_ranks = {}
    for _, path, r, coverage, typed, filename_coverage, folder_coverage in scored:
        copy_key = _copy_key(path, r["size"]) if r.get("size") is not None and not r["is_dir"] else path
        rank = name_ranks.setdefault(copy_key, len(name_ranks))
        e = entries.setdefault(os.path.normcase(path), {"path": path})
        e.update(is_dir=r["is_dir"], size=r.get("size"), _mtime=r.get("mtime"))
        e["_name"] = 0.8 * coverage ** 2 * (0.4 if _place_rank(path)[0] else 1.0) / (1 + 0.02 * rank)
        if hint and r.get("mtime") and hint[0] <= r["mtime"] < hint[1]:
            e["_name"] *= 1.5
        e["name_words"] = round(filename_coverage, 2)
        e["path_words"] = round(folder_coverage, 2)

    # Content: DigUp's order, filtered the same way as the names.
    rank = 0
    for h in side.get("hits", []):
        path = _norm(h.get("path") or "")
        if not path:
            continue
        if unders and not any(_under(path, u) for u in unders):
            continue
        mtime = h.get("modified")
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        if name_exts and ext not in name_exts:
            continue
        if (lo_after and (mtime or 0) < lo_after) or (lo_before and (mtime or 0) >= lo_before):
            continue
        e = entries.setdefault(os.path.normcase(path), {"path": path})
        if "_content" in e:
            continue
        e["_content"] = 1.0 / (4 + h.get("_rank", rank)) * (1.5 if hint and mtime and hint[0] <= mtime < hint[1] else 1.0)
        rank += 1
        e.update(size=h.get("size"), _mtime=mtime, is_dir=False, kind=h.get("kind"), z=_round(h.get("z")),
                 _segment=h.get("segment_id"), _code=h.get("_code", False),
                 _evidence={"rank": h.get("_rank", rank - 1), "z": h.get("z"), "cosine": h.get("cosine"),
                            "code": h.get("_code", False)})
        if h.get("loc") is not None:
            e["where"] = _where(h)
        if not args.no_excerpt and h.get("excerpt"):
            e["excerpt"] = h["excerpt"]

    # Fold copies: same name (without " (1)", " - 복사본") and size. The copy in the person's own place leads.
    groups = {}
    for e in entries.values():
        if e.get("is_dir"):
            key = ("dir", os.path.normcase(e["path"]))
        elif e.get("size") is not None:
            key = _copy_key(e["path"], e.get("size"))
        else:
            key = ("unknown-size", os.path.normcase(e["path"]))
        groups.setdefault(key, []).append(e)
    results = []
    for members in groups.values():
        score = max(m.get("_name", 0) for m in members) + max(m.get("_content", 0) for m in members)
        members.sort(key=lambda m: (_place_rank(m["path"]), -(m.get("_content", 0) + m.get("_name", 0))))
        lead = dict(members[0])
        for m in members[1:]:  # what a copy knows (the passage) goes on the lead line
            for k in ("excerpt", "where", "kind", "z", "_segment", "_code", "_content", "_name", "name_words", "path_words", "_evidence"):
                if k not in lead and k in m:
                    lead[k] = m[k]
        lead["why"] = "both" if lead.get("_content") and lead.get("_name") else ("content" if lead.get("_content") else "name")
        if len(members) > 1:
            lead["copies"] = len(members)
            lead["other_places"] = [m["path"] for m in members[1:6]]
            lead["_copy_paths"] = [m["path"] for m in members]
        lead["_score"] = score
        if type_exts and os.path.splitext(lead["path"])[1].lstrip(".").lower() not in type_exts:
            lead["_score"] *= 0.35
            lead["_type_mismatch"] = True
        results.append(lead)
    results.sort(key=lambda r: -r["_score"])
    results, stale = _live_results(results, args.limit)
    weak = _weak(results)
    side["profile"]["merge"] = round(time.monotonic() - merge_at, 4)

    excerpt_at = time.monotonic()
    if not args.no_excerpt:  # a content hit with no excerpt: the indexed text of that spot
        for r in results:
            if r.get("why") != "name" and not r.get("excerpt") and r.get("_segment") is not None:
                if deadline is not None and time.monotonic() >= deadline - .05:
                    side["timed_out"] = True
                    break
                request = {"op": "text", "segment": r["_segment"], "code": r.get("_code", False)}
                if deadline is not None:
                    request["_deadline"] = deadline - .05
                try:
                    reply = serve.ask(request, timeout=max(.001, deadline - .05 - time.monotonic()) if deadline else 20)
                except LfkError as e:
                    if e.code != "timeout":
                        raise
                    side["timed_out"] = True  # a passage is extra: answer without the rest
                    break
                if reply and isinstance(reply.get("text"), str) and reply["text"].strip():
                    r["excerpt"] = re.sub(r"\s+", " ", reply["text"]).strip()[:300]
    side["profile"]["excerpts"] = round(time.monotonic() - excerpt_at, 4)
    for r in results:
        r["modified"] = iso_time(r.pop("_mtime", None))
        for k in [k for k in r if k.startswith("_")]:
            r.pop(k)
        if not r.get("is_dir"):
            r.pop("is_dir", None)

    out = {"ok": True, "query": query, "count": len(results), "results": results,
           "searched": {"names": side.get("names_engine"), "content": "digup" if "hits" in side else None},
           "seconds": round(time.time() - started, 2), "weak": weak, "_candidates": side,
           "profile": dict(side["profile"], engine_ms=side.get("engine_ms", {}))}
    if words:
        out["name_words"] = words
    if after or before:
        out["dates"] = {"after": after.isoformat() if after else None, "before": before.isoformat() if before else None}
    if hint:
        out["dates_preferred"] = {"from": iso_time(hint[0])[:10], "before": iso_time(hint[1])[:10]}
    notes = []
    if side.get("timed_out"):
        notes.append(EXPANSION_NOTE if expanded else
                     "the search service did not answer in time; some results or passages may be missing")
    if weak:
        notes.append("못 찾았을 수 있음")
    if stale:
        notes.append(f"{stale} leading candidates are no longer accessible and were omitted")
    if side.get("content_error"):
        notes.append("content search: " + side["content_error"])
    if side.get("names_error"):
        notes.append("name search: " + side["names_error"])
    if side.get("names_truncated"):
        notes.append("name candidates reached the per-scope limit; narrow --under, --ext or the question for older matches")
    if side.get("names_engine") == "none":
        notes.append("Everything is not available: names were not searched (run setup, or use find --root)")
    elif side.get("other_drives"):
        notes.append("names on " + ", ".join(side["other_drives"]) + " come from a list made at "
                     + str(side.get("other_walked")) + " (Everything does not index them)")
    elif IS_WIN and not expanded and side.get("names_engine") == "everything" and not unders and "other_drives" not in side:
        missed = _drives_everything_misses()
        if missed:
            notes.append("names not searched on " + ", ".join(missed) + " (Everything does not index them and the "
                         "search service, which lists them, is not running)")
    if notes:
        out["notes"] = notes
    return out


def _drives_everything_misses():
    es = tools.locate("everything")
    if not es.get("found"):
        return []
    drives = [d + ":\\" for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.isdir(d + ":\\")]
    return [d for d in drives if not find._root_indexed(es["path"], d)]


def _where(hit):
    loc = hit.get("loc")
    kind = hit.get("kind")
    if kind == "pdf":
        return f"p. {int(loc)}"
    if kind in ("audio", "video"):
        return f"{int(loc) // 60}:{int(loc) % 60:02d}"
    if kind == "code":
        return f"line {int(loc)}" + (f"–{int(hit['loc_end'])}" if hit.get("loc_end") is not None else "")
    return f"part {int(loc) + 1}" if isinstance(loc, (int, float)) else str(loc)


def _under(path, root):
    p = os.path.normcase(path)
    r = os.path.normcase(root.rstrip("\\/"))
    return p == r or p.startswith(r + os.sep)


def _round(x):
    return round(x, 2) if isinstance(x, float) else x
