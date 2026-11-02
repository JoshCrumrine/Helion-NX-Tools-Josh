# NX 2506
# Author:  jo388c
# Created: 2026-10-30
# Stamps a large see-through text watermark, such as UNRELEASED, diagonally across every page of a
# PDF, centered on the drawing's border. export_pdf.py calls it after NX has written the PDF.
#
# NX's own watermark (PrintPDFBuilder.AddWatermark) is not used: NX hands it to its PDF converter,
# NXPLOT\bin\pdf\cgm2pdf.exe, which puts the text about 3/4 in left of center on a 17 x 11 in sheet
# (as in Teamcenter's UNRELEASED PDFs). Here the text is
#   * centered on the drawing's frame: the outermost lines on the page, which are the border (the
#     page itself when it has no lines);
#   * laid along the frame's diagonal, lower left to upper right, as large as fits in 90% of it;
#   * Helvetica (the same letter widths as Arial), black at 20% opacity: lighter than Teamcenter's 30%.
#
# Plain Python: NX's Python has no PDF library, and this needs no NXOpen. NX's bytes are kept as they
# are and the watermark is appended as an incremental update (new versions of the page objects, a
# font, an opacity setting and one small drawing per page), which every PDF reader understands.
import math
import os
import re
import zlib

OPACITY = 0.2       # 0 is invisible, 1 solid black
FILL = 0.9          # the text spans this share of the frame's width or height, whichever is tighter

# Helvetica's character widths (1/1000 of the font size) for the characters 32 to 126, from Adobe's
# font metrics; Arial's are the same. Other characters count as 556.
_WIDTHS = dict(zip(range(32, 127), (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,     # space to /
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556,                                   # 0 to 9
    278, 278, 584, 584, 584, 556, 1015,                                                 # : to @
    667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833,                    # A to M
    722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611,                    # N to Z
    278, 278, 278, 469, 556, 333,                                                       # [ to `
    556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833,                    # a to m
    556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500,                    # n to z
    334, 260, 334, 584)))                                                               # { to ~
_CAP_HEIGHT = 718   # height of Helvetica's capitals, 1/1000 of the font size


class PdfError(Exception):
    """The PDF could not be read or changed."""


# ----------------------------------------------------------------------------- PDF objects
class Ref(tuple):
    """An indirect reference, "12 0 R": (object number, generation)."""

    def __new__(cls, num, gen=0):
        return tuple.__new__(cls, (num, gen))


class Name(bytes):
    """A name, with its slash: b"/Type"."""


class Raw(bytes):
    """A number, string, true, false or null, kept exactly as the PDF writes it."""


_WS = rb"\x00\t\n\f\r\x20"
_SPACE = rb"(?:[" + _WS + rb"]|%[^\r\n]*)*"                      # white space and comments
_REGULAR = rb"[^" + _WS + rb"()<>\[\]{}/%]"                      # a character that is not a delimiter
_TOKEN = re.compile(
    _SPACE + rb"(?:(?P<num>\d+)[" + _WS + rb"]+(?P<gen>\d+)[" + _WS + rb"]+R(?!" + _REGULAR + rb")"
    rb"|(?P<dict><<)|(?P<enddict>>>)|(?P<array>\[)|(?P<endarray>\])"
    rb"|(?P<name>/" + _REGULAR + rb"*)"
    rb"|(?P<hex><[0-9A-Fa-f" + _WS + rb"]*>)"
    rb"|(?P<string>\()"
    rb"|(?P<number>[-+]?(?:\d+\.?\d*|\.\d+))"
    rb"|(?P<word>[A-Za-z]+))")
_SIMPLE_STRING = re.compile(rb"\((?:[^()\\]|\\.)*\)", re.S)


def _string_end(data, start):
    """The index just after the literal string that opens with "(" at data[start]."""
    simple = _SIMPLE_STRING.match(data, start)
    if simple:
        return simple.end()
    depth, i = 0, start
    while i < len(data):
        byte = data[i]
        if byte == 0x5C:                # backslash: the next byte is escaped
            i += 1
        elif byte == 0x28:
            depth += 1
        elif byte == 0x29:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise PdfError("a string in the PDF has no end")


