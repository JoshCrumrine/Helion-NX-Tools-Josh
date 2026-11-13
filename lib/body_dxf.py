"""Export one DXF per solid body, viewed square-on to the body's largest flat face.

Used by NX-Scripts/Export-Body-DXF. For each solid body of the work part:

1. measure the area of every face,
2. take the largest PLANAR face (a curved face has no single normal, so it cannot give a
   "normal to face" view) and save a view looking straight at it, zoomed to fit, named
   DXF_<BODYNAME>,
3. export the body to DXF through that view with every edge shown,
4. name the file <partID>.<revision>-UNRELEASED.dxf in the repo's output/dxf/ folder, as Export-PDF
   and Export-STEP name theirs (with _<bodyname> added when the part has more than one solid body),
5. clean the file up: each line and arc once (the top and bottom of a plate land on top of each
   other in the view, so NX writes every one twice), and no zero-length lines.

NX writes a DXF in the background: Commit hands it to a translator program, which takes about 40 s
(seen 2026-11-11). So the old file of that name is deleted first, and the clean-up runs afterwards
as a separate process, lib/dxf_cleanup.py in the repo's .venv Python, which waits for each file. NX
is free meanwhile. The clean-up writes what it did to helion_dxf_cleanup.log in the Windows temp
folder and deletes the translator's own <name>.log, so output/dxf holds only the DXFs.

Sheet metal: a sheet metal part gets one DXF, of its Flat Solid only. A hidden Flat Solid is shown
for the export, as NX leaves hidden objects out of a DXF, and hidden again. The DXF has no
bend lines: a flattened body keeps each bend region as a face of its own, in the plane of the flanges,
so the bend lines are the edges where two flat faces meet in one plane; they are found in NX and
taken out of the DXF. A sheet metal part without a Flat Solid gets a temporary one (make_flat_solid),
undone after the export: its formed body would come out as a side view, and a Flat Pattern gives an
empty DXF, through its own hidden flat body (even shown) and through NX's Export Flat Pattern alike
(2026-11-11).

NX notes: views and DXF export have no feature Builder (views are saved with
ViewCollection.SaveAs, the exporter is a DexBuilder), so none of this appears in the feature tree.
"""
import contextlib
import json
import math
import os
import re
import subprocess
import tempfile
import time

import NXOpen
import NXOpen.Features    # FlatSolid and FlatPattern, to recognize sheet metal parts
import NXOpen.UF          # NX only creates NXOpen.UF once it is imported explicitly

from lib.mcmaster import scraper_python     # the repo's .venv Python, which runs the clean-up

# DXFs get their own folder in output/, apart from the STEP files Export-STEP writes to output/step/
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "dxf")
CLEANUP_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dxf_cleanup.py")
CLEANUP_LOG = os.path.join(tempfile.gettempdir(), "helion_dxf_cleanup.log")   # rewritten by every run
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


# ----------------------------------------------------------------------------- sheet metal
def _syslog(line):
    """Write `line` to NX's log file (Help > Log File), to see later what the tool found."""
    try:
        NXOpen.Session.GetSession().LogFile.WriteLine("[Export DXF] " + line)
    except Exception:
        pass


def _attr(obj, name):
    try:
        return getattr(obj, name)
    except Exception:
        return None


def _flat_kind(*names):
    """"solid" or "pattern" when one of `names` (feature types, journal identifiers, body names) says
    Flat Solid or Flat Pattern, with or without spaces and underscores; None otherwise."""
    for name in names:
        letters = re.sub(r"[^A-Z]", "", str(name or "").upper())
        if "FLATSOLID" in letters:
            return "solid"
        if "FLATPATTERN" in letters:
            return "pattern"
    return None


def feature_kind(feature):
    """"solid" for a Flat Solid feature, "pattern" for a Flat Pattern, None for any other feature.

    The feature's name decides first: a Flat Pattern makes features of its own, among them a Flat Solid
    (FLAT_PATTERN(20:1B), class FlatSolid, type SB_FLAT_SOLID), whose body exports empty (seen
    2026-11-11). Those belong to the Flat Pattern, whatever their class.
    """
    named = _flat_kind(_attr(feature, "JournalIdentifier"))
    if named:
        return named
    for class_name, kind in (("FlatSolid", "solid"), ("FlatPattern", "pattern")):
        cls = getattr(NXOpen.Features, class_name, None)
        if cls is not None and isinstance(feature, cls):
            return kind
    return _flat_kind(_attr(feature, "FeatureType"))


