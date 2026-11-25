# lfk.py commands

Every command prints one JSON object. Common options (any command): `--pretty`, `--ascii`, `--out FILE`.
Errors look like `{"ok": false, "error": "<code>", "message": "...", ...}`.

| error code | meaning | exit |
|---|---|---|
| `bad_argument`, `not_found`, `need_root`, `exists` | fix the command | 2 |
| `tool_missing` | install advice in `install`, `homepage`, `license`, `set_path_with` | 3 |
| `everything_not_running` | start Everything, or pass `--engine walk --root DIR` | 3 |
| `digup_app_running` | add the folder in the DigUp app, or `--index DIR`, or `--force` | 2 |
| `tool_failed`, `timeout`, `internal_error` | details in `stderr` / `trace` | 1 |

## doctor
`tools.<key>`: `found, path, source (env|config|PATH|default location|registry), version, ready, problem`.
`features.<name>`: `available, via (tool key | fallback | python), fallback, install, reason`.
`system`: `os, cpu, memory.total_gb/free_gb, gpus[].name/vram_gb/vram_used_gb, disks[]`. `advice[]`: plain sentences.
Tool keys: `everything, digup, wiztree, czkawka, exiftool, 7zip, robocopy`.

## setup
Without `--yes` it only lists: `installer` (winget, choco or null), `missing[{tool, label, purpose, license, homepage,
how (winget|choco|manual), commands[], note}]`, `mode: preview`. With `--yes` and `--all` (every missing tool except
WizTree) or `--tools a,b` it runs the commands, starts Everything if it was just installed, looks again and returns
`results[{tool, status (installed|already installed|manual|failed...), exit_codes, found, path}]`.
Windows only (winget, else Chocolatey, which needs an administrator console; `LFK_INSTALLER=winget|choco` picks one).
DigUp is always `manual`.
On macOS/Linux it lists the brew/apt commands; `--yes` is refused (`not_supported`). No installer: `no_installer`.

## q QUERY
Start here. File names and contents at once, merged. Options: `--kind screenshot,image,pdf,doc,audio,video,code`,
`--ext a,b`, `--after/--before YYYY-MM-DD`, `--under DIR` (repeatable), `-n/--limit 10`, `--no-excerpt`,
`--also WORDS` (repeatable translations or alternative spellings supplied by the caller).
- Names: Everything, scored by how many of the question's words the name holds (fillers such as 파일·자료·찾아 and
  verb forms such as 설명한 are left out; a trailing particle 을·를·에서… is cut), so extra words in the question
  do not hide a name. Words that name a kind (pdf, 한글, 엑셀, 사진, 스캔, 영상…) favour that extension. Drives
  Everything does not index (a cloud drive) come from a name list `serve` walks every 30 minutes.
- Parent-folder words count less than filename words. Joined and spaced spellings are compared together.
- Contents: the DigUp document and existing code indexes through `serve`, filtered by the same `--ext`/dates/`--under`.
- Dates in the question: 오늘, 어제, 이번 주, 지난주 filter; 이번 달, 올해, 작년 only rank those files higher.
- Copies (same name without " (1)" / " - 복사본", same size) are one line; the path shown is the one outside
  backup, worktree and temp folders.
