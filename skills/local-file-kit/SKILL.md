---
name: local-file-kit
description: Use whenever the user wants to find or organize files on this computer - start every search with `lfk.py q` (names and contents at once, about a second) instead of Glob/grep/dir. A file by name, a document or photo by what it is about (meaning search in Korean and English, DigUp + EmbeddingGemma 2, also inside PDFs, Word files and images), what fills a disk, duplicate files, look-alike photos, empty folders, photo dates/camera/GPS, zip/unzip, copying folders, or tidying folders with previewed, undoable moves and Recycle Bin deletes. Prefer it over ad-hoc shell commands for these jobs - it uses Everything, WizTree, Czkawka, ExifTool, 7-Zip and robocopy when installed, safe Python fallbacks otherwise, and keeps undo logs. 파일 찾기, 내용·뜻으로 문서 찾기, 용량 확인, 중복 파일, 비슷한 사진, 사진 정리, 다운로드 폴더 정리.
---

# local-file-kit

**Whatever the user wants to find on this computer, run `q` first** - before Glob, grep, dir or a Python walk:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/lfk.py" q "what they asked for, in their words" [-n 10]
```

It searches file names (Everything) and what files say (the DigUp index, pictures and scans too) at once, folds
copies of one file into one line, and gives each content match its passage and page - answer from that without
opening the file. Narrow with `--ext pdf,hwp`, `--kind image`, `--after/--before YYYY-MM-DD`, `--under DIR`;
"오늘", "어제", "이번 주", "작년" in the question set the dates. Then, only if needed:

**이름이 영어일 만한 것은 `--also`로 파일 이름에 실제로 쓰였을 영어 낱말을 같이 넘긴다.**
대화 맥락에서 학명·영어 제목·실제 표기를 고른다(예: 쯔쯔가무시 → `scrub typhus`).
Supply those words, rather than a translation of the whole question:
`q "쯔쯔가무시 설명한 글" --also "scrub typhus"`.
Repeat `--also` for several alternatives; no personal dictionary is stored. Parent-folder terms count less than
filename terms, and spacing differences are normalized. Existing code-index matches are included as `kind: code`.
If the first pass has weak evidence, `q` automatically expands candidates once. `weak: true` and
`못 찾았을 수 있음` mean the answer remains uncertain, not that the file is absent. Check `timing.fast_seconds`
and `timing.expansion_seconds`; only weak queries pay for the extra pass.
Expansion waits at most 2.5 seconds. A timeout note means candidates may be incomplete; use the returned
results with that caveat. The first pass and model startup are outside this expansion budget.

1. `q` found nothing and the name is known: `find "words" --root DIR` (folders Everything does not index).
2. a document by what it says in one folder the index does not cover: `search "what it says" --root DIR`.
3. Code inside a repository: Glob and Grep as usual.

`q` and `search` ask the resident search service (`serve`): about a second per question. If it is not running they
start it (the first question then waits while it starts). After `--idle` seconds without a search (default 604800,
7 days) it lets the vectors go (about 1.5 KB per indexed piece), and the next question waits while it reads them back
(seconds to minutes). On Windows it also lets them go when the computer's memory use reaches `--release-at` (80%),
and loads them again when use stays under `--reload-at` (70%) with room to spare. Check it with `serve --status`; on
Windows it starts at logon
after `serve --autostart on`.

One command line, `scripts/lfk.py`, in front of the file tools this computer may have. It answers in JSON.
When a tool is missing it either falls back to plain Python (slower) or says exactly what to install.

## Run it

```bash
python "${CLAUDE_SKILL_DIR}/scripts/lfk.py" doctor
```

- Windows: if `python` is missing or opens the Microsoft Store, use `py -3` instead. macOS/Linux: `python3`.
- Needs Python 3.9+. Nothing to pip install.
- Quote every path (spaces and Korean names are normal). Output is UTF-8 JSON; if the console garbles it,
  add `--ascii` or `--out result.json` and read the file.
- Exit codes: 0 ok, 1 failed, 2 bad arguments, 3 a needed tool is missing (the JSON says what to install).

Start a session with `doctor` once: it lists which tools are found, which features work, and the PC's
memory, graphics card and disks. Do not re-run it for every request.

## Pick the command

| The user wants | Command |
|---|---|
| anything, by name or by what it says (start here) | `q "words" [--ext] [--kind] [--after] [--under DIR] [-n 10]` |
| a file whose name they partly know | `find "words" [--root DIR] [--ext pdf,docx] [--after 2024-01-01] [--min-size 10MB]` |
| a document by what it is about, in a folder | `search "what it says" --root DIR [--passages 3]` (text first, no index) |
| a document anywhere on the PC | `search "what it says"` (the DigUp index; only if DigUp has indexed those folders) |
| a photo, screenshot or scan by what is in it | `search "beach at sunset" --kind image,screenshot` (DigUp index) |
| to know what fills the disk | `size "D:\" --top 20` |
| duplicate files | `dupes DIR [DIR...] [--min-size 1MB]` |
| look-alike photos | `similar DIR` (edited copies: `--hash-alg Mean --hash-size 8 --max-difference 10`) |
| empty folders/files | `empty DIR --files` |
| when/where a photo was taken | `exif FILE_OR_DIR [-r]` |
| to zip/unzip | `archive create OUT.7z SRC...` / `archive list|test ARC` / `archive extract ARC --to DIR` |
| to copy a folder | `copy SRC DST` (preview) then `--execute` |
| to sort a folder | `plan SRC --to DEST --by kind|ext|year|month [--exif]` then `move --plan PLAN.csv` |
| to move things | `move PATH... --to DIR` (preview) then `--execute` |
| to delete | `trash PATH...` (preview) then `--execute` → Recycle Bin |
| to reverse a move/trash | `undo UNDO_LOG.csv` (preview) then `--execute` |
| pictures/scans searchable by meaning | `index DIR --media-only --estimate`, then `index DIR --media-only` |
| the index to include files changed since it was built | `refresh` (only what changed; `refresh --autostart on` runs it nightly) |
| index search ready from logon | `serve --autostart on` (Windows); `serve --status`, `serve --stop` |
| to install the missing tools | `setup` (lists them, installs nothing), then after a yes `setup --all --yes` or `setup --tools a,b --yes` |

