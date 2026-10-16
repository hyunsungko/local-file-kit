"""Measure Korean search quality and speed of DigUp + EmbeddingGemma 2 on made-up documents.

Usage:
  python tests/eval_korean.py <empty work folder> [--cpu] [--json results.json]

Needs DigUp installed (or LFK_DIGUP pointing at its helper) with its model. Indexes only the made-up
documents, into a separate index inside the work folder; the DigUp app's own index is not touched.
"""
import argparse
import json
import os
import re
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "local-file-kit", "scripts"))
sys.path.insert(0, HERE)

from korean_eval_data import DOCS, PASSAGE_QUERIES, QUERIES  # noqa: E402
from lfkit import content, textread, tools  # noqa: E402
from lfkit.util import run  # noqa: E402


def write_docs(folder):
    os.makedirs(folder, exist_ok=True)
    for name, paras in DOCS.items():
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write("\n\n".join(paras) + "\n")


def index(digup, docs, idx, env):
    t = time.perf_counter()
    rc, out, err = run([digup, "index", docs, "--index", idx], timeout=3600, env=env)
    secs = time.perf_counter() - t
    if rc != 0:
        raise SystemExit(f"index failed: {err[-500:]}")
    return secs


def search(digup, idx, q, env, zgate):
    cmd = [digup, "search", q, "--json", "-n", "10", "--index", idx]
    if zgate is not None:
        cmd += ["--zgate", str(zgate)]
    t = time.perf_counter()
    rc, out, err = run(cmd, timeout=300, env=env)
    secs = time.perf_counter() - t
    rows = json.loads(out) if out.strip() else []
    return [os.path.basename(r["path"]) for r in rows], rows, secs


def metrics(ranks):
    n = len(ranks)
    return {"n": n,
            "top1": round(sum(1 for r in ranks if r == 1) / n, 3),
            "top3": round(sum(1 for r in ranks if r and r <= 3) / n, 3),
            "mrr": round(sum(1 / r for r in ranks if r) / n, 3)}


def lexical_rank(q, expected):
    terms = [t for t in re.split(r"[\s,.?!ㅠ]+", q.lower()) if len(t) >= 2]
    scores = []
    for name, paras in DOCS.items():
        text = (name + " " + " ".join(paras)).lower()
        scores.append((sum(1 for t in terms if t in text), name))
    scores.sort(key=lambda s: -s[0])
    for i, (s, name) in enumerate(scores[:10], 1):
        if name == expected and s > 0:
            return i
    return None


def run_device(digup, work, device_cpu):
    env = dict(os.environ)
    tag = "cpu" if device_cpu else "auto"
    if device_cpu:
        env["DIGUP_DEVICE"] = "cpu"
    docs = os.path.join(work, "docs")
    idx = os.path.join(work, f"idx-{tag}")
    out = {"device": "cpu (DIGUP_DEVICE=cpu)" if device_cpu else "auto (GPU when DigUp finds it faster)"}
    out["index_seconds"] = round(index(digup, docs, idx, env), 2)

    per_group, detail, lat, shown = {}, [], [], {}
    for group, q, expected in QUERIES:
        names, rows, secs = search(digup, idx, q, env, 0)
        lat.append(secs)
        rank = names.index(expected) + 1 if expected in names else None
        default_names, _, _ = search(digup, idx, q, env, None)
        per_group.setdefault(group, []).append(rank)
        shown.setdefault(group, []).append(expected in default_names)
        top = rows[0] if rows else {}
        detail.append({"group": group, "query": q, "expected": expected, "rank": rank,
                       "top": os.path.basename(top.get("path", "")), "top_z": round(top.get("z", 0), 2),
                       "shown_with_default_gate": expected in default_names,
                       "lexical_rank": lexical_rank(q, expected)})
    out["search_seconds_median"] = round(statistics.median(lat), 3)
    out["groups"] = {g: {**metrics(r), "shown_with_default_gate": round(sum(shown[g]) / len(shown[g]), 3),
                         "lexical_top1": round(sum(1 for d in detail if d["group"] == g and d["lexical_rank"] == 1)
                                               / len(r), 3)}
                     for g, r in per_group.items()}
    out["overall"] = metrics([d["rank"] for d in detail])
    out["queries"] = detail

    # passages: which paragraph inside a file answers the question
    right = 0
    p_detail = []
    t = time.perf_counter()
    count = 0
    with content.Embedder(digup, env=env) as emb:
        for q, name, want in PASSAGE_QUERIES:
            parts = textread.passages(textread.read_text(os.path.join(docs, name)))
            qv = emb.embed([content.query_prompt(q)])[0]
            vecs = emb.embed([content.document_prompt(name, p) for p in parts])
            count += len(parts) + 1
            best = max(range(len(parts)), key=lambda i: content.cosine(qv, vecs[i]))
            # short paragraphs are merged into one passage, so compare text, not positions
            hit = DOCS[name][want] in parts[best]
            right += hit
            p_detail.append({"query": q, "file": name, "expected_paragraph": want, "passages_in_file": len(parts),
                             "correct": hit})
        all_parts = [p for paras in DOCS.values() for p in paras]
        t2 = time.perf_counter()
        emb.embed([content.document_prompt("none", p) for p in all_parts])
        embed_secs = time.perf_counter() - t2
    out["passages"] = {"n": len(PASSAGE_QUERIES), "top1": round(right / len(PASSAGE_QUERIES), 3), "detail": p_detail}
    out["embed_paragraphs_per_second"] = round(len(all_parts) / embed_secs, 1)
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # CI consoles (cp1252) cannot print Korean otherwise
    ap = argparse.ArgumentParser()
    ap.add_argument("work")
    ap.add_argument("--cpu", action="store_true", help="also run everything with DIGUP_DEVICE=cpu")
    ap.add_argument("--json")
    a = ap.parse_args()
    if os.path.exists(a.work) and os.listdir(a.work):
        raise SystemExit(f"{a.work} is not empty")
    digup = tools.require("digup")
    write_docs(os.path.join(a.work, "docs"))
    result = {"documents": len(DOCS), "queries": len(QUERIES), "passage_queries": len(PASSAGE_QUERIES),
              "digup": tools.probe("digup").get("version"), "runs": [run_device(digup, a.work, False)]}
    if a.cpu:
        result["runs"].append(run_device(digup, a.work, True))
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    summary = {r["device"]: {"overall": r["overall"], "groups": {g: v for g, v in r["groups"].items()},
                             "passages_top1": r["passages"]["top1"], "index_seconds": r["index_seconds"],
                             "search_seconds_median": r["search_seconds_median"],
                             "embed_paragraphs_per_second": r["embed_paragraphs_per_second"],
                             "misses": [{k: q[k] for k in ("query", "expected", "rank", "top")}
                                        for q in r["queries"] if q["rank"] != 1],
                             "passage_misses": [p["query"] for p in r["passages"]["detail"] if not p["correct"]]}
               for r in result["runs"]}
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
