"""Text out of PDF files, standard library only.

Covers PDFs made by programs (word processors, browsers, office suites): Flate-compressed content streams, object
streams, fonts with ToUnicode maps (how Korean and other non-Latin text is usually stored), simple 8-bit fonts, and
text inside form XObjects. Scanned PDFs (pictures of pages) have no text to read: they need DigUp's index.
Encrypted PDFs are skipped.
"""
import re
import zlib

_OBJ = re.compile(rb"(\d+)\s+(\d+)\s+obj\b")
_REF = rb"(\d+)\s+(\d+)\s+R"


class PdfError(Exception):
    pass


def _inflate(data):
    try:
        return zlib.decompress(data)
    except zlib.error:
        d = zlib.decompressobj()
        try:
            return d.decompress(data)  # truncated or with trailing junk: keep what decodes
        except zlib.error:
            return b""


class _Pdf:
    def __init__(self, data):
        self.data = data
        self.objs = {}      # num -> (dict bytes, stream bytes or None)
        self._parse_objects()
        self._parse_object_streams()

    # ------------------------------------------------------------------ objects
    def _parse_objects(self):
        d = self.data
        for m in _OBJ.finditer(d):
            num = int(m.group(1))
            start = m.end()
            end = d.find(b"endobj", start)
            if end < 0:
                continue
            body = d[start:end]
            s = re.search(rb"stream\r?\n", body)
            if s and body[:s.start()].rstrip().endswith(b">>"):
                head = body[:s.start()]
                raw = body[s.end():]
                length = re.search(rb"/Length\s+(\d+)(?!\s+\d+\s+R)", head)
                if length and int(length.group(1)) <= len(raw):
                    raw = raw[:int(length.group(1))]
                else:
                    e = raw.rfind(b"endstream")
                    raw = raw[:e] if e >= 0 else raw
                self.objs[num] = (head, raw)
            else:
                self.objs.setdefault(num, (body, None))

    def _parse_object_streams(self):
        for num, (head, raw) in list(self.objs.items()):
            if raw is None or b"/ObjStm" not in head:
                continue
            data = self.stream(num)
            n = re.search(rb"/N\s+(\d+)", head)
            first = re.search(rb"/First\s+(\d+)", head)
            if not data or not n or not first:
                continue
            nums = list(map(int, data[:int(first.group(1))].split()))
            pairs = list(zip(nums[0::2], nums[1::2]))
            base = int(first.group(1))
            for i, (onum, off) in enumerate(pairs):
                end = base + pairs[i + 1][1] if i + 1 < len(pairs) else len(data)
                self.objs.setdefault(onum, (data[base + off:end], None))

    def head(self, num):
        o = self.objs.get(num)
        return o[0] if o else b""

    def stream(self, num):
        o = self.objs.get(num)
        if not o or o[1] is None:
            return b""
        head, raw = o
        filters = re.findall(rb"/(\w+Decode)", head.split(b"/DecodeParms")[0])
        if not filters:
            return raw
        if filters == [b"FlateDecode"]:
            return _inflate(raw)
        return b""  # images and other filters carry no text

    def resolve(self, value):
        """A dict body for an inline '<<...>>' or an 'n g R' reference."""
        m = re.match(rb"\s*" + _REF, value)
        if m:
            return self.head(int(m.group(1)))
        return value

    # ------------------------------------------------------------------ dict helpers
    @staticmethod
    def entry(body, key):
        """Raw value text of /key in a dict body: a reference, an inline dict, an array or a name."""
        m = re.search(rb"/" + key + rb"(?![A-Za-z])\s*", body)
        if not m:
            return None
        rest = body[m.end():]
        r = re.match(_REF, rest)
        if r:
            return r.group(0)
        if rest.startswith(b"<<"):
            depth, i = 0, 0
            while i < len(rest) - 1:
                if rest[i:i + 2] == b"<<":
                    depth += 1
                    i += 2
                    continue
                if rest[i:i + 2] == b">>":
                    depth -= 1
                    i += 2
                    if depth == 0:
                        return rest[:i]
                    continue
                i += 1
            return rest
        if rest.startswith(b"["):
            e = rest.find(b"]")
            return rest[:e + 1]
        r = re.match(rb"/[^\s/<>\[\]()]+|[^\s/<>\[\]()]+", rest)
        return r.group(0) if r else None

    def refs(self, value):
        return [int(n) for n, _ in re.findall(_REF, value or b"")]

    # ------------------------------------------------------------------ pages
    def pages(self):
        root = re.search(rb"/Root\s+" + _REF, self.data)
        out = []
        if root:
            pages = self.entry(self.head(int(root.group(1))), b"Pages")
            self._walk(self.refs(pages)[:1], None, out, set())
        if not out:  # damaged or unusual: every /Type /Page in object order
            for num in sorted(self.objs):
                h = self.head(num)
                if re.search(rb"/Type\s*/Page(?!s)", h):
                    out.append((num, self.entry(h, b"Resources")))
        return out

    def _walk(self, nums, inherited, out, seen):
        for num in nums:
            if num in seen:
                continue
            seen.add(num)
            h = self.head(num)
            res = self.entry(h, b"Resources") or inherited
            if re.search(rb"/Type\s*/Pages", h):
                self._walk(self.refs(self.entry(h, b"Kids")), res, out, seen)
            else:
                out.append((num, res))

    def contents(self, page_num):
        value = self.entry(self.head(page_num), b"Contents") or b""
        if value.startswith(b"[") or re.match(rb"\s*" + _REF, value):
            nums = self.refs(value)
            # a reference may point at an array of streams
            if len(nums) == 1 and self.objs.get(nums[0], (b"", None))[1] is None:
                nums = self.refs(self.head(nums[0]))
            return b"\n".join(self.stream(n) for n in nums)
        return b""

    # ------------------------------------------------------------------ fonts
    def fonts(self, resources):
        res = self.resolve(resources or b"")
        fonts = self.resolve(self.entry(res, b"Font") or b"")
        out = {}
        for name, n, _ in re.findall(rb"/([^\s/<>\[\]()]+)\s+" + _REF, fonts):
            out[name] = _Font(self, self.head(int(n)))
        return out

    def xobjects(self, resources):
        res = self.resolve(resources or b"")
        xo = self.resolve(self.entry(res, b"XObject") or b"")
        out = {}
        for name, n, _ in re.findall(rb"/([^\s/<>\[\]()]+)\s+" + _REF, xo):
            h = self.head(int(n))
            if re.search(rb"/Subtype\s*/Form", h):
                out[name] = (int(n), self.entry(h, b"Resources") or resources)
        return out


