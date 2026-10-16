"""Command line: one entry point, JSON out."""
import argparse
import sys

from . import __version__
from .util import LfkError, emit, parse_size, setup_stdio

EPILOG = """examples:
  lfk.py doctor
  lfk.py setup                           (list missing tools)  ... --all --yes (install them)
  lfk.py find "budget 2024" --ext xlsx,pdf --limit 20
  lfk.py find report --root "D:\\Work" --engine walk
  lfk.py search "tenant contract renewal terms" --kind doc,pdf --passages 3
  lfk.py size "D:\\Photos" --top 15
  lfk.py dupes "D:\\Photos" --min-size 100k
  lfk.py plan "C:\\Users\\me\\Downloads" --to "D:\\Sorted" --by kind
  lfk.py move --plan plan.csv            (preview)   ... --execute (do it, writes an undo log)
  lfk.py trash "D:\\old\\copy 2.jpg"      (preview)   ... --execute (Recycle Bin)
  lfk.py undo <undo-log.csv> --execute

Output is JSON (UTF-8). Exit codes: 0 ok, 1 failed, 2 bad arguments, 3 a needed tool is missing.
"""


def _size(text):
    try:
        return parse_size(text)
    except LfkError as e:
        raise argparse.ArgumentTypeError(e.message)


class JsonArgumentParser(argparse.ArgumentParser):
    """Usage mistakes come back as JSON too, so an agent can read them like any other error."""

    def error(self, message):
        raise LfkError("bad_argument", message, exit_code=2, usage=self.format_usage().strip())


def _common(suppress):
    """--pretty/--ascii/--out work before or after the command. On subcommands they default to SUPPRESS so a
    value given before the command is not reset by the subcommand's own default."""
    c = argparse.ArgumentParser(add_help=False)
    d = {"default": argparse.SUPPRESS} if suppress else {}
    c.add_argument("--pretty", action="store_true", help="indent the JSON", **d)
    c.add_argument("--ascii", action="store_true", help="escape non-ASCII characters (for consoles that garble UTF-8)", **d)
    c.add_argument("--out", metavar="FILE", help="write the JSON to FILE (UTF-8) instead of the screen", **d)
    return c