def _is_sheet_metal_feature(feature, kind):
    """Whether `feature` (of flat `kind`, see feature_kind) is a sheet metal feature: a Flat Solid or Flat
    Pattern, or one whose type or name starts with SB_ (SB Convert To Sheet Metal, SB Flange, ...)."""
    names = (_attr(feature, "FeatureType"), _attr(feature, "JournalIdentifier"))
    return kind is not None or any(str(n or "").upper().startswith("SB_") for n in names)


def _add_bodies(feature, bodies):
    """Add the solid bodies `feature` made (none if it is suppressed) to `bodies`, once each."""
    try:
        made = [] if feature.Suppressed else feature.GetBodies()
    except Exception as ex:
        made = []
        _syslog("  its bodies could not be read: {0}".format(ex))
    for body in made:
        if getattr(body, "IsSolidBody", False) and all(body.Tag != b.Tag for b in bodies):
            bodies.append(body)


def sheet_metal_flats(part, solids=()):
    """(flats, pattern flats, sheet metal) of `part`:

    * flats: the solid bodies of its own Flat Solid features (not suppressed);
    * pattern flats: the flattened bodies of its Flat Patterns. A Flat Pattern makes a Flat Solid of its
      own (FLAT_PATTERN(8:1B), class FlatSolid), whose body NX keeps hidden;
    * sheet metal: whether it is a sheet metal part at all (see _is_sheet_metal_feature).

    When the features give no flat, the bodies in `solids` named after a Flat Solid feature count
    instead: NX names a body after the feature that made it ("SB_FLAT_SOLID(21:1B)"). The features go to
    NX's log file (all of them in a part of up to 100 features, else the sheet metal ones).
    """
    flats, pattern_flats, sheet_metal = [], [], False
    try:
        features = list(part.Features)
    except Exception as ex:
        features = []
        _syslog("could not list the features: {0}".format(ex))
    for feature in features:
        kind = feature_kind(feature)
        is_sheet_metal = _is_sheet_metal_feature(feature, kind)
        sheet_metal = sheet_metal or is_sheet_metal
        if is_sheet_metal or len(features) <= 100:
            _syslog("feature {0}: {1}, FeatureType {2}{3}".format(
                _attr(feature, "JournalIdentifier"), type(feature).__name__,
                _attr(feature, "FeatureType"), ": " + kind if kind else ""))
        if kind == "solid":
            _add_bodies(feature, flats)
        elif kind == "pattern" and "FLATSOLID" in re.sub(r"[^A-Z]", "", "{0} {1}".format(
                type(feature).__name__, _attr(feature, "FeatureType")).upper()):
            _add_bodies(feature, pattern_flats)
    if not flats:
        for body in solids:
            kind = _flat_kind(_attr(body, "JournalIdentifier"), _attr(body, "Name"))
            if kind == "solid":
                flats.append(body)
            if kind:
                sheet_metal = True
                _syslog("body {0}: {1}, by its name".format(_attr(body, "JournalIdentifier"), kind))
    _syslog("{0} features; Flat Solid bodies: {1}; Flat Pattern bodies: {2}; sheet metal: {3}".format(
        len(features), len(flats), len(pattern_flats), sheet_metal))
    return flats, pattern_flats, sheet_metal


def formed_body(part, solids):
    """The bent sheet metal body of `part` to flatten, from `solids`: the body its sheet metal features
    (SB Convert To Sheet Metal, SB Flange, ...) belong to, else the one solid not named after a Flat
    Solid or Flat Pattern. None when it cannot be told."""
    candidates = [b for b in solids if not _flat_kind(_attr(b, "JournalIdentifier"), _attr(b, "Name"))]
    tags = {b.Tag for b in candidates}
    try:
        features = list(part.Features)
    except Exception:
        features = []
    for feature in features:
        if feature_kind(feature) is None and _is_sheet_metal_feature(feature, None):
            found = []
            _add_bodies(feature, found)
            for body in found:
                if body.Tag in tags:
                    return body
    return candidates[0] if len(candidates) == 1 else None


