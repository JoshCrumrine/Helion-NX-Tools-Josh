"""Clean up the DXFs Export Body DXF writes. Plain Python, no NXOpen: NX writes a DXF in the background
(its translator takes about 40 s), so lib/body_dxf.py runs this as a separate process that waits for
each file, in the repo's .venv Python:

    python -I lib/dxf_cleanup.py <job file>

The job file (JSON, deleted once read) lists the DXFs: {"dxf": path, "since": time the export started,
"flat": bool, "axes": [view x axis, view y axis], "points": body vertices, "bends": [[start, end], ...]}.
One line per DXF is printed; the caller saves the output as helion_dxf_cleanup.log in the Windows
temp folder. The translator's own log beside each DXF (<name>.log) is deleted once the DXF is written,
and a DXF that came out empty is deleted too, so the output folder holds only usable DXFs.

Each DXF gets each LINE, ARC and CIRCLE once (the top and bottom of a plate land on top of each other in
the view, so NX writes every one twice), no zero-length lines, and, for a sheet metal Flat Solid, no
bend lines. Everything else in the file stays as NX wrote it.
"""
import json
import math
import os
import sys
import time

WAIT_SECONDS = 300  # how long to wait for NX to write a DXF


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


_TOL = 1e-3         # part units: DXF points closer than this are the same point
_ANGLE_TOL = 1e-3   # degrees, for arc start and end angles
_CELL = 1e-2        # grid cell for finding points again; must be larger than _TOL


class _Grid(object):
    """Things filed under points, found again near a point (within _TOL)."""

    def __init__(self):
        self.cells = {}

    @staticmethod
    def _cell(x, y):
        return int(math.floor(x / _CELL)), int(math.floor(y / _CELL))

    def add(self, point, item):
        self.cells.setdefault(self._cell(*point), []).append(item)

    def near(self, point):
        cx, cy = self._cell(*point)
        for i in (cx - 1, cx, cx + 1):
            for j in (cy - 1, cy, cy + 1):
                for item in self.cells.get((i, j), ()):
                    yield item


def _close(a, b, tol=_TOL):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _same_angle(a, b):
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d) <= _ANGLE_TOL


def _same_shape(s, t):
    """Whether two shapes from _shape are the same line (either way round), arc or circle."""
    if s[0] != t[0]:
        return False
    if s[0] == "LINE":
        return ((_close(s[1], t[1]) and _close(s[2], t[2]))
                or (_close(s[1], t[2]) and _close(s[2], t[1])))
    if not (_close(s[1], t[1]) and abs(s[2] - t[2]) <= _TOL):
        return False
    return s[0] == "CIRCLE" or (_same_angle(s[3], t[3]) and _same_angle(s[4], t[4]))


def _shape(kind, values):
    """("LINE", start, end), ("ARC", center, radius, start angle, end angle) or ("CIRCLE", center,
    radius) in the DXF's x-y plane, from an entity's group code values; None for anything else. An arc
    or circle drawn on the plane's back (extrusion direction -Z) is turned to face +Z."""
    def num(code, default=0.0):
        return float(values.get(code, default))
    if kind == "LINE":
        return ("LINE", (num("10"), num("20")), (num("11"), num("21")))
    if kind not in ("ARC", "CIRCLE"):
        return None
    center, radius = (num("10"), num("20")), num("40")
    start, end = num("50"), num("51")
    if num("230", 1.0) < 0:     # seen from the back: x is mirrored, so the arc runs the other way
        center = (-center[0], center[1])
        start, end = (180.0 - end) % 360.0, (180.0 - start) % 360.0
    return ("CIRCLE", center, radius) if kind == "CIRCLE" else ("ARC", center, radius, start, end)


def _ends(shape):
    """The points a shape is filed under: the ends of a line or arc, the center of a circle."""
    if shape[0] == "LINE":
        return [shape[1], shape[2]]
    if shape[0] == "CIRCLE":
        return [shape[1]]
    (cx, cy), r = shape[1], shape[2]
    return [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
            for a in shape[3:5]]