class _Font:
    def __init__(self, pdf, body):
        self.two_byte = b"/Type0" in body or b"Identity-H" in body
        self.cmap = {}
        tu = pdf.entry(body, b"ToUnicode")
        if tu:
            nums = pdf.refs(tu)
            if nums:
                self._read_cmap(pdf.stream(nums[0]))

    def _read_cmap(self, data):
        text = data.decode("latin-1")
        cs = re.search(r"begincodespacerange\s*<([0-9A-Fa-f]+)>", text)
        if cs:
            self.two_byte = len(cs.group(1)) >= 4

        def uni(h):
            try:
                return bytes.fromhex(h).decode("utf-16-be")
            except (ValueError, UnicodeDecodeError):
                return ""

        for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
            for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
                self.cmap[int(src, 16)] = uni(dst)
        for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
            for lo, hi, rest in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(\[[^\]]*\]|<[0-9A-Fa-f]+>)", block):
                lo, hi = int(lo, 16), int(hi, 16)
                if hi - lo > 65535:
                    continue
                if rest.startswith("["):
                    for i, d in enumerate(re.findall(r"<([0-9A-Fa-f]*)>", rest)):
                        self.cmap[lo + i] = uni(d)
                else:
                    base = bytes.fromhex(rest[1:-1])
                    for i in range(hi - lo + 1):
                        b = bytearray(base)
                        b[-1:] = bytes([(base[-1] + i) & 0xFF]) if len(base) else b""
                        if len(base) >= 2 and base[-1] + i > 0xFF:  # carry into the byte before
                            v = int.from_bytes(base, "big") + i
                            b = bytearray(v.to_bytes(len(base), "big"))
                        try:
                            self.cmap[lo + i] = bytes(b).decode("utf-16-be")
                        except UnicodeDecodeError:
                            pass

    def decode(self, raw):
        if self.two_byte:
            codes = [int.from_bytes(raw[i:i + 2], "big") for i in range(0, len(raw) - 1, 2)]
            return "".join(self.cmap.get(c, "") for c in codes)
        if self.cmap:
            return "".join(self.cmap.get(b, chr(b) if 32 <= b < 127 else "") for b in raw)
        return raw.decode("cp1252", "replace")


