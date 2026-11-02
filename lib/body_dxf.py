"""Export one DXF per solid body, viewed square-on to the body's largest flat face.

Used by NX-Scripts/Export-Body-DXF. For each solid body of the work part:

1. measure the area of every face,
2. take the largest PLANAR face (a curved face has no single normal, so it cannot give a
   "normal to face" view) and save a view looking straight at it, zoomed to fit, named
   DXF_<BODYNAME>,
3. export the body to DXF through that view with every edge shown,
4. name the file <partID>.<revision>-UNRELEASED.dxf in the repo's output/dxf/ folder, as Export-PDF
   and Export-STEP name theirs (with _<bodyname> added when the part has more than one solid body).

NX notes: views and DXF export have no feature Builder (views are saved with
ViewCollection.SaveAs, the exporter is a DexBuilder), so none of this appears in the feature tree.
"""
import math
import os
import re

import NXOpen
import NXOpen.UF          # NX only creates NXOpen.UF once it is imported explicitly

# DXFs get their own folder in output/, apart from the STEP files Export-STEP writes to output/step/
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "dxf")
SUFFIX = "UNRELEASED"                                # <partID>.<revision>-UNRELEASED.dxf; "" for none
VIEW_PREFIX = "DXF_"
_ID_ATTRIBUTES = ("DB_PART_NO", "DB_PART_REV")
_MAX_VIEW_NAME = 30                                  # NX view names are limited in length


# ----------------------------------------------------------------------------- names
def safe_name(text, upper=False, default="BODY"):
    """`text` with everything Windows (and NX view names) dislike turned into "_"."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text or "").strip()).strip("._")
    if upper:
        s = s.upper()
    return s or default


def part_id(part):
    """(part number, revision, note). Uses the DB_PART_NO / DB_PART_REV attributes; if one is
    missing it falls back to the part's Leaf name ("1150201-500/01") and says so in `note`."""
    found = {}
    try:
        for a in part.GetUserAttributes():
            key = a.Title.strip().upper()
            if key in _ID_ATTRIBUTES and key not in found:
                found[key] = str(a.StringValue).strip()
    except Exception:
        pass
    number, rev = found.get("DB_PART_NO"), found.get("DB_PART_REV")
    note = None
    if not number or not rev:
        leaf = str(getattr(part, "Leaf", "") or "")
        left, _sep, right = leaf.partition("/")
        number, rev = number or left or "PART", rev or right or "0"
        note = "DB_PART_NO/DB_PART_REV not both set; used the part name '{0}'".format(leaf)
    return number, rev, note


def body_name(body, index):
    try:
        name = body.Name or body.JournalIdentifier
    except Exception:
        name = None
    return name or "BODY_{0}".format(index)


def dxf_path(out_dir, number, rev, name, used, add_body_name=False):
    """out_dir/<number>.<rev>-UNRELEASED.dxf, with _<name> added if `add_body_name` (a part with more
    than one solid body); a name already used in this run gets _2, _3, ..."""
    stem = "{0}.{1}".format(safe_name(number, default="PART"), safe_name(rev, default="0"))
    if SUFFIX:
        stem += "-" + safe_name(SUFFIX)
    if add_body_name:
        stem += "_" + safe_name(name)
    candidate, n = stem, 1
    while candidate.lower() in used:
        n += 1
        candidate = "{0}_{1}".format(stem, n)
    used.add(candidate.lower())
    return os.path.join(out_dir, candidate + ".dxf")


# ----------------------------------------------------------------------------- faces
def measure_faces(session, body):
    """[(face, area, is_planar)] for every face of `body` (area in the part's base units)."""
    measurement = session.Measurement
    planar = NXOpen.Face.FaceType.Planar
    rows = []
    for face in body.GetFaces():
        area = measurement.GetFaceProperties([face], 0.99, NXOpen.Measurement.AlternateFace.Radius,
                                             False)[0]
        rows.append((face, float(area), face.SolidFaceType == planar))
    return rows


def pick_view_face(rows):
    """(largest face overall, largest planar face or None) from measure_faces rows."""
    if not rows:
        return None, None
    largest = max(rows, key=lambda r: r[1])
    planar = [r for r in rows if r[2]]
    return largest, (max(planar, key=lambda r: r[1]) if planar else None)


