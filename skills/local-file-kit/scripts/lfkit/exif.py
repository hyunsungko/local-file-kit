"""exif: when and with what a photo or video was taken (ExifTool)."""
import json
import os

from . import tools
from .util import LfkError, abspath, remove_quietly, run, temp_path

DEFAULT_TAGS = ["FileName", "Directory", "FileSize", "MIMEType", "DateTimeOriginal", "CreateDate", "ModifyDate",
                "Make", "Model", "LensModel", "ImageWidth", "ImageHeight", "Orientation", "GPSLatitude", "GPSLongitude",
                "GPSAltitude", "Duration", "VideoFrameRate", "Software"]
MEDIA_EXTS = "jpg,jpeg,png,heic,heif,tif,tiff,webp,gif,bmp,dng,cr2,cr3,nef,arw,orf,rw2,raf,mp4,mov,m4v,avi,mkv,3gp,mts,m2ts"


def cmd_exif(args):
    exe = tools.require("exiftool")
    paths = [abspath(p) for p in args.paths]
    for p in paths:
        if not os.path.exists(p):
            raise LfkError("not_found", f"no such file or folder: {p}", exit_code=2)
    # One UTF-8 argfile carries every option and path: Windows command lines garble non-ASCII names for Perl.
    lines = ["-j", "-n", "-charset", "filename=utf8", "-api", "LargeFileSupport=1"]
    if not args.all:
        tags = args.tags.split(",") if args.tags else DEFAULT_TAGS
        lines += ["-" + t.strip() for t in tags if t.strip()]
    if any(os.path.isdir(p) for p in paths):
        if args.recursive:
            lines.append("-r")
        for e in (args.ext or MEDIA_EXTS).split(","):
            lines += ["-ext", e.strip().lstrip(".")]
    lines += paths
    argfile = temp_path(".args")
    with open(argfile, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    try:
        rc, out, err = run([exe, "-@", argfile], timeout=args.max_seconds)
    finally:
        remove_quietly(argfile)
    if rc not in (0, 1) or (rc == 1 and not out.strip()):
        if "No matching files" in err or "0 image files read" in err:
            return {"ok": True, "count": 0, "results": [], "hint": "no photo or video files found (see --ext)"}
        raise LfkError("tool_failed", f"exiftool exited with code {rc}", stderr=err.strip()[-500:])
    rows = json.loads(out) if out.strip() else []
    results = rows[:args.limit]
    for r in results:
        src = r.pop("SourceFile", None)
        if src:
            r["path"] = os.path.normpath(src)
    out_obj = {"ok": True, "count": len(rows), "results": results}
    if len(rows) > args.limit:
        out_obj["truncated"] = f"showing {args.limit} of {len(rows)}"
    warnings = [l for l in err.splitlines() if l.startswith(("Warning", "Error"))]
    if warnings:
        out_obj["warnings"] = warnings[:20]
    return out_obj