# ---------------------------------------------------------------------- content streams

_TOKEN = re.compile(rb"""
    \s+ | %[^\r\n]* |
    (?P<str>\() | (?P<hex><[0-9A-Fa-f\s]*>) | (?P<dict><<|>>) | (?P<arr>[\[\]]) |
    (?P<name>/[^\s/<>\[\]()%{}]*) | (?P<num>[+-]?(?:\d+\.?\d*|\.\d+)) | (?P<op>[A-Za-z'"*][A-Za-z0-9'"*]*) |
    (?P<other>.)
""", re.X | re.S)

_ESC = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\"}


def _literal(data, i):
    """Read a (string) starting after '(' at i; return (bytes, next index)."""
    out = bytearray()
    depth = 1
    n = len(data)
    while i < n:
        c = data[i:i + 1]
        if c == b"\\":
            nxt = data[i + 1:i + 2]
            if nxt in _ESC:
                out += _ESC[nxt]
                i += 2
            elif nxt.isdigit():
                m = re.match(rb"[0-7]{1,3}", data[i + 1:i + 4])
                out.append(int(m.group(0), 8) & 0xFF)
                i += 1 + len(m.group(0))
            else:
                i += 2  # line continuation or unknown escape
            continue
        if c == b"(":
            depth += 1
        elif c == b")":
            depth -= 1
            if depth == 0:
                return bytes(out), i + 1
        out += c
        i += 1
    return bytes(out), n


class _Lines:
    """Text pieces gathered into lines, each with the height (y) it was drawn at."""

    def __init__(self):
        self.lines = []   # (y or None, text, font size on the page or None)
        self.cur = []
        self.y = None
        self.font_size = None
        self.scale = 1.0

    def add(self, text):
        self.cur.append(text)

    def move_to(self, y):
        if self.y is not None and y is not None and abs(y - self.y) > 0.5:
            self.end()
        self.y = y

    def end(self):
        text = "".join(self.cur).strip()
        if text:
            size = self.font_size * self.scale if self.font_size else None
            self.lines.append((self.y, text, size))
        self.cur = []