def face_outward_normal(face, body=None, part=None, session=None):
    """Outward unit normal (x, y, z) of a planar face.

    The direction comes from, in order: UF_MODL_ask_face_data (exact, outward; not every NX Python
    build has it); a temporary "dumb" Direction on the face (works for any planar face, including
    a round one, but its sign is not guaranteed); the face's own edge vertices (needs three that are
    not in a line, so not a round face). Unless UF gave the sign, the normal is then pointed away
    from the body's material: the side of the face's plane that most of the body's vertices are on
    is "inside". That is right for a face that bounds the body on one side (plates, blocks, discs,
    the big faces this script picks); a face whose plane cuts through the middle of the body could
    come out flipped.
    """
    try:
        ufs = NXOpen.UF.UFSession.GetUFSession()
        data = ufs.Modl.AskFaceData(face.Tag)
        direction, sense = data[2], data[6]
        v = [float(c) * (1 if sense >= 0 else -1) for c in direction]
        return _unit(tuple(v))
    except Exception:
        pass
    pts = _vertices(face.GetEdges())
    reasons = []
    axis = None
    if part is not None:
        axis, why = _direction_of_face(face, part, session)
        if why:
            reasons.append("temporary Direction: " + why)
    if axis is None:
        try:
            axis = _axis_from_vertices(pts)
        except RuntimeError as ex:
            reasons.append(str(ex))
    if axis is None and body is not None:
        axis = _axis_from_seam(face, body, pts)
        if axis is None:
            reasons.append("no body edge leaves the face's vertex")
    if axis is None:
        raise RuntimeError("cannot find the face normal ({0})".format("; ".join(reasons)))
    if body is not None and pts:
        inside = sum(_dot(_sub(p, pts[0]), axis) for p in _vertices(body.GetEdges()))
        if inside > 0:
            axis = tuple(-c for c in axis)
    return axis


def _direction_of_face(face, part, session):
    """(unit normal, None) of a planar face from a temporary dumb Direction (deleted again), or
    (None, why it did not work)."""
    direction = None
    try:
        direction = part.Directions.CreateDumbDirectionFace(
            face, NXOpen.Sense.Forward, NXOpen.SmartObject.UpdateOption.WithinModeling)
        v = direction.Vector
        axis = _unit((float(v.X), float(v.Y), float(v.Z)))
        return (axis, None) if _length(axis) > 0.5 else (None, "zero-length vector")
    except Exception as ex:
        return None, str(ex)
    finally:
        if direction is not None and session is not None:
            try:
                session.UpdateManager.AddObjectsToDeleteList([direction])
                session.UpdateManager.DoUpdate(session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible,
                                                                    "Delete temporary direction"))
            except Exception:
                pass


def _vertices(edges):
    pts = []
    for e in edges:
        for p in e.GetVertices():
            pts.append((float(p.X), float(p.Y), float(p.Z)))
    return pts


def _same_point(a, b, tol=1e-6):
    return _length(_sub(a, b)) <= tol


def _axis_from_seam(face, body, pts):
    """Normal of a round planar face (a disc: one vertex per circle edge, so no plane can be built
    from vertices). The body edge that leaves the face's vertex and is not one of the face's own
    edges is the seam of the cylinder the disc closes, which runs along the cylinder axis, i.e.
    along the disc's normal. Returns a unit vector or None."""
    if not pts:
        return None
    v = pts[0]
    own = {getattr(e, "Tag", id(e)) for e in face.GetEdges()}
    for e in body.GetEdges():
        if getattr(e, "Tag", id(e)) in own:
            continue
        a, b = e.GetVertices()
        a, b = (float(a.X), float(a.Y), float(a.Z)), (float(b.X), float(b.Y), float(b.Z))
        if _same_point(a, v):
            d = _sub(b, a)
        elif _same_point(b, v):
            d = _sub(a, b)
        else:
            continue
        if _length(d) > 1e-9:
            return _unit(d)
    return None


