"""Tests for lfk.py. Standard library only:  python -m unittest discover -s tests -v

- NoTools*: runs lfk.py in a pretend user profile ("김 철수", with a space) where no outside tool can be found,
  so every Python fallback is exercised. Works on any machine.
- WithTools*: uses the tools installed on this machine; each test is skipped when its tool is missing.
- DigUp tests run only with LFK_TEST_DIGUP=1 (they need DigUp and its ~865 MB model).
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "skills", "local-file-kit", "scripts")
LFK = os.path.join(SCRIPTS, "lfk.py")
sys.path.insert(0, HERE)
sys.path.insert(0, SCRIPTS)

import make_corpus  # noqa: E402
import mockenv  # noqa: E402
from lfkit import tools  # noqa: E402

IS_WIN = os.name == "nt"


def lfk(*args, env=None, check_json=True):
    p = subprocess.run([sys.executable, LFK, *[str(a) for a in args]], capture_output=True, env=env)
    out = p.stdout.decode("utf-8")
    if not check_json:
        return p.returncode, out
    try:
        return p.returncode, json.loads(out)
    except ValueError:
        raise AssertionError(f"not JSON (exit {p.returncode}): {out[:500]} {p.stderr.decode('utf-8', 'replace')[:500]}")


class Corpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lfk test ")
        cls.corpus = os.path.join(cls.tmp, "자료 모음")
        cls.files, cls.images = make_corpus.build(cls.corpus)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def fresh_copy(self, name):
        dst = os.path.join(self.tmp, name)
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(self.corpus, dst)
        return dst

    def p(self, *parts):
        return os.path.join(self.corpus, *parts)


class NoToolsTests(Corpus):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = mockenv.make(os.path.join(cls.tmp, "mock"))
        cls.env["LFK_DATA"] = os.path.join(cls.tmp, "lfk data")

    def run_lfk(self, *args):
        return lfk(*args, env=self.env)

    def test_doctor_reports_missing_tools_with_install_advice(self):
        rc, d = self.run_lfk("doctor")
        self.assertEqual(rc, 0)
        for key, info in d["tools"].items():
            if key == "robocopy" and IS_WIN:
                self.assertTrue(info["found"])
                continue
            self.assertFalse(info["found"], key)
            self.assertIn("homepage", info)
        self.assertEqual(d["features"]["find"]["via"], "fallback")
        self.assertFalse(d["features"]["search"]["available"])
        self.assertIn("김 철수", d["config_file"])

    def test_find_without_everything_needs_root(self):
        rc, d = self.run_lfk("find", "김치")
        self.assertEqual(rc, 2)
        self.assertEqual(d["error"], "need_root")

    def test_find_walk(self):
        rc, d = self.run_lfk("find", "김치", "--root", self.corpus)
        self.assertEqual((rc, d["engine"], d["count"]), (0, "walk", 1))
        self.assertTrue(d["results"][0]["path"].endswith("김치찌개.txt"))
        rc, d = self.run_lfk("find", "", "--root", self.corpus, "--min-size", "5MB")
        self.assertEqual([r["name"] for r in d["results"]], ["big_backup.bin"])
        rc, d = self.run_lfk("find", "", "--root", self.corpus, "--type", "folder", "--limit", "500")
        self.assertIn("빈 폴더", [r["name"] for r in d["results"]])
        rc, d = self.run_lfk("find", "*.md", "--root", self.corpus)
        self.assertEqual(sorted(r["name"] for r in d["results"]), ["meeting notes 2024-03.md", "된장국.md"])
        rc, d = self.run_lfk("find", r"^copy\s?\d", "--regex", "--root", self.corpus)
        self.assertEqual(d["count"], 3)

    def test_size_walk(self):
        rc, d = self.run_lfk("size", self.corpus, "--top", "3")
        self.assertEqual((rc, d["engine"]), (0, "walk"))
        total = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(self.corpus) for f in fs)
        self.assertEqual(d["total_bytes"], total)
        self.assertEqual(d["files"], self.files)
        self.assertTrue(d["largest_files"][0]["path"].endswith("big_backup.bin"))

    def test_dupes_python(self):
        rc, d = self.run_lfk("dupes", self.corpus)
        self.assertEqual((rc, d["engine"], d["groups"]), (0, "python", 1))
        names = sorted(os.path.basename(f["path"]) for f in d["duplicates"][0]["files"])
        self.assertEqual(names, ["copy 2.txt", "copy1.txt", "copy3.txt"])

    def test_empty_python(self):
        rc, d = self.run_lfk("empty", self.corpus, "--files")
        self.assertEqual([os.path.basename(p) for p in d["empty_folders"]], ["빈 폴더"])
        self.assertEqual([os.path.basename(p) for p in d["empty_files"]], ["empty.txt"])

    def test_missing_tools_exit_3(self):
        for args in (["search", "찌개"], ["similar", self.corpus], ["exif", self.corpus], ["status"]):
            rc, d = self.run_lfk(*args)
            self.assertEqual((rc, d["error"]), (3, "tool_missing"), args)
            self.assertIn("install", d)

    def test_archive_zip_roundtrip_without_7zip(self):
        arc = os.path.join(self.tmp, "묶음 test.zip")
        rc, d = self.run_lfk("archive", "create", arc, self.p("레시피 모음"))
        self.assertEqual((rc, d["engine"]), (0, "zipfile"))
        rc, d = self.run_lfk("archive", "create", arc, self.p("레시피 모음"))
        self.assertEqual(d["error"], "exists")
        rc, d = self.run_lfk("archive", "list", arc)
        self.assertIn("레시피 모음/김치찌개.txt", [e["path"] for e in d["files"]])
        rc, d = self.run_lfk("archive", "test", arc)
        self.assertTrue(d["intact"])
        out = os.path.join(self.tmp, "풀기")
        rc, d = self.run_lfk("archive", "extract", arc, "--to", out)
        self.assertEqual(d["extracted"], 3)
        with open(os.path.join(out, "레시피 모음", "김치찌개.txt"), encoding="utf-8") as f:
            self.assertIn("김치", f.read())
        rc, d = self.run_lfk("archive", "extract", arc, "--to", out)
        self.assertEqual(d["skipped_existing"], 3)
        rc, d = self.run_lfk("archive", "create", os.path.join(self.tmp, "x.7z"), self.p("레시피 모음"))
        self.assertEqual(rc, 3)

    def test_copy_preview_execute_no_overwrite(self):
        dst = os.path.join(self.tmp, "복사 대상")
        rc, d = self.run_lfk("copy", self.p("레시피 모음"), dst)
        self.assertEqual((rc, d["mode"], d["files"]), (0, "preview", 3))
        self.assertFalse(os.path.exists(dst))
        rc, d = self.run_lfk("copy", self.p("레시피 모음"), dst, "--execute")
        self.assertEqual(sorted(os.listdir(dst)), ["pancakes.txt", "김치찌개.txt", "된장국.md"])
        with open(os.path.join(dst, "pancakes.txt"), "w") as f:
            f.write("mine")
        rc, d = self.run_lfk("copy", self.p("레시피 모음"), dst, "--execute")
        self.assertEqual(d["files"], 0)
        with open(os.path.join(dst, "pancakes.txt")) as f:
            self.assertEqual(f.read(), "mine")

    def test_plan_move_undo(self):
        work = self.fresh_copy("정리 시험")
        sorted_dir = os.path.join(work, "정리됨")
        plan = os.path.join(self.tmp, "plan.csv")
        rc, d = self.run_lfk("plan", os.path.join(work, "Work Docs"), "--to", sorted_dir, "--by", "kind", "--save", plan)
        self.assertEqual(rc, 0)
        self.assertEqual(d["folders"]["documents"], 5)
        rc, d = self.run_lfk("move", "--plan", plan)
        self.assertEqual((d["mode"], d["ready"]), ("preview", d["total"]))
        self.assertFalse(os.path.exists(sorted_dir))
        rc, d = self.run_lfk("move", "--plan", plan, "--execute")
        self.assertEqual((rc, d["failed"]), (0, 0))
        self.assertTrue(os.path.isfile(os.path.join(sorted_dir, "documents", "project plan.docx")))
        with open(d["undo_log"], encoding="utf-8-sig") as f:
            self.assertEqual(len(list(csv.DictReader(f))), d["moved"])
        rc, d = self.run_lfk("undo", d["undo_log"], "--execute")
        self.assertEqual((rc, d["failed"]), (0, 0))
        self.assertTrue(os.path.isfile(os.path.join(work, "Work Docs", "project plan.docx")))

    def test_move_conflict_skip_and_rename(self):
        work = self.fresh_copy("충돌 시험")
        src = os.path.join(work, "Hobby Notes", "chess openings.txt")
        target = os.path.join(work, "레시피 모음")
        shutil.copy(src, os.path.join(target, "chess openings.txt"))
        rc, d = self.run_lfk("move", src, "--to", target, "--execute")
        self.assertIn("conflict", d["operations"][0]["status"])
        self.assertTrue(os.path.exists(src))
        rc, d = self.run_lfk("move", src, "--to", target, "--on-conflict", "rename", "--execute")
        self.assertEqual(d["moved"], 1)
        self.assertTrue(os.path.exists(os.path.join(target, "chess openings (1).txt")))

    def test_protected_paths_refused(self):
        home = self.env.get("USERPROFILE") or self.env["HOME"]
        targets = [home, os.path.splitdrive(self.tmp)[0] + os.sep if IS_WIN else "/"]
        if IS_WIN:
            targets.append(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "notepad.exe"))
        rc, d = lfk("trash", *targets, env=dict(self.env, USERPROFILE=home))
        self.assertEqual(d["ready"], 0)
        self.assertTrue(all(i["status"].startswith("protected") for i in d["items"]), d["items"])

    def test_archive_guards(self):
        rc, d = self.run_lfk("archive", "create", os.path.join(self.tmp, "no extension"), self.p("레시피 모음"))
        self.assertEqual((rc, d["error"]), (2, "bad_argument"))
        rc, d = self.run_lfk("archive", "create", self.p("레시피 모음", "self.zip"), self.p("레시피 모음"))
        self.assertEqual((rc, d["error"]), (2, "bad_argument"))
        self.assertFalse(os.path.exists(self.p("레시피 모음", "self.zip")))
        # an entry whose name climbs out ("sub/./../x.txt") must not overwrite an existing file
        import zipfile
        arc = os.path.join(self.tmp, "tricky.zip")
        out = os.path.join(self.tmp, "tricky out")
        os.makedirs(os.path.join(out, "sub"), exist_ok=True)
        with open(os.path.join(out, "sub", "x.txt"), "w") as f:
            f.write("ORIGINAL")
        with zipfile.ZipFile(arc, "w") as z:
            z.writestr("sub/./../x.txt", "FROM ZIP")
            z.writestr("../../escape.txt", "FROM ZIP")
        rc, d = self.run_lfk("archive", "extract", arc, "--to", out)
        with open(os.path.join(out, "sub", "x.txt")) as f:
            self.assertEqual(f.read(), "ORIGINAL")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "escape.txt")))

    def test_move_names_differing_only_in_case_conflict(self):
        work = self.fresh_copy("대소문자 시험")
        a, b = os.path.join(work, "a"), os.path.join(work, "b")
        os.makedirs(a)
        os.makedirs(b)
        with open(os.path.join(a, "IMG.JPG"), "w") as f:
            f.write("1")
        with open(os.path.join(b, "img.jpg"), "w") as f:
            f.write("2")
        rc, d = self.run_lfk("move", os.path.join(a, "IMG.JPG"), os.path.join(b, "img.jpg"), "--to",
                             os.path.join(work, "together"))
        self.assertEqual((d["ready"], d["blocked"]), (1, 1))

    def test_setup_lists_first_and_never_installs_without_yes(self):
        rc, d = self.run_lfk("setup")
        self.assertEqual((rc, d["mode"]), (0, "preview"))
        tools_listed = {m["tool"]: m for m in d["missing"]}
        self.assertIn("exiftool", tools_listed)
        self.assertIn("Not part of --all", tools_listed.get("wiztree", {}).get("note", "Not part of --all"))
        rc, d = self.run_lfk("setup", "--all")  # no --yes: still only a preview
        self.assertEqual(d["mode"], "preview")
        rc, d = self.run_lfk("setup", "--tools", "nosuch", "--yes")
        self.assertEqual((rc, d["error"]), (2, "bad_argument"))
        rc, d = self.run_lfk("setup", "--all", "--yes")  # the pretend profile has no winget/choco on PATH
        self.assertEqual(d["error"], "no_installer" if IS_WIN else "not_supported")

    def test_text_search_without_digup_uses_words(self):
        rc, d = self.run_lfk("search", "김치찌개", "--root", self.corpus)
        self.assertEqual((rc, d["engine"], d["ranking"]), (0, "text", "shared words"))
        self.assertTrue(d["results"][0]["path"].endswith("김치찌개.txt"))
        self.assertIn("note", d)  # says DigUp is missing, so no meaning ranking
        rc, d = self.run_lfk("search", "hotel receipts submitted", "--root", self.corpus)
        self.assertTrue(d["results"][0]["path"].endswith("travel policy.pdf"), d["results"][:2])
        self.assertGreaterEqual(d["files_without_text"], 1)  # the scan-only PDF (and the empty file)
        rc, d = self.run_lfk("search", "김치", "--engine", "text")
        self.assertEqual((rc, d["error"]), (2, "need_root"))

    def test_options_before_command(self):
        out = os.path.join(self.tmp, "앞 옵션.json")
        rc, d = self.run_lfk("--out", out, "find", "김치", "--root", self.corpus)
        self.assertTrue(os.path.isfile(out))

    @unittest.skipUnless(IS_WIN, "Windows path forms")
    def test_protected_path_spellings(self):
        sysroot = os.environ.get("SystemRoot", r"C:\Windows")
        rc, d = lfk("trash", "\\\\?\\" + os.path.join(sysroot, "notepad.exe"), env=self.env)
        self.assertTrue(d["items"][0]["status"].startswith("protected"), d)

    def test_bad_arguments(self):
        rc, d = self.run_lfk("dupes", self.corpus, "--min-size", "lots")
        self.assertEqual(rc, 2)
        rc, d = self.run_lfk("find", "x", "--root", os.path.join(self.tmp, "없는 폴더"))
        self.assertEqual((rc, d["error"]), (2, "not_found"))

    def test_ascii_and_out_options(self):
        rc, text = lfk("find", "김치", "--root", self.corpus, "--ascii", env=self.env, check_json=False)
        text.encode("ascii")
        self.assertIn("\\uae40\\uce58", text)
        out = os.path.join(self.tmp, "결과.json")
        rc, d = self.run_lfk("find", "김치", "--root", self.corpus, "--out", out)
        with open(out, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["count"], 1)


class PdfTextTests(Corpus):
    def test_simple_pdf(self):
        from lfkit import textread
        text = textread.read_text(self.p("Work Docs", "travel policy.pdf"))
        self.assertIn("Economy class for flights under six hours.", text)

    def test_scan_pdf_has_no_text(self):
        from lfkit import textread
        self.assertEqual(textread.read_text(self.p("스캔", "영수증 스캔.pdf")), "")

    def test_browser_made_korean_pdf(self):
        import pdfmaker
        from lfkit import textread
        out = os.path.join(self.tmp, "한글 안내문.pdf")
        paras = ["보증금 반환이 늦어질 때는 법원에 임차권등기명령을 신청한다.",
                 "두 번째 문단은 English words와 숫자 123을 함께 담는다."]
        if not pdfmaker.make_pdf(paras, out):
            self.skipTest("no Edge/Chrome to print a test PDF")
        text = textread.read_text(out)
        if not any("가" <= c <= "힣" for c in text) and not pdfmaker.has_korean_font(out):
            self.skipTest("the browser had no Korean font, so the PDF holds empty boxes instead of Korean")
        self.assertIn("임차권등기명령을 신청한다", text)
        self.assertIn("English words", text)
        self.assertEqual(len(text.split("\n\n")), 2)  # two paragraphs, as in the page


@unittest.skipUnless(IS_WIN or (sys.platform.startswith("linux") and shutil.which("gio")),
                     "undo restores from the Windows Recycle Bin or the Linux home Trash only")
class TrashTests(Corpus):
    def test_trash_then_undo_restores(self):
        work = self.fresh_copy("휴지통 시험")
        target = os.path.join(work, "중복 테스트", "b c", "copy 2.txt")
        env = dict(os.environ, LFK_DATA=os.path.join(self.tmp, "lfk data"))
        rc, d = lfk("trash", target, env=env)
        self.assertTrue(os.path.exists(target))
        rc, d = lfk("trash", target, "--execute", env=env)
        self.assertEqual((rc, d["trashed"]), (0, 1))
        self.assertFalse(os.path.exists(target))
        rc, d = lfk("undo", d["undo_log"], "--execute", env=env)
        self.assertEqual(d["operations"][0]["status"], "restored", d)
        self.assertTrue(os.path.exists(target))


class WithToolsTests(Corpus):
    def need(self, key):
        if not tools.locate(key)["found"]:
            self.skipTest(f"{key} not installed")

    def test_czkawka_matches_python(self):
        self.need("czkawka")
        rc, a = lfk("dupes", self.corpus)
        rc, b = lfk("dupes", self.corpus, "--engine", "python")
        norm = lambda d: sorted(sorted(os.path.normcase(f["path"]) for f in g["files"]) for g in d["duplicates"])
        self.assertEqual(a["engine"], "czkawka")
        self.assertEqual(norm(a), norm(b))
        rc, a = lfk("empty", self.corpus, "--files")
        rc, b = lfk("empty", self.corpus, "--files", "--engine", "python")
        self.assertEqual(a["empty_folders"], b["empty_folders"])
        self.assertEqual(a["empty_files"], b["empty_files"])

    def test_czkawka_similar_images(self):
        self.need("czkawka")
        if not self.images:
            self.skipTest("Pillow not installed, no sample images")
        rc, d = lfk("similar", self.corpus, "--min-size", "1", "--hash-alg", "Mean", "--hash-size", "8",
                    "--max-difference", "10")
        self.assertEqual(d["groups"], 1)
        self.assertEqual(sorted(os.path.basename(m["path"]) for m in d["similar"][0]), ["바다 풍경 (보정).jpg", "바다 풍경.jpg"])

    def test_exiftool_reads_korean_names(self):
        self.need("exiftool")
        if not self.images:
            self.skipTest("Pillow not installed, no sample images")
        rc, d = lfk("exif", self.p("여행 사진 2024"))
        models = {os.path.basename(r["path"]): r.get("Model") for r in d["results"]}
        self.assertEqual(models["바다 풍경.jpg"], "Sample Camera A")
        self.assertEqual(models["forest walk.jpg"], "Sample Phone B")

    def test_7zip_roundtrip(self):
        self.need("7zip")
        arc = os.path.join(self.tmp, "묶음 7z.7z")
        rc, d = lfk("archive", "create", arc, self.p("레시피 모음"))
        self.assertEqual((rc, d["engine"]), (0, "7zip"))
        rc, d = lfk("archive", "list", arc)
        self.assertIn(os.path.join("레시피 모음", "김치찌개.txt") if IS_WIN else "레시피 모음/김치찌개.txt",
                      [e["path"] for e in d["files"]])
        rc, d = lfk("archive", "test", arc)
        self.assertTrue(d["intact"])

    def test_wiztree_matches_walk(self):
        self.need("wiztree")
        rc, a = lfk("size", self.corpus)
        rc, b = lfk("size", self.corpus, "--engine", "walk")
        self.assertEqual(a["engine"], "wiztree")
        self.assertEqual((a["total_bytes"], a["files"]), (b["total_bytes"], b["files"]))

    def test_everything_find(self):
        self.need("everything")
        rc, d = lfk("doctor")
        if not d["tools"]["everything"].get("ready"):
            self.skipTest("Everything not running")
        for _ in range(20):  # Everything picks up new files within a moment
            rc, d = lfk("find", "김치", "--root", self.corpus)
            if d.get("count"):
                break
            time.sleep(0.5)
        self.assertEqual(d["count"], 1)
        self.assertTrue(d["engine"].startswith("everything") or d["engine"] == "walk")


@unittest.skipUnless(os.environ.get("LFK_TEST_DIGUP") == "1", "set LFK_TEST_DIGUP=1 to run DigUp tests")
class DigUpTests(Corpus):
    def test_index_search_passages(self):
        idx = os.path.join(self.tmp, "digup index")
        rc, d = lfk("index", self.corpus, "--index", idx)
        self.assertEqual(rc, 0, d)
        rc, d = lfk("status", "--index", idx)
        self.assertGreaterEqual(d["vectors"], 10)
        rc, d = lfk("search", "찌개 끓이는 법", "--index", idx, "--zgate", "0", "-n", "3", "--passages", "1")
        self.assertTrue(d["results"][0]["path"].endswith("김치찌개.txt"), d)
        self.assertIn("passages", d["results"][0])
        rc, d = lfk("search", "찌개 끓이는 법", "--index", idx, "--zgate", "0", "--no-excerpt", "--passages", "1")
        self.assertNotIn("excerpt", d["results"][0])
        self.assertNotIn("text", d["results"][0]["passages"][0])

    def test_text_first_search_with_model(self):
        env = dict(os.environ, LFK_DATA=os.path.join(self.tmp, "text cache"))
        rc, d = lfk("search", "찌개 끓이는 법", "--root", self.corpus, "-n", "3", "--passages", "1", env=env)
        self.assertEqual((rc, d["ranking"]), (0, "meaning (EmbeddingGemma 2)"), d)
        self.assertTrue(d["results"][0]["path"].endswith("김치찌개.txt"))
        self.assertGreater(d["files_read_now"], 0)
        rc, d = lfk("search", "항공권 좌석 등급 규정", "--root", self.corpus, "-n", "1", env=env)
        self.assertTrue(d["results"][0]["path"].endswith("travel policy.pdf"), d["results"])  # Korean -> English PDF
        self.assertEqual(d["files_read_now"], 0)  # everything came from the cache
        rc, d = lfk("search", "x", "--root", self.corpus, "--estimate", env=env)
        self.assertEqual(d["estimate"]["files_to_read"], 0)

    def test_index_media_only_leaves_documents_out(self):
        idx = os.path.join(self.tmp, "digup index media")
        rc, d = lfk("index", self.corpus, "--index", idx, "--estimate", "--media-only")
        self.assertEqual(rc, 0, d)
        self.assertNotIn("doc", d["estimate"]["files"])


if __name__ == "__main__":
    unittest.main()
