"""Plain text out of common document files, standard library only (for picking passages inside a file)."""
import html
import os
import re
import zipfile

TEXT_EXTS = {".txt", ".md", ".markdown", ".csv", ".tsv", ".log", ".json", ".xml", ".yaml", ".yml", ".ini", ".rst",
             ".html", ".htm", ".rtf", ".tex", ".srt", ".vtt"}
ZIP_EXTS = {".docx", ".pptx", ".xlsx", ".odt", ".odp", ".hwpx"}
READABLE = TEXT_EXTS | ZIP_EXTS
MAX_BYTES = 8 * 1024 * 1024


def _decode(data):
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    for enc in ("utf-8", "cp949", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", "replace")


def _xml_text(xml, para_tags):
    """Text of an office XML part, one paragraph per block."""
    xml = re.sub(r"<(?:\w+:)?(?:%s)\b[^>]*/?>" % "|".join(para_tags), "\n", xml)
    xml = re.sub(r"<(?:\w+:)?(?:tab|br|line-break|s)\b[^>]*/?>", " ", xml)
    out = [html.unescape(re.sub(r"<[^>]+>", "", chunk)).strip() for chunk in xml.split("\n")]
    return "\n\n".join(t for t in out if t)


def _zip_text(path, ext):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()

        def read(n):
            return z.read(n).decode("utf-8", "replace")

        if ext == ".docx":
            return _xml_text(read("word/document.xml"), ["p"])
        if ext == ".pptx":
            slides = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                            key=lambda n: int(re.findall(r"\d+", n)[-1]))
            return "\n\n".join(_xml_text(read(n), ["p"]) for n in slides)
        if ext == ".xlsx":
            if "xl/sharedStrings.xml" not in names:
                return ""
            return "\n".join(html.unescape(t) for t in re.findall(r"<t[^>]*>([^<]*)</t>", read("xl/sharedStrings.xml")))
        if ext in (".odt", ".odp"):
            return _xml_text(read("content.xml"), ["p", "h"])
        if ext == ".hwpx":
            secs = sorted((n for n in names if re.match(r"Contents/section\d+\.xml$", n)),
                          key=lambda n: int(re.findall(r"\d+", n)[-1]))
            return "\n\n".join(_xml_text(read(n), ["p"]) for n in secs)
    return ""


def read_text(path):
    """Text of a file, or None when this module cannot read that kind of file."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in READABLE:
        return None
    if os.path.getsize(path) > MAX_BYTES:
        return None
    if ext in ZIP_EXTS:
        try:
            return _zip_text(path, ext)
        except (zipfile.BadZipFile, KeyError, OSError):
            return None
    with open(path, "rb") as f:
        text = _decode(f.read())
    if ext in (".html", ".htm", ".xml"):
        text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
        text = re.sub(r"(?i)<(br|p|div|li|h\d|tr)\b[^>]*>", "\n\n", text)
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    elif ext == ".rtf":
        text = re.sub(r"\\par[d]?\b", "\n\n", text)
        text = re.sub(r"\\'[0-9a-f]{2}|\\[a-z]+-?\d* ?|[{}]", "", text)
    return text


def passages(text, max_chars=600, min_chars=12):
    """Split text into passages: paragraphs, long ones cut at sentence ends, short neighbours merged."""
    paras = [re.sub(r"[ \t]+", " ", p).strip() for p in re.split(r"\n\s*\n", text.replace("\r\n", "\n"))]
    if len(paras) <= 1:  # no blank lines: treat each line as a paragraph
        paras = [l.strip() for l in text.splitlines()]
    pieces = []
    for p in paras:
        if not p:
            continue
        while len(p) > max_chars:
            cut = max(p.rfind(s, 0, max_chars) for s in (". ", "다. ", "? ", "! ", "。", "\n"))
            cut = cut + 1 if cut > max_chars // 3 else max_chars
            pieces.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            pieces.append(p)
    merged = []
    for p in pieces:
        if merged and (len(merged[-1]) < min_chars * 4) and len(merged[-1]) + len(p) + 1 <= max_chars:
            merged[-1] = merged[-1] + "\n" + p
        else:
            merged.append(p)
    return [m for m in merged if len(m) >= min_chars]
