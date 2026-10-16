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