def make_flat_solid(session, part, body):
    """Add a Flat Solid of the sheet metal `body`, as Sheet Metal > Flat Solid does (recorded in
    example_journals/journal_flat_solid.py), and return its flat body.

    The stationary face is the body's largest flat face: always on a flange, never a bend or an edge
    face. Which flange it is only moves the flat body in space (or mirrors it, for a face on the other
    side of the sheet); the outline is the same. Layer, color and corner treatments come from the sheet
    metal preferences, as in the dialog. If NX will not build it outside the Sheet Metal application,
    it switches there for the build and back after.
    """
    # Reached through NXOpen.Features, as in the journal: NX's NXOpen.Features is not a package, so
    # "import NXOpen.Features.SheetMetal" fails (seen 2026-11-11).
    sheet_metal = NXOpen.Features.SheetMetal
    _largest, planar = pick_view_face(measure_faces(session, body))
    if planar is None:
        raise RuntimeError("the bent body has no flat face to flatten about")

    def build():
        manager = part.Features.SheetmetalManager
        builder = manager.CreateFlatSolidFeatureBuilder(NXOpen.Features.Feature.Null)
        try:
            builder.SetApplicationContext(sheet_metal.ApplicationContext.NxSheetMetal)
            builder.LayerSetting = sheet_metal.FlatSolidBuilder.LayerSettingOption.Preference
            builder.FixAtTimestamp = True
            preferences = part.Preferences.SheetMetalPreferences
            corners = (
                (builder.InnerCornerTreatment, preferences.GetFlatPatternInsideCornerTreatmentValue()),
                (builder.OuterCornerTreatment, preferences.GetFlatPatternOutsideCornerTreatmentValue()))
            for treatment, preference in corners:
                treatment.TreatmentType = sheet_metal.CornerTreatmentBuilder.CornerTreatmentType.NotSet
                treatment.Value.RightHandSide = preference.Name
            builder.StationaryFace.Value = planar[0]
            for treatment, preference in corners:
                treatment.Value.SetFormula(preference.Name)
            return builder.CommitFeature()
        finally:
            builder.Destroy()

    try:
        feature = build()
    except Exception as ex:
        application = session.ApplicationName
        if application == "UG_APP_SBSM":
            raise
        _syslog("Flat Solid not built in {0} ({1}); trying in Sheet Metal".format(application, ex))
        session.ApplicationSwitchImmediate("UG_APP_SBSM")
        try:
            feature = build()
        finally:
            session.ApplicationSwitchImmediate(application)
    flats = []
    _add_bodies(feature, flats)
    if not flats:
        raise RuntimeError("the Flat Solid made no body")
    return flats[0]


def bend_lines(body, normal):
    """[(start, end)] of the bend lines of a flat solid seen along `normal`: its straight edges between
    two flat faces that both face the viewer, so lie in one plane (a flattened bend region is a face of
    its own, in the plane of the flanges). The bottom's copies are included; they land on the top's."""
    facing = {}

    def faces_viewer(face):
        if face.Tag not in facing:
            try:
                ok = face.SolidFaceType == NXOpen.Face.FaceType.Planar
                if ok:
                    ok = abs(_dot(_axis_from_vertices(_vertices(face.GetEdges())), normal)) > 1 - 1e-6
            except Exception:
                ok = False
            facing[face.Tag] = ok
        return facing[face.Tag]

    lines = []
    for edge in body.GetEdges():
        try:
            if edge.SolidEdgeType != NXOpen.Edge.EdgeType.Linear:
                continue
            faces = edge.GetFaces()
            if len(faces) == 2 and all(faces_viewer(f) for f in faces):
                a, b = edge.GetVertices()
                lines.append(tuple((float(v.X), float(v.Y), float(v.Z)) for v in (a, b)))
        except Exception:
            continue
    return lines


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

    # Sheet metal: only the Flat Solid, without bend lines. A sheet metal part without one gets a
    # temporary Flat Solid, removed again (undone) after the export: its formed body would come out as a
    # side view, and a Flat Pattern gives an empty DXF, as NX's 2D step finds nothing to draw in its own
    # flat body even when shown (seen 2026-11-11).
    flats, _pattern_flats, sheet_metal = sheet_metal_flats(part, solids)
    temporary = None
    if not flats and sheet_metal:
        formed = formed_body(part, solids)
        temporary = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible,
                                        "Export DXF temporary Flat Solid")
        try:
            if formed is None:
                raise RuntimeError("its bent body could not be told apart from its other bodies")
            flats = [make_flat_solid(session, part, formed)]
        except Exception as ex:
            _rollback(session, temporary)
            why = ("sheet metal without a Flat Solid, and a temporary one could not be made ({0}): add "
                   "Sheet Metal > Flat Solid and run Export DXF again".format(ex))
            log("Nothing exported: '{0}' is {1}.".format(part.Leaf, why))
            result["skipped"].extend((body_name(b, 0), why) for b in solids)
            return result
        log("Sheet metal part without a Flat Solid: made a temporary one, removed again after the "
            "export.")
    flat_tags = {b.Tag for b in flats}
    if flats:
        log("Sheet metal part: exporting its Flat Solid only, without bend lines.")
        for b in solids:
            if b.Tag not in flat_tags:
                result["skipped"].append((body_name(b, 0),
                                           "sheet metal: only the Flat Solid is exported"))
        solids = flats

    if not solids:
        log("'{0}' has no solid bodies. Nothing to export.".format(part.Leaf))
        return result
    os.makedirs(out_dir, exist_ok=True)

    used, jobs = set(), []
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
                started = _clear_old_output(path)
                with _shown(session, body):
                    export_dxf(session, part, body, view, path)
                result["exported"].append((name, view, path))
                log("{0}: {1}  (view {2}, face area {3:.3f}{4})".format(
                    name, path, view, planar[1],
                    ", largest face is curved ({0:.3f}); used the largest flat face".format(largest[1])
                    if substituted else ""))
                jobs.append(cleanup_job(path, started, body, normal, body.Tag in flat_tags))
            except Exception as ex:
                result["failures"].append((name, str(ex)))
                log("{0}: FAILED, {1}".format(name, ex))
                _rollback(session, mark)
    finally:
        # The temporary Flat Solid, and the view saved for it, go again. The DXF is not affected: the
        # export took a copy of the part when it started.
        if temporary is not None:
            _rollback(session, temporary)
        # Saving a view can make the saved copy the displayed work view, so restore whichever
        # view is the work view now as well as the one we started in.
        _restore_view_state(work_view, original_state)
        try:
            current = part.ModelingViews.WorkView
        except Exception:
            current = None
        if current is not None and current is not work_view:
            _restore_view_state(current, original_state)
    if jobs:
        log(start_cleanup(jobs))
    return result