def _parse(data, pos):
    """(object, end): the PDF object that starts at data[pos], after any white space."""
    m = _TOKEN.match(data, pos)
    if m is None:
        raise PdfError("unreadable PDF data at byte {0}".format(pos))
    end = m.end()
    if m.group("gen") is not None:
        return Ref(int(m.group("num")), int(m.group("gen"))), end
    kind = m.lastgroup
    if kind in ("dict", "array"):
        closing = "end" + kind
        items = []
        while True:
            m = _TOKEN.match(data, end)
            if m is not None and m.lastgroup == closing:
                break
            item, end = _parse(data, end)
            items.append(item)
        end = m.end()
        if kind == "array":
            return items, end
        if len(items) % 2 or not all(isinstance(key, Name) for key in items[0::2]):
            raise PdfError("unreadable dictionary in the PDF at byte {0}".format(pos))
        return dict(zip(items[0::2], items[1::2])), end
    if kind == "name":
        return Name(m.group(kind)), end
    if kind == "string":
        stop = _string_end(data, m.start(kind))
        return Raw(data[m.start(kind):stop]), stop
    if kind in ("hex", "number") or (kind == "word" and m.group(kind) in (b"true", b"false", b"null")):
        return Raw(m.group(kind)), end
    raise PdfError("unexpected {0!r} in the PDF at byte {1}".format(m.group(kind)[:20], m.start(kind)))


def _number(x):
    """`x` as a PDF number: no exponent, at most 4 decimals."""
    if isinstance(x, int):
        return b"%d" % x
    text = (b"%.4f" % x).rstrip(b"0").rstrip(b".")
    return b"0" if text in (b"", b"-", b"-0") else text


def _dump(value):
    """`value` written as PDF."""
    if isinstance(value, dict):
        return b"<<" + b" ".join(key + b" " + _dump(item) for key, item in value.items()) + b">>"
    if isinstance(value, list):
        return b"[" + b" ".join(_dump(item) for item in value) + b"]"
    if isinstance(value, Ref):
        return b"%d %d R" % value
    if isinstance(value, bytes):        # Name, Raw
        return bytes(value)
    return _number(value)


def _stream(content):
    return b"<</Length %d>>\nstream\n" % len(content) + content + b"\nendstream"