def build_parser():
    p = JsonArgumentParser(prog="lfk.py", description="local-file-kit: find and organize files on this computer.",
                           epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter, parents=[_common(False)])
    p.add_argument("--version", action="version", version=f"local-file-kit {__version__}")
    sub = p.add_subparsers(dest="command", metavar="command")
    common = _common(True)

    def cmd(name, help_text):
        return sub.add_parser(name, help=help_text, description=help_text, parents=[common])

    s = cmd("doctor", "what is installed, what works, what to install; this computer's specs")

    s = cmd("setup", "install missing tools (winget/Chocolatey on Windows); lists them first, installs only with --yes")
    s.add_argument("--all", action="store_true", help="every missing tool that can be installed, except WizTree")
    s.add_argument("--tools", help="only these, comma separated: everything,czkawka,exiftool,7zip,wiztree")
    s.add_argument("--yes", action="store_true", help="really install (after the user agreed to the list)")
    s.add_argument("--max-seconds", type=int, default=1800, help="time limit per installer")

    s = cmd("find", "find files and folders by name (Everything; folder walk without it)")
    s.add_argument("query", nargs="?", default="", help="words that must all appear in the name (* and ? wildcards; "
                   "a word with \\ matches the full path). With --engine everything, full Everything syntax works")
    s.add_argument("--root", action="append", metavar="DIR", help="only inside this folder (repeatable)")
    s.add_argument("--ext", help="extensions, comma separated: pdf,docx")
    s.add_argument("--type", choices=["file", "folder"])
    s.add_argument("--min-size", help="e.g. 10MB")
    s.add_argument("--max-size")
    s.add_argument("--after", metavar="DATE", help="modified on or after YYYY-MM-DD")
    s.add_argument("--before", metavar="DATE", help="modified before YYYY-MM-DD")
    s.add_argument("--regex", action="store_true", help="the query is a regular expression on the name")
    s.add_argument("--case", action="store_true", help="match case")
    s.add_argument("--sort", choices=["name", "path", "size", "modified"])
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--engine", choices=["auto", "everything", "walk"], default="auto")
    s.add_argument("--max-seconds", type=int, default=120, help="time limit for a folder walk")

    s = cmd("search", "find files by what they say: with --root, reads the text of the files there (no index); "
            "without, asks the DigUp index (also pictures, scans)")
    s.add_argument("query")
    s.add_argument("--root", action="append", metavar="DIR",
                   help="search inside this folder (repeatable); reads text directly unless --engine digup")
    s.add_argument("--engine", choices=["auto", "text", "digup"], default="auto",
                   help="auto: text when --root is given, otherwise the DigUp index")
    s.add_argument("--estimate", action="store_true", help="text search: only count files and estimate the time")
    s.add_argument("--max-seconds", type=int, default=300, help="text search: time limit for reading new files")
    s.add_argument("--max-files", type=int, default=20000, help="text search: at most this many files")
    s.add_argument("--no-cache", action="store_true", help="text search: do not store paragraph vectors")
    s.add_argument("--words", action="store_true", help="text search: rank by shared words, skip the model")
    s.add_argument("--kind", help="DigUp index: screenshot,image,pdf,doc,audio,video")
    s.add_argument("--limit", "-n", type=int, default=10)
    s.add_argument("--passages", type=int, default=0, metavar="K",
                   help="also return the K best paragraphs inside each text-like result (EmbeddingGemma 2)")
    s.add_argument("--no-excerpt", action="store_true", help="leave text excerpts out of the output (privacy)")
    s.add_argument("--zgate", type=float, help="DigUp index: how much a match must stand out (default 2.0; 0 shows all)")
    s.add_argument("--index", metavar="DIR", help="a separate DigUp index folder (default: the DigUp app's index)")
    s.add_argument("--cpu", action="store_true", help="run the model on the CPU (DIGUP_DEVICE=cpu)")

    s = cmd("index", "add folders to the DigUp index (or --estimate how long that takes); best for pictures and scans")
    s.add_argument("folders", nargs="+")
    s.add_argument("--estimate", action="store_true", help="only estimate files and time; index nothing")
    s.add_argument("--media-only", action="store_true",
                   help="leave out text documents (searched as text with search --root): pictures, PDFs, audio, video")
    s.add_argument("--no-pdf", action="store_true", help="with --media-only, also leave out PDFs")
    s.add_argument("--index", metavar="DIR", help="a separate DigUp index folder")
    s.add_argument("--exclude", action="append", metavar="DIR")
    s.add_argument("--limit", type=int, help="index at most N new files this run")
    s.add_argument("--cpu", action="store_true")
    s.add_argument("--force", action="store_true", help="write the app's index even while the DigUp app runs")
    s.add_argument("--timeout", type=int, default=6 * 3600, help="seconds before giving up (default 6 h)")

    s = cmd("status", "what the DigUp index holds")
    s.add_argument("--index", metavar="DIR")

    s = cmd("size", "what takes up space in a folder or drive (WizTree; folder walk without it)")
    s.add_argument("path")
    s.add_argument("--top", type=int, default=20)
    s.add_argument("--engine", choices=["auto", "wiztree", "walk"], default="auto")
    s.add_argument("--max-seconds", type=int, default=600)

    s = cmd("dupes", "identical files (Czkawka; Python without it)")
    s.add_argument("paths", nargs="+")
    s.add_argument("--min-size", type=_size, default=1,
                   help="ignore smaller files, e.g. 100k (default: every non-empty file)")
    s.add_argument("--limit", type=int, default=100, help="groups to list")
    s.add_argument("--engine", choices=["auto", "czkawka", "python"], default="auto")
    s.add_argument("--max-seconds", type=int, default=1800)

    s = cmd("similar", "look-alike images (Czkawka)")
    s.add_argument("paths", nargs="+")
    s.add_argument("--max-difference", type=int, default=5, help="0-40, higher finds looser matches (default 5)")
    s.add_argument("--hash-size", type=int, default=16, choices=[8, 16, 32, 64])
    s.add_argument("--hash-alg", default="Gradient",
                   choices=["Gradient", "Mean", "Median", "Blockhash", "VertGradient", "DoubleGradient"])
    s.add_argument("--min-size", type=int, default=16384, help="bytes; smaller images are skipped (default 16384)")
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--max-seconds", type=int, default=3600)

    s = cmd("empty", "empty folders (and with --files, empty files)")
    s.add_argument("paths", nargs="+")
    s.add_argument("--files", action="store_true")
    s.add_argument("--engine", choices=["auto", "czkawka", "python"], default="auto")
    s.add_argument("--max-seconds", type=int, default=1800)

    s = cmd("exif", "photo/video details: date taken, camera, GPS, size, duration (ExifTool)")
    s.add_argument("paths", nargs="+")
    s.add_argument("--recursive", "-r", action="store_true")
    s.add_argument("--tags", help="comma separated tag names instead of the default set")
    s.add_argument("--all", action="store_true", help="every tag")
    s.add_argument("--ext", help="extensions to read inside folders (default: common photo/video types)")
    s.add_argument("--limit", type=int, default=200)
    s.add_argument("--max-seconds", type=int, default=1800)

    s = cmd("archive", "create / list / test / extract archives (7-Zip; .zip with Python without it)")
    s.add_argument("action", choices=["create", "list", "test", "extract"])
    s.add_argument("archive")
    s.add_argument("sources", nargs="*", help="files and folders to put in (create)")
    s.add_argument("--to", metavar="DIR", help="extract into this folder (existing files are kept)")
    s.add_argument("--limit", type=int, default=500)
    s.add_argument("--max-seconds", type=int, default=6 * 3600)

    s = cmd("copy", "copy a folder or file; preview unless --execute; never deletes or overwrites by default")
    s.add_argument("source")
    s.add_argument("dest")
    s.add_argument("--execute", action="store_true")
    s.add_argument("--overwrite-changed", action="store_true",
                   help="also replace destination files that differ from the source (default: keep them)")
    s.add_argument("--limit", type=int, default=200)
    s.add_argument("--max-seconds", type=int, default=6 * 3600)

    s = cmd("plan", "write a move plan (CSV) that sorts a folder's files into subfolders; changes nothing")
    s.add_argument("source")
    s.add_argument("--to", required=True, metavar="DIR")
    s.add_argument("--by", choices=["kind", "ext", "year", "month"], default="kind")
    s.add_argument("--exif", action="store_true", help="year/month from the date a photo was taken (ExifTool)")
    s.add_argument("--recursive", "-r", action="store_true")
    s.add_argument("--save", metavar="CSV", help="where to write the plan (default: per-user data folder)")

    s = cmd("move", "move files/folders; preview unless --execute; writes an undo log")
    s.add_argument("paths", nargs="*")
    s.add_argument("--to", metavar="DIR")
    s.add_argument("--plan", metavar="CSV", help="CSV with source,destination rows (from 'plan' or hand-made)")
    s.add_argument("--on-conflict", choices=["skip", "rename"], default="skip")
    s.add_argument("--execute", action="store_true")
    s.add_argument("--log", metavar="CSV", help="undo log path (default: per-user data folder)")
    s.add_argument("--limit", type=int, default=500)

    s = cmd("trash", "send files/folders to the Recycle Bin; preview unless --execute")
    s.add_argument("paths", nargs="+")
    s.add_argument("--execute", action="store_true")
    s.add_argument("--log", metavar="CSV")
    s.add_argument("--limit", type=int, default=500)

    s = cmd("undo", "reverse the moves in an undo log; preview unless --execute")
    s.add_argument("log_file")
    s.add_argument("--execute", action="store_true")
    s.add_argument("--limit", type=int, default=500)
    return p