@contextlib.contextmanager
def _shown(session, body):
    """Show `body` while the block runs if it is hidden, then hide it again. The exporter leaves hidden
    objects out, so a hidden Flat Solid gave an empty DXF; shown this way it exports right (both seen
    2026-11-11). Commit copies the part for the translator, so hiding it again straight after does not
    change the DXF."""
    hidden = bool(_attr(body, "IsBlanked"))
    if hidden:
        session.DisplayManager.UnblankObjects([body])
    try:
        yield
    finally:
        if hidden:
            try:
                session.DisplayManager.BlankObjects([body])
            except Exception as ex:
                _syslog("could not hide {0} again: {1}".format(_attr(body, "JournalIdentifier"), ex))


# ----------------------------------------------------------------------------- clean-up
def _clear_old_output(path):
    """Delete an older DXF of this name and its translator log, so the clean-up cannot take the old
    file for the new one (and the translator does not keep it as <name>_bk.dxf). Returns the time."""
    for old in (path, os.path.splitext(path)[0] + ".log"):
        try:
            os.remove(old)
        except OSError:
            pass
    return time.time()


def cleanup_job(path, started, body, normal, flat):
    """What lib/dxf_cleanup.py needs for the DXF at `path` of `body`, seen along `normal`: its bend lines
    and corners if it is a `flat` solid (see bend_lines and dxf_cleanup.clean_dxf)."""
    job = {"dxf": path, "since": started, "flat": flat}
    if flat:
        try:
            bends = bend_lines(body, normal)
            x_axis, y_axis, _z = view_axes(normal)
            job.update(axes=[x_axis, y_axis], bends=bends,
                       points=_vertices(body.GetEdges()) if bends else [])
        except Exception as ex:                     # the DXF is still cleaned up, without the bend lines
            _syslog("could not find the bend lines of {0}: {1}".format(os.path.basename(path), ex))
    return job


def start_cleanup(jobs):
    """Start lib/dxf_cleanup.py on `jobs` in the background (NX writes the DXFs over the next ~40 s) and
    return a line for the Listing Window saying so, or why it could not start. What it does goes to
    CLEANUP_LOG, in the Windows temp folder, so the output folder holds only the DXFs."""
    try:
        handle, job_file = tempfile.mkstemp(prefix="dxf_cleanup_", suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            json.dump(jobs, f)
        with open(CLEANUP_LOG, "w", encoding="utf-8") as out:
            subprocess.Popen([scraper_python(), "-I", CLEANUP_SCRIPT, job_file],
                             stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as ex:
        return ("Could not start the clean-up ({0}), so the DXFs keep their doubled lines and bend "
                "lines.".format(ex))
    return ("NX writes the DXFs in the background (about 40 s). They are then cleaned up (doubled "
            "lines{0} removed); what was done goes to {1}".format(
                ", bend lines" if any(job["flat"] for job in jobs) else "", CLEANUP_LOG))


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
