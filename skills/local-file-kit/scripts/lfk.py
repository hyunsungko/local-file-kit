#!/usr/bin/env python3
"""local-file-kit command line. Run `python lfk.py --help`. Needs Python 3.9+ and nothing else."""
import os
import sys

if sys.version_info < (3, 9):
    sys.stdout.write('{"ok": false, "error": "python_too_old", "message": "local-file-kit needs Python 3.9 or newer"}\n')
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lfkit.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