def _find_shift(ends, refs):
    """(dx, dy, share): the shift that puts the largest share of the points `refs` on points in
    `ends` (within _TOL). Tries no shift first, then the shifts that put one of the first few refs on
    an end, scored on a sample of the refs."""
    grid = _Grid()
    for p in ends:
        grid.add(p, p)

    def share(dx, dy, points):
        moved = [(x + dx, y + dy) for x, y in points]
        hits = sum(1 for p in moved if any(_close(p, e) for e in grid.near(p)))
        return hits / float(len(points))

    if not ends or not refs:
        return 0.0, 0.0, 0.0
    best = (0.0, 0.0, share(0.0, 0.0, refs))
    if best[2] < 0.9:
        sample = refs[:: max(1, len(refs) // 50)]
        tried = set()
        for r in refs[:3]:
            for e in ends:
                dx, dy = e[0] - r[0], e[1] - r[1]
                key = (round(dx / _TOL), round(dy / _TOL))
                if key in tried:
                    continue
                tried.add(key)
                score = share(dx, dy, sample)
                if score > best[2]:
                    best = (dx, dy, score)
        best = (best[0], best[1], share(best[0], best[1], refs))
    return best


def _entities(pairs):
    """[(first, end)] pair-index ranges of the entities in the ENTITIES section, or [] if none."""
    for s in range(len(pairs) - 1):
        if pairs[s] == (b"0", b"SECTION") and pairs[s + 1] == (b"2", b"ENTITIES"):
            break
    else:
        return []
    found, first = [], None
    for k in range(s + 2, len(pairs)):
        if pairs[k][0] == b"0":
            if first is not None:
                found.append((first, k))
            if pairs[k][1] == b"ENDSEC":
                return found
            first = k
    return []


def clean_dxf(path, axes=None, points=(), bends=()):
    """Rewrite the DXF at `path` with each LINE, ARC and CIRCLE once, without zero-length LINEs and
    without the `bends` lines; every other entity and section stays as it is.

    `bends` are 3D (start, end) pairs, put into the DXF's 2D coordinates with the view's x and y
    `axes`. There they can differ from the DXF's by a shift, the one that puts the most of `points`
    (the body's vertices, 3D) on line and arc ends in the DXF. If no shift puts half of them there,
    no bend line is removed. Returns a dict: bends (bend lines removed, each counted once), located
    (False when bends could not be lined up), doubles and zero_length (entities removed), and empty
    (True when the DXF has no entities at all, so there was nothing to clean up).
    """
    with open(path, "rb") as f:
        data = f.read()
    eol = b"\r\n" if b"\r\n" in data else b"\n"
    rows = data.split(eol)
    pairs = [(rows[i].strip(), rows[i + 1].strip()) for i in range(0, len(rows) - 1, 2)]
    entities = _entities(pairs)
    report = {"bends": 0, "located": True, "doubles": 0, "zero_length": 0, "empty": not entities}
    if not entities:
        return report

    shapes = []
    for first, end in entities:
        values = {}
        for code, value in pairs[first + 1:end]:
            values.setdefault(code.decode("ascii", "replace"), value.decode("latin-1"))
        try:
            shapes.append(_shape(pairs[first][1].decode("latin-1"), values))
        except ValueError:
            shapes.append(None)

    bend_2d = []
    if bends:
        x_axis, y_axis = axes
        dx, dy, share = _find_shift([e for s in shapes if s for e in _ends(s)],
                                    [(_dot(p, x_axis), _dot(p, y_axis)) for p in points])
        report["located"] = share >= 0.5
        if report["located"]:
            for a, b in bends:
                line = ("LINE", (_dot(a, x_axis) + dx, _dot(a, y_axis) + dy),
                        (_dot(b, x_axis) + dx, _dot(b, y_axis) + dy))
                if not any(_same_shape(line, other) for other in bend_2d):
                    bend_2d.append(line)

    keep, kept, matched = [], _Grid(), set()
    for (first, end), shape in zip(entities, shapes):
        if shape is not None:
            if shape[0] == "LINE" and _close(shape[1], shape[2]):
                report["zero_length"] += 1
                continue
            hit = [i for i, line in enumerate(bend_2d) if _same_shape(shape, line)]
            if hit:
                matched.update(hit)
                continue
            if any(_same_shape(shape, other) for p in _ends(shape) for other in kept.near(p)):
                report["doubles"] += 1
                continue
            for p in _ends(shape)[:1]:
                kept.add(p, shape)
        keep.append((first, end))
    report["bends"] = len(matched)

    if len(keep) < len(entities):
        out = rows[:2 * entities[0][0]]
        for first, end in keep:
            out.extend(rows[2 * first:2 * end])
        out.extend(rows[2 * entities[-1][1]:])
        temporary = path + ".tmp"
        with open(temporary, "wb") as f:
            f.write(eol.join(out))
        _replace(temporary, path)
    return report


def _replace(source, target, tries=20):
    """os.replace, retried for a few seconds while another program (the translator) still has `target`
    open."""
    for attempt in range(tries):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.5)


def _finished(path):
    """Whether the DXF at `path` is complete: it ends with the EOF marker."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 64))
            return f.read().rstrip().endswith(b"EOF")
    except OSError:
        return False


def wait_for_dxf(path, since, seconds=None):
    """Wait until `path` has been written (complete, and changed at or after the time `since`) and has
    kept its size for half a second. True once it has, False after `seconds` (WAIT_SECONDS if None)."""
    deadline = time.time() + (WAIT_SECONDS if seconds is None else seconds)
    size = None
    while time.time() < deadline:
        try:
            info = os.stat(path)
            ready = info.st_mtime >= since - 2 and _finished(path)
        except OSError:
            ready = False
        if ready and size == info.st_size:
            return True
        size = info.st_size if ready else None
        time.sleep(0.5)
    return False


def describe(report, flat, bends_found):
    """One line saying what clean_dxf did (`report`) to the DXF of a body that is a `flat` solid or not,
    and whether bend lines were found on it in NX (`bends_found`)."""
    if report.get("empty"):
        return "the DXF is empty: NX wrote no lines into it"
    said = []
    if flat:
        if not bends_found:
            said.append("no bend lines found")
        elif not report["located"]:
            said.append("bend lines NOT removed: the part could not be lined up with the DXF")
        else:
            said.append("removed {0} bend line{1}".format(
                report["bends"], "" if report["bends"] == 1 else "s"))
    if report["doubles"]:
        said.append("removed {0} doubled line{1}/arc{1}".format(
            report["doubles"], "" if report["doubles"] == 1 else "s"))
    if report["zero_length"]:
        said.append("removed {0} zero-length line{1}".format(
            report["zero_length"], "" if report["zero_length"] == 1 else "s"))
    return "; ".join(said) or "nothing to clean up"


def run_jobs(jobs, say=print):
    """Wait for and clean up each DXF in `jobs` (see the module description), saying what happened
    through say(line). Returns 0 when all were cleaned up, 1 otherwise."""
    code = 0
    for job in jobs:
        name = os.path.basename(job["dxf"])
        try:
            if not wait_for_dxf(job["dxf"], job["since"]):
                say("{0}: NX had not written it after {1} s, so it was not cleaned up".format(
                    name, WAIT_SECONDS))
                code = 1
                continue
            bends = [(tuple(a), tuple(b)) for a, b in job.get("bends", ())]
            points = [tuple(p) for p in job.get("points", ())]
            report = clean_dxf(job["dxf"], job.get("axes"), points, bends)
            said = describe(report, job.get("flat", False), bool(bends)) + remove_translator_log(
                job["dxf"], job["since"])
            if report["empty"]:                 # of no use: leave nothing behind
                os.remove(job["dxf"])
                said += "; deleted it"
                code = 1
            say("{0}: {1}".format(name, said))
        except Exception as ex:
            say("{0}: clean-up failed, the DXF is as NX wrote it: {1}".format(name, ex))
            code = 1
    return code


def remove_translator_log(path, since, seconds=10):
    """Delete the log NX's translator writes beside the DXF at `path` (<name>.log), once it is there
    (written at or after `since`; waited for up to `seconds`). Returns "" when it was deleted or there
    was none, else a note to add to the report line."""
    log_file = os.path.splitext(path)[0] + ".log"
    deadline = time.time() + seconds
    while True:
        try:
            if os.stat(log_file).st_mtime >= since - 2:
                break
        except OSError:
            pass
        if time.time() >= deadline:
            return ""                       # NX wrote none
        time.sleep(0.5)
    for attempt in range(20):
        try:
            os.remove(log_file)
            return ""
        except PermissionError:             # the translator still has it open
            time.sleep(0.5)
        except OSError:
            break
    return "; NX's translator log {0} could not be deleted".format(os.path.basename(log_file))


def main(argv):
    job_file = argv[1]
    with open(job_file, encoding="utf-8") as f:
        jobs = json.load(f)
    try:
        os.remove(job_file)
    except OSError:
        pass
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    print("{0}  cleaning up {1} DXF file(s)".format(started, len(jobs)), flush=True)
    return run_jobs(jobs, say=lambda line: print(line, flush=True))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