def _run(pdf, content, fonts, xobjects, out, depth=0):
    stack = []
    font = None
    i, n = 0, len(content)
    while i < n:
        m = _TOKEN.match(content, i)
        if not m:
            i += 1
            continue
        i = m.end()
        if m.group("str"):
            s, i = _literal(content, i)
            stack.append(("s", s))
        elif m.group("hex"):
            h = re.sub(rb"\s", b"", m.group("hex")[1:-1])
            if len(h) % 2:
                h += b"0"
            stack.append(("s", bytes.fromhex(h.decode())))
        elif m.group("arr"):
            stack.append(("a", m.group("arr")))
        elif m.group("dict"):
            stack.append(("d", None))
        elif m.group("name"):
            stack.append(("n", m.group("name")[1:]))
        elif m.group("num"):
            stack.append(("f", float(m.group("num"))))
        elif m.group("op"):
            op = m.group("op")
            nums = [v for t, v in stack if t == "f"]
            if op == b"BI":  # inline image: skip its binary data
                e = re.search(rb"\sEI\b", content[i:])
                i = i + e.end() if e else n
            elif op == b"Tf":
                names = [v for t, v in stack if t == "n"]
                font = fonts.get(names[-1]) if names else None
                if nums:
                    out.font_size = abs(nums[-1])
            elif op in (b"Tj", b"'", b'"'):
                if op != b"Tj":
                    out.end()
                strs = [v for t, v in stack if t == "s"]
                if strs:
                    out.add(_decode(font, strs[-1]))
            elif op == b"TJ":
                for t, v in _last_array(stack):
                    if t == "s":
                        out.add(_decode(font, v))
                    elif t == "f" and v < -200:
                        out.add(" ")
            elif op in (b"Td", b"TD"):
                # a move along the line is ordinary glyph placement (browsers place every glyph this way);
                # real word gaps come as space glyphs or TJ spacing
                if len(nums) >= 2 and abs(nums[-1]) > 0.01:
                    out.move_to((out.y or 0) + nums[-1])
            elif op == b"Tm":
                if len(nums) >= 6:
                    out.scale = abs(nums[-3]) or abs(nums[-6]) or 1.0
                    out.move_to(nums[-1])
            elif op == b"T*":
                out.end()
            # ET does not end a line: browsers draw one line as many BT..ET pieces at the same height
            # (a space can be a piece of its own); a new line shows up as a new height in Tm/Td
            elif op == b"Do" and depth < 3:
                names = [v for t, v in stack if t == "n"]
                if names and names[-1] in xobjects:
                    num, res = xobjects[names[-1]]
                    _run(pdf, pdf.stream(num), {**fonts, **pdf.fonts(res)}, pdf.xobjects(res), out, depth + 1)
            stack = []
    return out


def _paragraphs(lines):
    """Join lines into paragraphs: a gap clearly bigger than plain line spacing (about 1.2-1.5 x the font size,
    or else the usual gap between lines) starts a new one."""
    gaps = sorted(abs(b[0] - a[0]) for a, b in zip(lines, lines[1:])
                  if a[0] is not None and b[0] is not None and abs(b[0] - a[0]) > 0.5)
    usual = gaps[len(gaps) // 2] * 1.3 if gaps else None
    paras, cur = [], []
    prev = None
    for y, text, size in lines:
        limit = size * 1.6 if size else usual
        if cur and prev is not None and y is not None and limit and abs(y - prev) > limit:
            paras.append(cur)
            cur = []
        cur.append(text)
        prev = y
    if cur:
        paras.append(cur)
    out = []
    for p in paras:
        joined = p[0]
        for t in p[1:]:
            # wrapped Latin words need a space; Korean/Chinese/Japanese wrap inside words
            sep = " " if (joined[-1:].isascii() or t[:1].isascii()) else ""
            joined = joined.rstrip() + sep + t.lstrip()
        out.append(joined)
    return out


def _last_array(stack):
    items, inside = [], False
    for t, v in stack:
        if t == "a" and v == b"[":
            items, inside = [], True
        elif t == "a" and v == b"]":
            inside = False
        elif inside:
            items.append((t, v))
    return items


def _decode(font, raw):
    if font is None:
        return raw.decode("cp1252", "replace")
    return font.decode(raw)


def extract(data, max_pages=2000):
    """Text of a PDF given as bytes ('' when it has none, e.g. a scan). Raises PdfError when unreadable."""
    if not data.startswith(b"%PDF"):
        raise PdfError("not a PDF")
    if re.search(rb"/Encrypt\s", data[-4096:]) or re.search(rb"trailer[^%]*?/Encrypt", data):
        raise PdfError("encrypted PDF")
    pdf = _Pdf(data)
    pages = []
    for num, res in pdf.pages()[:max_pages]:
        lines = _run(pdf, pdf.contents(num), pdf.fonts(res), pdf.xobjects(res), _Lines())
        lines.end()
        paras = [re.sub(r"[ \t]+", " ", t).strip() for t in _paragraphs(lines.lines)]
        pages.append("\n\n".join(t for t in paras if t))
    return "\n\n".join(p for p in pages if p)