Output: `results[{path, why: name|content|both, modified, size, kind, z, where, excerpt, name_words, copies,
other_places[], path_words}]`, `searched{names, content}`, `name_words[]`, `dates`, `dates_preferred`, `notes[]`, `seconds`.
`weak` means the leading evidence is weak, not that the file is absent. A weak first pass triggers exactly one
larger pass (`expanded: true`); `timing{fast_seconds, expansion_seconds}` measures them separately.
Confidence uses filename coverage and semantic evidence, not the rank-fusion score alone. It is a heuristic,
not a correctness probability. `timing.stages.fast` and `.expansion` break down `names`, `other_names`, `semantic`,
`code`, `merge`, and `excerpts` in seconds; `engine_ms` separates embedding and search inside DigUp.
The retrieval stages overlap, so their durations must not be added to obtain elapsed time.
Expansion reuses a nonempty name pool if its first query hit no quota or error (`names_reused: true`). A content
search that already took longer than the remaining budget keeps its first-pass hits (`semantic_reused` or
`code_reused`) with a note instead of repeating that search. Filename plus leading semantic evidence can avoid
expansion; folder-only evidence needs stronger semantic support.
Expansion waits at most 2.5 seconds, including merge and excerpt work. Retrieval gets up to 1.5 seconds,
reserving one second for merging, excerpts and cleanup; it returns
completed candidates with a timeout note; if merging itself cannot finish, it retains the first-pass results.
This is not a whole-query cap: the first pass, startup and output serialization are outside it. Timed-out ES
processes are killed. Expired queued helper requests are discarded; a helper search already executing may
finish in the background. Each caller process permits only one unfinished expansion worker.
`where`: `p. N` (PDF page), `part N` (a document's chunk), `m:ss` (audio/video), `line N–M` (code).

## serve
Keeps `digup search-service` running for the DigUp app's index (or `--index DIR`) with the query encoder on the CPU,
answering on a named pipe (Windows) or a Unix socket in the data folder, with a key in `serve.json` there. Nothing
listens on the network. `--idle 604800`: seconds without a search before the vectors are let go (the next search loads
them again). `--release-at 80` (Windows, 0 = off): when the whole computer's memory use reaches this percent, the
helpers are stopped too (checked every 15 s; the next search starts them again; each release is logged in
`memory-release.log`). `--reload-at 70` (0 = off): after such a release, the main helper loads its vectors again once
memory use has stayed under this percent for a minute and ten minutes have passed, but only while the memory it held
before still leaves use 5 points under `--release-at`; the code helper waits for the next code search. `--status` (`running, pid, vectors_loaded, encoder, searches, names{drives, entries, walked}`),
`--stop`, `--autostart on|off` (Windows: task `LocalFileKit-Search` at logon, no window).
`q` and `search` start it themselves when it is not running (not with `--index`; `LFK_NO_AUTOSERVE=1` turns that
off). `search` output says `via: service|cli`.
For the default index, the service reuses `codeFolders` and `codeSkipped` from the app's settings when a code
database already exists. It does not rebuild the index or edit settings. Custom indexes are isolated from those
app folders. Status also includes `code_enabled` and `code_vectors_loaded`. Automatic code-folder discovery
requires the app's JSON settings; platforms using a different settings format may have no code connection.
Normal and code searches use separate helpers in parallel. The code helper leaves its main-index vectors unloaded;
it has its own idle encoder, reported as `code_encoder`. This trades some additional RAM for lower query latency.
Drive-name normalization is cached until the next name-list refresh.

## refresh
Indexes what changed in the folders chosen in the DigUp app (its `settings.json`), without the app: the app's own
helper (`digup index-service --backfill`, same folders, skips and code folders), below-normal priority, then
`serve` reloads. Skipped while the DigUp app runs (it does this itself); stops if the app starts. `--max-hours 6`,
`--last` (what the last run did), `--autostart on|off [--at 03:30]` (Windows: daily task `LocalFileKit-IndexRefresh`).
Output: `minutes, syncs[{code, added, changed, moved, removed, unchanged, ms}], files, states, rest, errors, missing,
service_reloaded`.
The installed DigUp helper determines which extensions can be indexed. Markdown documents in code folders
use the normal content index when those folders are selected there. MDX needs a helper that recognizes `.mdx`
as a document; scheduling alone cannot add an unsupported type. A helper update does not require rebuilding
unchanged files when its model and indexing settings remain compatible.

## find QUERY
Options: `--root DIR` (repeatable), `--ext a,b`, `--type file|folder`, `--min-size`, `--max-size` (500, 10k, 5MB, 1.5GB),
`--after/--before YYYY-MM-DD` (modified), `--regex`, `--case`, `--sort name|path|size|modified`, `--limit 100`,
`--engine auto|everything|walk`, `--max-seconds 120` (walk only).
Query: words that must all be in the name; `*`/`?` wildcards; a word containing `\` or `/` is matched against the full path.
With Everything, its own syntax also works (e.g. `dm:today`, `"exact phrase"`).
Without `--root` the whole Everything index is searched; without Everything, `--root` is required.
Output: `engine, count, results[{path,name,is_dir,size,modified}]`, `truncated`, `notes[]`, `walked_entries`.

## search QUERY
Two engines. `--engine auto` (default) uses **text** when `--root` is given and the **DigUp index** otherwise.

Text first (`--root DIR`, repeatable): walks the folder, reads the text of txt, md, docx, hwpx, pptx, xlsx, odt, html,
rtf and program-made PDFs, splits it into paragraphs and ranks them by meaning with EmbeddingGemma 2 (`digup worker`;
no index), or by shared words when DigUp is missing (`--words` forces that). Paragraph vectors are cached per file in
`text-vectors.sqlite` in the data folder (numbers only, not the text), so a second search only reads changed files.
Options: `-n/--limit 10`, `--passages K`, `--no-excerpt`, `--estimate` (counts and expected seconds, searches nothing),
`--max-seconds 300` (time for reading new files; what was read is kept), `--max-files 20000`, `--no-cache`, `--cpu`.
Output: `ranking, files_with_text, files_read_now, files_from_cache, files_without_text, pictures_audio_video,
not_readable_as_text, cloud_only_skipped, incomplete, results[{path, kind: text, score, loc, size, modified, excerpt,
passages[{rank, score, index, text}]}]` plus `hint_*` sentences.

DigUp index (no `--root`, or `--engine digup`): `--kind screenshot,image,pdf,doc,audio,video`, `--root DIR` (filter),
`--zgate Z` (0 = show all ranked), `--index DIR` (separate index), `--passages K`, `--no-excerpt`, `--cpu`.
Output: `results[{path, kind, z, cosine, segment, loc, size, modified, excerpt, passages[...], passages_total,
passages_skipped}]`, `hint` when empty. `loc` is the page (PDF) or chunk (document) where the best match is.

## index FOLDER...
`--estimate` (no indexing; returns files per kind, `seconds`, `minutes`, `calibrated`), `--media-only` (leave out
txt, md, rtf, docx, odt, html: search those as text), `--no-pdf` (with `--media-only`), `--index DIR`,
`--exclude DIR`, `--limit N`, `--cpu`, `--force`, `--timeout`.
Output: `sync` (new/changed/removed counts), `done`, `skipped_files`, `failed[]`.

## status
`index, vectors, kinds.<kind>.files/state, size, model, app_running`.

## size PATH
`--top 20`, `--engine auto|wiztree|walk`, `--max-seconds 600`.
Output: `total_bytes, files, folders, children[{path,is_dir,size,files}], largest_files[{path,size,modified}]`.

## dupes DIR...
`--min-size 1` (bytes or 100k...), `--limit 100` (groups), `--engine auto|czkawka|python`.
Output: `groups, wasted_bytes, duplicates[{size, files[{path,modified}]}]` sorted by wasted space.

## similar DIR...
`--max-difference 5` (0-40), `--hash-size 16` (8/16/32/64), `--hash-alg Gradient|Mean|Median|Blockhash|VertGradient|DoubleGradient`,
`--min-size 16384`. Output: `similar[[{path,size,width,height,modified,difference}]]`.

## empty DIR...
`--files` adds empty files. Output: `empty_folders[]` (outermost only), `empty_files[]`.

## exif PATH...
`-r`, `--tags A,B`, `--all`, `--ext`, `--limit 200`. Default tags: date taken (`DateTimeOriginal`, `CreateDate`),
`Make, Model, LensModel, ImageWidth/Height, GPSLatitude/Longitude/Altitude, Duration, ...` (numbers, not text: `-n`).

## archive create|list|test|extract ARCHIVE [SOURCES...]
`--to DIR` for extract. Never overwrites: create refuses an existing archive, extract skips existing files.
Without 7-Zip only `.zip` works.

## copy SRC DST
`--execute`, `--overwrite-changed`, `--limit`. Preview lists what would be copied. Never deletes; by default never
replaces existing files. Windows uses robocopy (`/E /R:1 /W:1 /XJ`, plus `/XC /XN /XO` unless overwriting).

## plan SRC --to DEST
`--by kind|ext|year|month`, `--exif` (date taken), `-r`, `--save CSV`. Writes a `source,destination` CSV; moves nothing.
Kinds: images, videos, audio, documents, archives, code, others.

## move [PATH...] --to DIR | --plan CSV
`--on-conflict skip|rename`, `--execute`, `--log CSV`. Each operation has `status`: `ok`, `conflict...`, `missing`,
`protected: ...`, then `moved`/`failed: ...`. Output after execute: `moved, failed, undo_log`.

## trash PATH...
`--execute`, `--log CSV`. Windows: Recycle Bin (refuses drives without one); macOS: Finder Trash; Linux: `gio trash`
or the `send2trash` package. If Windows would delete something for good (too big for the bin) it asks on screen.

## undo LOG.csv
Moves files back in reverse order; for trashed items it restores them from the Recycle Bin (Windows) or the home
Trash (Linux). On macOS restore trashed items in Finder. `--execute` to act.

## Where things are kept
- Undo logs and plans: `%LOCALAPPDATA%\local-file-kit\` (Windows) or `~/.local/state/local-file-kit/`; override `LFK_DATA`.
- Config: `%APPDATA%\local-file-kit\config.json` or `~/.config/local-file-kit/config.json`; override `LFK_CONFIG`.
  `{"tools": {"7zip": "D:/Apps/7-Zip/7z.exe"}}`. Environment variables win: `LFK_ES, LFK_DIGUP, LFK_WIZTREE,
  LFK_CZKAWKA, LFK_EXIFTOOL, LFK_7Z, LFK_ROBOCOPY`.