Full options: `python lfk.py <command> --help`. Details and output fields: [reference/commands.md](reference/commands.md).

## Rules

1. **Preview first, then ask.** `copy`, `move`, `trash` and `undo` change nothing without `--execute`.
   Show the user the preview (counts, a few paths, anything `blocked`) and get a clear yes before `--execute`.
   Never add `--execute` on your own initiative for `trash`.
2. **Keep the undo log path.** Every executed `move`/`trash`/`undo` returns `undo_log`. Tell the user where it is.
3. **Install tools only with the user's yes.** On `tool_missing`, or when `doctor` lists missing tools, run `setup`
   (it only lists), show the user each tool, what it is for and its licence note (WizTree: personal use only), and
   ask which to install. Only then run `setup --tools ... --yes` (or `--all --yes`, which skips WizTree), and run
   `doctor` afterwards. DigUp is never installed by `setup`: give the user its download page. On macOS/Linux,
   `setup` only prints the brew/apt commands for the user to run.
4. **Privacy.** Results contain file names, paths and (for `search`) text excerpts from the user's files, and they
   go to the AI service you run on. Show only what the task needs. Use `--no-excerpt` when the content is not
   needed. Do not paste whole result lists back to the user unasked.
5. **Text first, index second.** For documents in a folder, use `search ... --root DIR`: it reads the text of
   txt, md, docx, hwpx, pptx, xlsx, odt, html, rtf and program-made PDFs directly and needs no index. Use the
   DigUp index for what has no text (photos, screenshots, scanned PDFs, audio, video): `index DIR --media-only`.
6. **Big jobs.** Before a first text search in a large folder run `search "x" --root DIR --estimate`; before
   indexing run `index DIR --media-only --estimate`. Tell the user the time. If the DigUp app is running, let the
   app index (add the folder there) instead of `index`.
7. Protected places (drive roots, the home folder itself, Windows, Program Files, ProgramData, AppData except
   the temp folder, macOS/Linux system folders) are refused by `move`/`trash`; do not try to work around it.

## Reading results

- `q` → `results[]` with `path, why` (`name`, `content` or `both`), `modified`, `size`; content matches add
  `excerpt`, `where` (`p. 3` for a PDF page, `part N` for a document chunk) and `kind`; `copies` and
  `other_places` when the same file (same name and size) is in several places - the path shown is the one outside
  backup/worktree/temp folders. `notes` says what could not be searched (a drive Everything does not index, the
  service not running). The index only knows files indexed so far: for files made today, names answer first.

- `find` → `results[]` with `path, name, is_dir, size, modified`. `engine` says whether Everything or a folder
  walk answered. Everything only knows local NTFS drives; for cloud/network/USB folders the walk is used.
- `search --root` (text first) → `engine: text`, `ranking` (`meaning (EmbeddingGemma 2)` when DigUp's model is
  there, else `shared words`), `results[]` with `path, score, excerpt, loc` (paragraph number); `--passages K` adds
  the K best paragraphs. Also `files_read_now`/`files_from_cache`, `files_without_text` (scans: suggest the
  DigUp index), `pictures_audio_video`, `not_readable_as_text` (HWP, DOC...), and `incomplete` when the time limit
  stopped it (running it again continues where it stopped).
- `search` without `--root` (DigUp index) → `results[]` with `path, kind, z, excerpt, loc` (page or chunk). DigUp
  returns one best spot per file and hides weak matches (z < 2.0): rephrase, or `--zgate 0` to see the ranking.
- `dupes` → `duplicates[]` groups; `wasted_bytes`. Keep one file per group; suggest which by path/date.
- `size` → `children[]` (biggest first) and `largest_files[]`.

## Limits worth telling the user

- Meaning ranking uses EmbeddingGemma 2 from the DigUp app (free, MIT, 865 MB model). Without DigUp, text search
  still works but ranks by shared words. The index search only finds what DigUp has indexed.
- Text is read from txt, md, docx, hwpx, pptx, xlsx, odt, html, rtf and PDFs made by programs. Old binary HWP,
  DOC, XLS, PPT and scanned PDFs have no readable text here. Cloud-only (not downloaded) files are skipped.
- Everything, WizTree and robocopy are Windows-only; on macOS/Linux, `find`, `size` and `copy` use Python.
- WizTree is free for personal use only.

Hardware needs and measured speeds: https://github.com/hyunsungko/local-file-kit/blob/main/docs/SPECS.md
