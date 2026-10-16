# Changelog

All notable changes. Versions follow [Semantic Versioning](https://semver.org/); the version lives in
`.claude-plugin/plugin.json` and `skills/local-file-kit/scripts/lfkit/__init__.py` (keep them equal).

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