def _png_unpredict(data, columns, colors, bits):
    """Undo the PNG predictors (one filter-type byte in front of each row) of compressed data."""
    step = max(1, colors * bits // 8)               # bytes per pixel
    width = (columns * colors * bits + 7) // 8      # bytes per row
    out, above = bytearray(), bytearray(width)
    for start in range(0, len(data), width + 1):
        kind, row = data[start], bytearray(data[start + 1:start + 1 + width].ljust(width, b"\0"))
        for i in range(width):
            left = row[i - step] if i >= step else 0
            if kind == 1:
                row[i] = (row[i] + left) & 0xFF
            elif kind == 2:
                row[i] = (row[i] + above[i]) & 0xFF
            elif kind == 3:
                row[i] = (row[i] + ((left + above[i]) >> 1)) & 0xFF
            elif kind == 4:
                corner = above[i - step] if i >= step else 0
                guess = left + above[i] - corner
                near = min((abs(guess - left), 0, left), (abs(guess - above[i]), 1, above[i]),
                           (abs(guess - corner), 2, corner))
                row[i] = (row[i] + near[2]) & 0xFF
            elif kind != 0:
                raise PdfError("unknown PNG predictor {0} in the PDF".format(kind))
        out += row
        above = row
    return bytes(out)


# ----------------------------------------------------------------------------- reading a PDF
_OBJECT = re.compile(_SPACE + rb"(\d+)[" + _WS + rb"]+(\d+)[" + _WS + rb"]+obj\b")
_STREAM = re.compile(_SPACE + rb"stream(?:\r\n|\n|\r)")
_ENDSTREAM = re.compile(rb"[" + _WS + rb"]*endstream")
_XREF = re.compile(_SPACE + rb"xref\b")
_TRAILER = re.compile(_SPACE + rb"trailer\b")
_XREF_SUBSECTION = re.compile(_SPACE + rb"(\d+)[" + _WS + rb"]+(\d+)")
_XREF_ENTRY = re.compile(_SPACE + rb"(\d+)[" + _WS + rb"]+(\d+)[" + _WS + rb"]+([nf])")
_INHERITED = (b"/Resources", b"/MediaBox", b"/CropBox", b"/Rotate")


class _Pdf:
    """The objects of a PDF held in memory (reading only), and the update that changes some."""

    def __init__(self, data):
        if b"%PDF-" not in data[:1024]:
            raise PdfError("not a PDF file")
        self.data = data
        self.where = {}             # object number -> (byte offset, generation) or (None, object stream)
        self.trailer = None
        self.xref_stream = False    # whether the last cross-reference section is a stream
        self._cache = {}
        self._object_streams = {}
        at = data.rfind(b"startxref")
        m = re.match(rb"startxref[" + _WS + rb"]+(\d+)", data[at:at + 64]) if at >= 0 else None
        if m is None:
            raise PdfError("the PDF has no startxref, so it is not complete")
        self.startxref = int(m.group(1))
        seen, offset = set(), self.startxref
        while offset is not None and offset not in seen:   # newest section first, then /Prev
            seen.add(offset)
            table = _XREF.match(data, offset) is not None
            trailer = self._read_table(offset) if table else self._read_xref_stream(offset)
            if self.trailer is None:
                self.trailer, self.xref_stream = trailer, not table
            if trailer.get(b"/XRefStm") is not None:     # a hybrid file: a table plus a stream
                self._read_xref_stream(int(trailer[b"/XRefStm"]))
            offset = int(trailer[b"/Prev"]) if trailer.get(b"/Prev") is not None else None
        if b"/Encrypt" in self.trailer:
            raise PdfError("the PDF is encrypted")

    def _read_table(self, offset):
        pos = _XREF.match(self.data, offset).end()
        while True:
            m = _TRAILER.match(self.data, pos)
            if m is not None:
                trailer = _parse(self.data, m.end())[0]
                if not isinstance(trailer, dict):
                    raise PdfError("the PDF's trailer is damaged")
                return trailer
            m = _XREF_SUBSECTION.match(self.data, pos)
            if m is None:
                raise PdfError("the PDF's cross-reference table is damaged")
            first, count = int(m.group(1)), int(m.group(2))
            pos = m.end()
            for num in range(first, first + count):
                entry = _XREF_ENTRY.match(self.data, pos)
                if entry is None:
                    raise PdfError("the PDF's cross-reference table is damaged")
                pos = entry.end()
                if entry.group(3) == b"n":      # newer sections were read first and win
                    self.where.setdefault(num, (int(entry.group(1)), int(entry.group(2))))

    def _read_xref_stream(self, offset):
        _, value, raw = self._object_at(offset)
        if not isinstance(value, dict) or value.get(b"/Type") != b"/XRef" or raw is None:
            raise PdfError("no cross-reference data where the PDF says it is")
        rows = self._decode(value, raw)
        widths = [int(w) for w in value[b"/W"]]
        index = [int(v) for v in value.get(b"/Index", [0, value[b"/Size"]])]
        pos = 0
        for first, count in zip(index[0::2], index[1::2]):
            for num in range(first, first + count):
                fields = []
                for width in widths:
                    fields.append(int.from_bytes(rows[pos:pos + width], "big"))
                    pos += width
                kind = fields[0] if widths[0] else 1
                if kind == 1:
                    self.where.setdefault(num, (fields[1], fields[2]))
                elif kind == 2:
                    self.where.setdefault(num, (None, fields[1]))
        return value

    def _object_at(self, offset):
        """(number, object, raw stream data or None) for the object written at byte `offset`."""
        m = _OBJECT.match(self.data, offset)
        if m is None:
            raise PdfError("no object at byte {0} of the PDF".format(offset))
        value, pos = _parse(self.data, m.end())
        raw = None
        stream = _STREAM.match(self.data, pos)
        if stream is not None and isinstance(value, dict):
            start = stream.end()
            raw = self.data[start:self._stream_end(value, start)]
        return int(m.group(1)), value, raw

    def _stream_end(self, value, start):
        try:
            end = start + int(self.resolve(value.get(b"/Length")))
            if _ENDSTREAM.match(self.data, end):
                return end
        except (TypeError, ValueError, PdfError):
            pass
        end = self.data.find(b"endstream", start)     # a wrong /Length: find the end instead
        if end < 0:
            raise PdfError("a stream in the PDF has no end")
        if self.data[end - 2:end] == b"\r\n":
            return end - 2
        return end - 1 if self.data[end - 1:end] in (b"\r", b"\n") else end

    def _load(self, num):
        """(object, raw stream data or None) for object `num`; (None, None) if there is none."""
        if num in self._cache:
            return self._cache[num]
        where = self.where.get(num)
        if where is None:               # not cached: the cross-references may still be being read
            return None, None
        if where[0] is None:
            loaded = (self._from_object_stream(where[1], num), None)
        else:
            found, value, raw = self._object_at(where[0])
            if found != num:
                raise PdfError("object {0} is not where the PDF says it is".format(num))
            loaded = (value, raw)
        self._cache[num] = loaded
        return loaded

    def _from_object_stream(self, stream_num, num):
        if stream_num not in self._object_streams:
            value, raw = self._load(stream_num)
            if not isinstance(value, dict) or raw is None:
                raise PdfError("object stream {0} is missing from the PDF".format(stream_num))
            text = self._decode(value, raw)
            first = int(value[b"/First"])
            numbers = [int(n) for n in text[:first].split()]
            self._object_streams[stream_num] = (text, first, dict(zip(numbers[0::2], numbers[1::2])))
        text, first, offsets = self._object_streams[stream_num]
        if num not in offsets:
            raise PdfError("object {0} is missing from its object stream".format(num))
        return _parse(text, first + offsets[num])[0]

    def _decode(self, value, raw):
        """The data of a stream, uncompressed."""
        filters = self.resolve(value.get(b"/Filter"))
        params = self.resolve(value.get(b"/DecodeParms"))
        if filters is None:
            return raw
        if not isinstance(filters, list):
            filters, params = [filters], [params]
        elif not isinstance(params, list):
            params = [params] * len(filters)
        data = raw
        for name, param in zip(filters, params):
            if name not in (b"/FlateDecode", b"/Fl"):
                raise PdfError("the PDF uses {0} compression, which this cannot read".format(
                    bytes(name).decode("latin-1")))
            try:
                data = zlib.decompressobj().decompress(data)
            except zlib.error as ex:
                raise PdfError("damaged compressed data in the PDF ({0})".format(ex))
            param = self.resolve(param)
            predictor = int(param.get(b"/Predictor", 1)) if isinstance(param, dict) else 1
            if predictor >= 10:
                data = _png_unpredict(data, int(param.get(b"/Columns", 1)), int(param.get(b"/Colors", 1)),
                                      int(param.get(b"/BitsPerComponent", 8)))
            elif predictor != 1:
                raise PdfError("the PDF uses a TIFF predictor, which this cannot read")
        return data

    def get(self, num):
        """Object `num`; None if the PDF has no such object."""
        return self._load(num)[0]

    def resolve(self, value):
        """`value`, or the object it refers to."""
        for _ in range(32):
            if not isinstance(value, Ref):
                return value
            value = self.get(value[0])
        raise PdfError("the PDF refers to itself in a loop")

    def stream_data(self, ref):
        """The uncompressed data of the stream `ref` refers to."""
        value, raw = self._load(ref[0])
        if not isinstance(value, dict) or raw is None:
            raise PdfError("object {0} of the PDF is not a stream".format(ref[0]))
        return self._decode(value, raw)

    def size(self):
        return int(self.trailer.get(b"/Size", 0))

    def pages(self):
        """[(Ref, page dictionary, its attributes including the inherited ones)] in page order."""
        catalog = self.resolve(self.trailer.get(b"/Root"))
        if not isinstance(catalog, dict):
            raise PdfError("the PDF has no catalog")
        found = []
        self._collect(catalog.get(b"/Pages"), {}, found, set())
        return found

    def _collect(self, ref, inherited, found, seen):
        if not isinstance(ref, Ref) or ref in seen:
            raise PdfError("the PDF's page tree is damaged")
        seen.add(ref)
        node = self.get(ref[0])
        if not isinstance(node, dict):
            raise PdfError("the PDF's page tree is damaged")
        attributes = dict(inherited)
        attributes.update((key, node[key]) for key in _INHERITED if key in node)
        if node.get(b"/Type") == b"/Pages" or (b"/Kids" in node and node.get(b"/Type") != b"/Page"):
            for kid in self.resolve(node.get(b"/Kids")) or []:
                self._collect(kid, attributes, found, seen)
        else:
            found.append((ref, node, attributes))

    def content_refs(self, page):
        """The page's content streams, as references."""
        value = page.get(b"/Contents")
        if isinstance(value, Ref):
            target = self.get(value[0])
            if not isinstance(target, list):
                return [value]
            value = target
        return [item for item in value if isinstance(item, Ref)] if isinstance(value, list) else []

    def update(self, objects):
        """The bytes to append to the PDF to add or replace `objects`, [(Ref, object as written)]:
        the objects, then a cross-reference section of the same kind as the PDF's last one."""
        out = bytearray(b"" if self.data.endswith((b"\n", b"\r")) else b"\n")
        base = len(self.data)
        where = {}
        for ref, body in objects:
            where[ref[0]] = (base + len(out), ref[1])
            out += b"%d %d obj\n" % ref + body + b"\nendobj\n"
        kept = (b"/Root", b"/Info", b"/ID")
        trailer = {Name(key): self.trailer[key] for key in kept if key in self.trailer}
        trailer[Name(b"/Prev")] = self.startxref
        size = max([self.size()] + [num + 1 for num in where])
        if self.xref_stream:
            where[size] = (base + len(out), 0)          # the cross-reference stream lists itself
            numbers = sorted(where)
            rows = b"".join(b"\x01" + where[n][0].to_bytes(4, "big") + where[n][1].to_bytes(2, "big")
                            for n in numbers)
            trailer.update({Name(b"/Type"): Name(b"/XRef"), Name(b"/Size"): size + 1,
                            Name(b"/W"): [1, 4, 2], Name(b"/Index"): _runs(numbers),
                            Name(b"/Length"): len(rows)})
            start = where[size][0]
            out += b"%d 0 obj\n" % size + _dump(trailer) + b"\nstream\n" + rows + b"\nendstream\nendobj\n"
        else:
            start = base + len(out)
            out += b"xref\n"
            runs = _runs(sorted(where))
            for first, count in zip(runs[0::2], runs[1::2]):
                out += b"%d %d\n" % (first, count)
                for num in range(first, first + count):
                    out += b"%010d %05d n\r\n" % where[num]
            trailer[Name(b"/Size")] = size
            out += b"trailer\n" + _dump(trailer) + b"\n"
        out += b"startxref\n%d\n%%%%EOF\n" % start
        return bytes(out)


def _runs(numbers):
    """[first, count, first, count, ...] for the runs of consecutive numbers in sorted `numbers`."""
    runs = []
    for num in numbers:
        if runs and runs[-2] + runs[-1] == num:
            runs[-1] += 1
        else:
            runs += [num, 1]
    return runs


# ----------------------------------------------------------------------------- where the watermark goes
_CONTENT = re.compile(
    rb"(?:[" + _WS + rb"]+|%[^\r\n]*)*(?:(?P<number>[-+]?(?:\d+\.?\d*|\.\d+))"
    rb"|(?P<op>[A-Za-z'\"*][A-Za-z0-9'\"*]*)"
    rb"|(?P<string>\()"
    rb"|(?P<operand>/" + _REGULAR + rb"*|<<|>>|<[0-9A-Fa-f" + _WS + rb"]*>|[\[\]{}])"
    rb"|(?P<end>\Z))")
_INLINE_IMAGE_END = re.compile(rb"[" + _WS + rb"]EI(?=[" + _WS + rb"/\[<(%]|\Z)")
_PAINT = frozenset((b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"))


def _point(ctm, x, y):
    a, b, c, d, e, f = ctm
    return a * x + c * y + e, b * x + d * y + f


def _times(m, n):
    """The matrix product m x n (apply m, then n), PDF's [a b c d e f] form."""
    a, b, c, d, e, f = m
    p, q, r, s, t, u = n
    return a * p + b * r, a * q + b * s, c * p + d * r, c * q + d * s, e * p + f * r + t, e * q + f * s + u


def _numbers(operands, count):
    """The last `count` operands if they are all numbers, else None."""
    values = operands[-count:]
    return values if len(values) == count and None not in values else None


def _drawing_extent(content):
    """(x0, y0, x1, y1): the extent, in page coordinates, of the lines and shapes that the page
    `content` strokes or fills (text and pictures are left out); None if it draws none."""
    ctm, saved, operands, path = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), [], [], []
    x0 = y0 = math.inf
    x1 = y1 = -math.inf
    pos = 0
    while True:
        m = _CONTENT.match(content, pos)
        if m is None:                   # a stray byte
            pos += 1
            continue
        kind, pos = m.lastgroup, m.end()
        if kind == "end":
            break
        if kind == "number":
            operands.append(float(m.group(kind)))
            continue
        if kind != "op":
            if kind == "string":
                pos = _string_end(content, m.start(kind))
            operands.append(None)
            continue
        op = m.group(kind)
        if op == b"q":
            saved.append(ctm)
        elif op == b"Q":
            ctm = saved.pop() if saved else ctm
        elif op == b"cm":
            values = _numbers(operands, 6)
            if values:
                ctm = _times(values, ctm)
        elif op in (b"m", b"l", b"c", b"v", b"y"):
            values = _numbers(operands, {b"m": 2, b"l": 2, b"c": 6}.get(op, 4))
            if values:
                path.extend(_point(ctm, values[i], values[i + 1]) for i in range(0, len(values), 2))
        elif op == b"re":
            values = _numbers(operands, 4)
            if values:
                x, y, w, h = values
                corners = ((x, y), (x + w, y), (x, y + h), (x + w, y + h))
                path.extend(_point(ctm, px, py) for px, py in corners)
        elif op in _PAINT:
            if path:
                xs, ys = zip(*path)
                x0, y0, x1, y1 = min(x0, *xs), min(y0, *ys), max(x1, *xs), max(y1, *ys)
            path = []
        elif op == b"n":                # a clipping path: not drawn
            path = []
        elif op == b"ID":               # inline picture data: skip to its end
            stop = _INLINE_IMAGE_END.search(content, pos)
            pos = stop.end() if stop else len(content)
        operands = []
    return (x0, y0, x1, y1) if x0 <= x1 and y0 <= y1 else None


def _rect(pdf, value):
    """A PDF rectangle as (x0, y0, x1, y1), lower left first; None if it is not one."""
    value = pdf.resolve(value)
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        xa, ya, xb, yb = (float(pdf.resolve(v)) for v in value)
    except (TypeError, ValueError):
        return None
    box = (min(xa, xb), min(ya, yb), max(xa, xb), max(ya, yb))
    return box if box[2] > box[0] and box[3] > box[1] else None


def _frame(pdf, page, attributes):
    """(x0, y0, x1, y1) to center the watermark on: the drawing's border, found as the extent of the
    lines on the page; the page itself when it has no lines or they cover less than half of it."""
    page_box = (_rect(pdf, attributes.get(b"/CropBox")) or _rect(pdf, attributes.get(b"/MediaBox"))
                or (0.0, 0.0, 612.0, 792.0))
    try:
        lines = _drawing_extent(b"\n".join(pdf.stream_data(ref) for ref in pdf.content_refs(page)))
    except Exception:                   # the page itself is a good enough fallback
        lines = None
    if lines:
        box = (max(lines[0], page_box[0]), max(lines[1], page_box[1]),
               min(lines[2], page_box[2]), min(lines[3], page_box[3]))
        if (box[2] - box[0] >= (page_box[2] - page_box[0]) / 2
                and box[3] - box[1] >= (page_box[3] - page_box[1]) / 2):
            return box
    return page_box


def _drawing(text, frame, rotate, font, state):
    """Page content that writes `text` (bytes) through the middle of `frame`, along its diagonal as
    the page is seen (turned `rotate` degrees), with the resources named `font` and `state`."""
    x0, y0, x1, y1 = frame
    width, height = x1 - x0, y1 - y0
    seen_width, seen_height = (height, width) if rotate % 180 else (width, height)
    angle = math.atan2(seen_height, seen_width) + math.radians(rotate)
    cos, sin = math.cos(angle), math.sin(angle)
    advance = sum(_WIDTHS.get(byte, 556) for byte in text) / 1000.0    # the text's width at size 1
    cap = _CAP_HEIGHT / 1000.0
    size = FILL * min(width / (advance * abs(cos) + cap * abs(sin)),
                      height / (advance * abs(sin) + cap * abs(cos)))
    # The middle of the text (half its width, half a capital's height) goes on the frame's middle
    half_width, half_height = size * advance / 2, size * cap / 2
    x = (x0 + x1) / 2 - (cos * half_width - sin * half_height)
    y = (y0 + y1) / 2 - (sin * half_width + cos * half_height)
    literal = text.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    literal = literal.replace(b"\r", b"\\r")
    matrix = b" ".join(_number(v) for v in (cos, sin, -sin, cos, x, y))
    return (b"Q\nq %s gs 0 g BT %s %s Tf %s Tm (%s) Tj ET Q\n"
            % (state, font, _number(size), matrix, literal))


def _free_name(names, base=b"/HelionWatermark"):
    """A resource name not yet in `names`."""
    name, n = Name(base), 1
    while name in names:
        name, n = Name(base + b"%d" % n), n + 1
    return name


def _copy(value):
    return dict(value) if isinstance(value, dict) else {}


# ----------------------------------------------------------------------------- stamping
def watermark_bytes(data, text, opacity=OPACITY):
    """(new PDF, page count): the PDF `data` with `text` across every page. The original bytes are
    kept; the watermark is appended to them as an incremental update."""
    text = text.encode("cp1252", "replace")
    if not text.strip():
        raise ValueError("no watermark text")
    pdf = _Pdf(data)
    pages = pdf.pages()
    if not pages:
        raise PdfError("the PDF has no pages")
    objects = []
    next_num = max([pdf.size()] + [num + 1 for num in pdf.where])

    def add(body):
        nonlocal next_num
        ref = Ref(next_num)
        next_num += 1
        objects.append((ref, body))
        return ref

    font = add(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>")
    state = add(b"<</Type/ExtGState/ca %s/CA %s>>" % (_number(opacity), _number(opacity)))
    begin = add(_stream(b"q\n"))        # keeps NX's drawing state away from the watermark's
    marks = []
    for ref, page, attributes in pages:
        resources = _copy(pdf.resolve(attributes.get(b"/Resources")))
        fonts = _copy(pdf.resolve(resources.get(b"/Font")))
        states = _copy(pdf.resolve(resources.get(b"/ExtGState")))
        font_name, state_name = _free_name(fonts), _free_name(states)
        fonts[font_name], states[state_name] = font, state
        resources[Name(b"/Font")], resources[Name(b"/ExtGState")] = fonts, states
        rotate = int(float(pdf.resolve(attributes.get(b"/Rotate")) or 0)) % 360
        mark = add(_stream(_drawing(text, _frame(pdf, page, attributes), rotate, font_name, state_name)))
        marks.append(mark)
        new_page = dict(page)
        new_page[Name(b"/Contents")] = [begin] + pdf.content_refs(page) + [mark]
        new_page[Name(b"/Resources")] = resources
        objects.append((ref, _dump(new_page)))
    result = data + pdf.update(objects)

    check = _Pdf(result)                # read it back: every page must end with its watermark
    if [check.content_refs(page)[-1:] for _, page, _ in check.pages()] != [[mark] for mark in marks]:
        raise PdfError("the watermarked PDF did not read back as expected")
    return result, len(pages)


def add_watermark(path, text, opacity=OPACITY):
    """Stamp `text` across every page of the PDF file `path`. Returns the number of pages."""
    with open(path, "rb") as f:
        data = f.read()
    result, pages = watermark_bytes(data, text, opacity)
    temp = path + ".watermark"
    try:
        with open(temp, "wb") as f:
            f.write(result)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.remove(temp)
    return pages
