# Changelog

All notable changes. Versions follow [Semantic Versioning](https://semver.org/); the version lives in
`.claude-plugin/plugin.json` and `skills/local-file-kit/scripts/lfkit/__init__.py` (keep them equal).

## 0.3.0

- `q` searches names and indexed contents together, folds copies, applies shared filters and returns passages
  and locations. Parent paths, Korean particles, spacing variants and repeatable caller-supplied `--also` help retrieval.
- Weak first results trigger one expanded search; JSON reports `weak`, `expanded` and separate stage timings.
  Confidence checks filename coverage and semantic evidence separately from ranking. Detailed timings show
  names, meaning, code, excerpts and merging, with overlapping retrieval stages.
- Combined name/content evidence can avoid expansion. Complete name pools are reused; content searches that
  already exceeded the remaining expansion budget retain their first-pass hits with a note. Expansion has a
  2.5-second budget, retains completed results and reports timeouts in `notes`.
- `serve` keeps the DigUp searcher ready, reuses existing app code-folder selections and releases idle vectors.
  `q` merges code hits and fetches their text from the correct index. Windows logon registration is optional.
  Normal and code searches run in parallel helpers; drive-name normalization is reused between queries.
- `serve --release-at 80` (Windows): when the computer's memory use reaches this percent, the helpers let their
  vectors go; `--reload-at 70` loads the main helper again once use stays lower and the memory it held before still
  fits 5 points under the release level, so it is not let go again right after. Only the main helper is reloaded
  (a prewarm of the code helper would load the main vectors a second time). Releases and reloads go to
  `memory-release.log`.
- `refresh` updates changed files using the app's chosen folders and exclusions, then reloads the service.
  Optional Windows daily scheduling; skips while the app is running (a skipped run keeps the last report for `--last`).
  It reports an error when the helper ends before reporting anything, and stops it if it ignores the time limit.
- `status` reads DigUp's numbers with thousands separators (it showed only the kinds under 1,000 files).
- `q`: a slow passage lookup no longer fails the whole search; copy-folder words match whole folder names only.
  `--under` keeps results spelled under the folder as given or as resolved (a short 8.3 name, a symlink such as
  macOS `/var`); before, only the resolved spelling counted and such results were dropped. Everything is always
  given the resolved folder (it matches nothing under a short name or a link).
- Synthetic regression tests cover aliases, spacing, parent evidence, copies, filters, expansion and code routing.

## 0.2.0

- Text first: `search "..." --root DIR` reads the text of the files in a folder (txt, md, docx, hwpx, pptx, xlsx, odt,
  html, rtf and PDFs) without any index and ranks pieces of up to ~1,200 characters by meaning with EmbeddingGemma 2
  through `digup worker`, or by shared words when DigUp is missing. Vectors are cached per file (numbers only), so
  later searches read only changed files. Same Korean results as the DigUp index on the CI runner. `--estimate` shows the files and the expected time first; `--max-seconds` bounds a run.
- PDF text reading in plain Python (Flate streams, object streams, ToUnicode maps for Korean and other scripts,
  form XObjects). Scanned PDFs are reported as having no text.
- `index --media-only` (and `--no-pdf`) leaves text documents out of the DigUp index, which is meant for photos,
  screenshots, scans, audio and video.
- `--passages` now also works for PDFs in DigUp index results.

## 0.1.0

First release.

- `lfk.py` command line (Python 3.9+, standard library only), JSON output, exit codes 0/1/2/3.
- `doctor`: tools found (environment variable → config file → PATH → usual folders → Windows registry), versions,
  readiness, what each feature will use, install commands, and the computer's OS, CPU, memory, graphics cards and disks.
- `setup`: lists the missing tools with their install commands and licence notes; installs them with winget (or
  Chocolatey) only when given `--yes` and a choice (`--all`, which leaves out WizTree, or `--tools`).
- Finding: `find` (Everything, or a folder walk), `search` and `index`/`status` (DigUp official 0.7.0-beta.1 commands;
  `--passages` picks the best paragraphs inside a file with EmbeddingGemma 2 through `digup worker`).
- Looking: `size` (WizTree or walk), `dupes` (Czkawka or Python), `similar` (Czkawka), `empty`, `exif` (ExifTool).
- Doing: `archive` (7-Zip or zipfile), `copy` (robocopy or shutil), `plan`, `move`, `trash`, `undo`.
  Preview by default, undo logs for everything executed, Recycle Bin only, protected system folders,
  and `undo` restores trashed items from the Windows Recycle Bin and the Linux home Trash.
- Claude Code skill and plugin marketplace in one repository.