def dispatch(args):
    from . import archive, content, copyfiles, doctor, dupes, exif, find, organize, setup, size
    table = {
        "doctor": doctor.cmd_doctor, "setup": setup.cmd_setup, "find": find.cmd_find, "search": content.cmd_search, "index": content.cmd_index,
        "status": content.cmd_status, "size": size.cmd_size, "dupes": dupes.cmd_dupes, "similar": dupes.cmd_similar,
        "empty": dupes.cmd_empty, "exif": exif.cmd_exif, "archive": archive.cmd_archive, "copy": copyfiles.cmd_copy,
        "plan": organize.cmd_plan, "move": organize.cmd_move, "trash": organize.cmd_trash, "undo": organize.cmd_undo,
    }
    return table[args.command](args)


def main(argv=None):
    setup_stdio()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except LfkError as e:
        argv = sys.argv[1:] if argv is None else argv
        emit(e.to_json(), "--pretty" in argv, "--ascii" in argv)
        return e.exit_code
    if not args.command:
        parser.print_help()
        return 2
    out_file = args.out
    try:
        result = dispatch(args)
        emit(result, args.pretty, args.ascii, out_file)
        return 0 if result.get("ok", True) else 1
    except LfkError as e:
        emit(e.to_json(), args.pretty, args.ascii, out_file)
        return e.exit_code
    except KeyboardInterrupt:
        emit({"ok": False, "error": "interrupted", "message": "stopped by the user"}, args.pretty, args.ascii)
        return 130
    except Exception as e:  # report, don't dump a traceback on the agent
        import traceback
        emit({"ok": False, "error": "internal_error", "message": f"{type(e).__name__}: {e}",
              "trace": traceback.format_exc().splitlines()[-6:]}, args.pretty, args.ascii)
        return 1


if __name__ == "__main__":
    sys.exit(main())