def _axis_from_vertices(pts):
    if len(pts) < 3:
        raise RuntimeError("cannot find the face normal (too few vertices on the face)")
    p0 = pts[0]
    p1 = max(pts, key=lambda p: _length(_sub(p, p0)))
    base = _sub(p1, p0)
    best, normal = 0.0, None
    for p in pts:
        c = _cross(base, _sub(p, p0))
        if _length(c) > best:
            best, normal = _length(c), c
    if normal is None or best < 1e-9:
        raise RuntimeError("cannot find the face normal (the face vertices are in a line)")
    return _unit(normal)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def view_axes(normal):
    """(x, y, z) unit axes of a view looking at a face: z = the outward normal (toward the viewer),
    x = horizontal, y = up. Z stays "up" in the picture for side faces; for faces looking along
    +-Z the world X axis is used."""
    z = normal
    up = (0.0, 0.0, 1.0)
    x = _cross(up, z)
    if _length(x) < 1e-6:                              # face looks along Z
        x = (1.0, 0.0, 0.0) if z[2] > 0 else (-1.0, 0.0, 0.0)
    x = _unit(x)
    y = _unit(_cross(z, x))
    return x, y, z


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _length(v):
    return math.sqrt(sum(c * c for c in v))


def _unit(v):
    n = _length(v) or 1.0
    return tuple(c / n for c in v)


# ----------------------------------------------------------------------------- views
def _view_names(part):
    names = {}
    try:
        for v in part.ModelingViews:
            names[v.Name.upper()] = v
    except Exception:
        pass
    return names


def create_face_view(session, part, face_normal, name):
    """Orient the work view square-on to the face, fit it, save it as view `name` and return the
    name actually used (a view already called `name` is deleted first; if NX will not delete it a
    numbered name is used instead)."""
    x, y, z = view_axes(face_normal)
    m = NXOpen.Matrix3x3()
    m.Xx, m.Xy, m.Xz = x
    m.Yx, m.Yy, m.Yz = y
    m.Zx, m.Zy, m.Zz = z
    work = part.ModelingViews.WorkView
    work.Orient(m)
    work.Fit()
    try:
        # every edge visible: plain wireframe, no hidden-line removal
        work.RenderingStyle = NXOpen.View.RenderingStyleType.StaticWireframe
    except Exception:
        pass

    existing = _view_names(part)
    final = name
    if final.upper() in existing:
        try:
            session.UpdateManager.AddObjectsToDeleteList([existing[final.upper()]])
            session.UpdateManager.DoUpdate(session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible,
                                                                "Replace DXF view"))
            existing = _view_names(part)
        except Exception:
            pass
        n = 1
        while final.upper() in existing:
            n += 1
            final = "{0}_{1}".format(name[:_MAX_VIEW_NAME - 3], n)
    # as recorded in example_journals/journal_face_normal.py; True copies the wireframe style to the saved view
    part.Views.SaveAsPreservingCase(work, final, True, False)
    return final


# ----------------------------------------------------------------------------- export
def _input_file(part):
    """The exporter's InputFile: "@DB/<number>/<rev>" for a Teamcenter part (as in the recorded
    example_journals/journal_export_dxf.py), otherwise the part's file path."""
    leaf = str(getattr(part, "Leaf", "") or "")
    return "@DB/" + leaf if "/" in leaf else str(getattr(part, "FullPath", leaf))


def export_dxf(session, part, body, view_name, path):
    """Export `body` as 2D DXF through the saved view `view_name` (all edges), to `path`."""
    creator = session.DexManager.CreateDxfdwgCreator()
    try:
        # settings the recorded File > Export > AutoCAD DXF/DWG journal sets
        creator.AutoCADRevision = NXOpen.DxfdwgCreator.AutoCADRevisionOptions.R2004
        creator.FlattenAssembly = False
        creator.ExportScaleValue = 1.0
        creator.InputFile = _input_file(part)
        creator.ExportDestination = NXOpen.BaseCreator.ExportDestinationOption.NativeFileSystem
        creator.ExportFrom = NXOpen.DxfdwgCreator.ExportFromOption.DisplayPart
        creator.ExportData = NXOpen.DxfdwgCreator.ExportDataOption.Modeling
        creator.ExportAs = NXOpen.DxfdwgCreator.ExportAsOption.TwoD
        creator.OutputTo = NXOpen.DxfdwgCreator.OutputToOption.Modeling
        creator.OutputFileType = NXOpen.DxfdwgCreator.OutputFileTypeOption.Dxf
        creator.FileSaveFlag = False
        creator.ViewList = '"{0}"'.format(view_name)      # the journal quotes view names: "Top"
        creator.ExportSelectionBlock.SelectionScope = NXOpen.ObjectSelector.Scope.SelectedObjects
        creator.ExportSelectionBlock.SelectionComp.Add(body)          # one object per call, as recorded
        creator.ObjectTypes.Curves = True
        creator.ObjectTypes.Annotations = True
        creator.ObjectTypes.Structures = True
        creator.LayerMask = "1-256"
        creator.WidthFactorMode = NXOpen.DxfdwgCreator.WidthfactorMethodOptions.AutomaticCalculation
        creator.OutputFile = path
        creator.Commit()
    finally:
        creator.Destroy()


# ----------------------------------------------------------------------------- the run
def export_part_bodies(session, part, out_dir=None, log=None):
    """Export a DXF for every solid body of `part` (the work/displayed part).

    Returns a dict: exported [(body name, view name, path)], skipped [(body name, why)],
    failures [(body name, reason)], out_dir, note (about how the part ID was built, or None).
    `log(line)` receives progress lines (the Listing Window).
    """
    log = log or (lambda line: None)
    out_dir = out_dir or OUTPUT_DIR
    result = {"exported": [], "skipped": [], "failures": [], "out_dir": out_dir, "note": None}

    number, rev, result["note"] = part_id(part)
    if result["note"]:
        log("Note: " + result["note"])
    bodies = [b for b in part.Bodies]
    solids = [b for b in bodies if getattr(b, "IsSolidBody", False)]
    for b in bodies:
        if b not in solids:
            result["skipped"].append((body_name(b, 0), "not a solid body"))
    if not solids:
        log("'{0}' has no solid bodies. Nothing to export.".format(part.Leaf))
        return result
    os.makedirs(out_dir, exist_ok=True)

    used = set()
    work_view = part.ModelingViews.WorkView
    original_state = _view_state(work_view)           # the views below are made wireframe; put it back after
    try:
        for index, body in enumerate(solids, 1):
            name = body_name(body, index)
            mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Export DXF " + name)
            try:
                rows = measure_faces(session, body)
                largest, planar = pick_view_face(rows)
                if largest is None:
                    raise RuntimeError("the body has no faces")
                if planar is None:
                    result["skipped"].append((name, "no planar face to look at"))
                    log("{0}: skipped, no planar face.".format(name))
                    _rollback(session, mark)
                    continue
                substituted = planar is not largest
                normal = face_outward_normal(planar[0], body, part, session)
                view = create_face_view(session, part, normal,
                                        (VIEW_PREFIX + safe_name(name, upper=True))[:_MAX_VIEW_NAME])
                path = dxf_path(out_dir, number, rev, name, used, add_body_name=len(solids) > 1)
                export_dxf(session, part, body, view, path)
                result["exported"].append((name, view, path))
                log("{0}: {1}  (view {2}, face area {3:.3f}{4})".format(
                    name, path, view, planar[1],
                    ", largest face is curved ({0:.3f}); used the largest flat face".format(largest[1])
                    if substituted else ""))
            except Exception as ex:
                result["failures"].append((name, str(ex)))
                log("{0}: FAILED, {1}".format(name, ex))
                _rollback(session, mark)
    finally:
        # Saving a view can make the saved copy the displayed work view, so restore whichever
        # view is the work view now as well as the one we started in.
        _restore_view_state(work_view, original_state)
        try:
            current = part.ModelingViews.WorkView
        except Exception:
            current = None
        if current is not None and current is not work_view:
            _restore_view_state(current, original_state)
    return result


def _view_state(view):
    """(rendering style, shaded display type) of a view; either may be None if unreadable."""
    state = []
    for attr in ("RenderingStyle", "ShadedDisplayType"):
        try:
            state.append(getattr(view, attr))
        except Exception:
            state.append(None)
    return tuple(state)


def _restore_view_state(view, state):
    """Put a view back in the display style it had before the export (not wireframe): the rendering
    style, then Shaded Type (the recorded journal_SOLID_DISPLAY.py sets ShadedDisplayType)."""
    style, shaded = state
    for attr, value in (("RenderingStyle", style), ("ShadedDisplayType", shaded)):
        if value is None:
            continue
        try:
            setattr(view, attr, value)
        except Exception:
            pass
    try:
        view.UpdateDisplay()
    except Exception:
        pass


def _rollback(session, mark):
    """Undo whatever a body that did not export changed (its view), and drop the mark.
    A body that exported keeps its mark, so Edit > Undo takes its view back."""
    try:
        session.UndoToMark(mark, None)
        session.DeleteUndoMark(mark, None)
    except Exception:
        pass
