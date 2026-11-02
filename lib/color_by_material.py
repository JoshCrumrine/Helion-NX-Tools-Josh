"""Color the bodies of the displayed assembly by NX physical material.

Shared implementation behind NX-Scripts/Color-By-Material/*. Bodies with no
material get NO_MATERIAL_COLOR. Other styles come from
Materials/NX_Materials.csv: the "color" column (hex code, or NX color ID 1-216) and the "Transparency"
column (0 = opaque .. 100 = fully clear). See that folder's README for behavior,
caveats and the Listing Window output.
"""
import csv
import os

import NXOpen

from lib.assemblies import (assign_material, find_display_body, get_bodies, get_body_material,
                            update_mass_properties, walk_components)
from lib.colors import clear_component_color_override, color_number_from, set_body_color
from lib.nx_dialogs import UserCancelled, choose_from_list

# Bodies with no material assigned get this color (set to None to leave them alone).
NO_MATERIAL_COLOR = "#ff00ff"

# Folder holding the site's MatML material libraries (the files NX_Materials.csv was built
# from: its "source_file" column). Matches the site customer default
# "Gateway > Materials/Mass > Locations > Site MatML Library" (UG_SiteMatMlLibrary_WIN).
# Change it if the libraries move.
MATERIAL_LIBRARY_DIR = (r"\\usantpvwtcor001\NXStore\NX_PROD_CUSTOM\NXcustom"
                        r"\NXcommonlibrary\Materials")

MATERIALS_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Materials", "NX_Materials.csv")


def _load_material_styles():
    """{lower-cased material name: (hex or None, translucency or None)} for CSV
    rows that have a "color" and/or a "Transparency" value. Column names are
    matched case-insensitively. A bad Transparency value is ignored."""
    styles = {}
    with open(MATERIALS_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            hex_code = row.get("color") or None
            translucency = None
            raw = row.get("transparency", "")
            if raw:
                try:
                    translucency = max(0, min(100, int(round(float(raw)))))
                except ValueError:
                    translucency = None
            if hex_code or translucency is not None:
                styles[row["name"].lower()] = (hex_code, translucency)
    return styles


def _load_material_names():
    """Material names from NX_Materials.csv (the Helion material library), sorted,
    for the "pick a material" dialog."""
    names = []
    with open(MATERIALS_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            if row.get("name"):
                names.append(row["name"])
    return sorted(set(names), key=str.lower)


def _load_material_libraries():
    """{lower-cased material name: [MatML file to load it from]} using the CSV's
    "source_file" column, so a gas or liquid material is loaded from the gas/liquid
    library and the rest from the main Helion library. Each material gets the full
    path first and the bare file name second (NX resolves a bare name against its site
    and user MatML libraries)."""
    libraries = {}
    with open(MATERIALS_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            name, source = row.get("name"), row.get("source_file")
            if name and source:
                libraries[name.lower()] = [os.path.join(MATERIAL_LIBRARY_DIR, source), source]
    return libraries


# Public names, for other modules (lib/part_materials.py).
load_material_names = _load_material_names
load_material_libraries = _load_material_libraries
load_material_styles = _load_material_styles


_bad_colors = set()      # color cells that were neither hex nor an NX ID (reported once)


def _color_number(value, part):
    """NX color number for a hex code or NX color ID, or None (blank or invalid;
    invalid values are remembered and reported at the end)."""
    try:
        return color_number_from(value, part)
    except ValueError:
        _bad_colors.add(value)
        return None


def _report_bad_colors(lw):
    if _bad_colors:
        lw.WriteLine("")
        lw.WriteLine("Ignored color values that are neither a hex code nor an NX color ID (1-216):")
        for value in sorted(_bad_colors):
            lw.WriteLine("  {0!r}".format(value))


def _resolve_style(material, material_styles):
    """(style, label) for a body's material name. style is (hex, translucency) or
    None when the body should be left alone; label is what the listing shows."""
    if material:
        return material_styles.get(material.lower()), material
    if NO_MATERIAL_COLOR:
        return (NO_MATERIAL_COLOR, None), "(no material)"
    return None, "(none)"


def _body_name(body):
    try:
        return body.Name or body.JournalIdentifier
    except Exception:
        return "?"


def _highlight(obj):
    """Highlight `obj` in the graphics window (no-op for None; never raises)."""
    if obj is not None:
        try:
            obj.Highlight()
        except Exception:
            pass


def _unhighlight(obj):
    if obj is not None:
        try:
            obj.Unhighlight()
        except Exception:
            pass


def _assign_missing_materials(session, display_part, proto, comp, names, dialog,
                              state, assigned, failures, libraries=None, mass_updates=None):
    """Ask for, and assign, a material for every body of `proto` that has none.

    One dialog per body. Cancel (or OK with nothing selected) skips that body; the
    dialog's "stop asking" toggle sets state["skip_all"] so no further prompts are
    shown. Assigned bodies are appended to `assigned` as (part, body, material),
    problems to `failures` as (part, body, material, reason). The caller then reads
    each body's material again, so a body that was assigned simply gets that
    material's color, and one that was not falls back to the no-material color.

    If any body got a material, the part's mass properties are then updated (as Assign
    Material does) so its weight uses the new densities; (part, ok, why) is appended to
    `mass_updates`.

    Assigning needs the owning part to be the work part, so it is made the work part
    for the duration and the displayed part is restored afterwards.
    """
    missing = [b for b in proto.Bodies if get_body_material(b) is None]
    if not missing or state["skip_all"] or state["cancelled"]:
        return
    assigned_before = len(assigned)
    try:
        if comp is not None:
            session.Parts.SetWorkComponent(comp)
        for body in missing:
            if state["skip_all"] or state["cancelled"]:
                break
            body_name = _body_name(body)
            # Highlight this body in the display so the user can see which one the
            # dialog is asking about. The displayed object is the occurrence of the
            # body (or the body itself, for the active part). No zoom: the view is
            # left alone. Always un-highlighted again in the finally below.
            shown = find_display_body(comp, body)
            hidden = ""
            try:
                if shown is not None and shown.IsBlanked:
                    hidden = " (this body is hidden)"
            except Exception:
                pass
            heading = "{0} / {1}{2}: no material. Pick one:".format(proto.Leaf, body_name, hidden)
            try:
                _highlight(shown)
                chosen, skip = choose_from_list(
                    dialog, "materialList", names, heading=heading,
                    heading_id="heading", skip_id="skipAll", search_id="searchBox",
                    cancel_id="cancelAll",
                    on_shown=lambda shown=shown: _highlight(shown))
            except UserCancelled:
                state["cancelled"] = True        # stop the whole run; what is done stays done
                break
            except Exception as ex:
                failures.append((proto.Leaf, body_name, "(dialog)",
                                 "could not show the material dialog: {0}".format(ex)))
                state["skip_all"] = True
                break
            finally:
                _unhighlight(shown)
            if skip:
                state["skip_all"] = True
            if not chosen:
                continue
            ok, why = assign_material(proto, body, chosen,
                                      (libraries or {}).get(chosen.lower(), ()))
            if ok:
                assigned.append((proto.Leaf, body_name, chosen))
            else:
                failures.append((proto.Leaf, body_name, chosen, why))
        if len(assigned) > assigned_before:       # also after a cancel: what was assigned stays
            ok, why = update_mass_properties(proto)
            if mass_updates is not None:
                mass_updates.append((proto.Leaf, ok, why))
    except Exception as ex:
        failures.append((proto.Leaf, "(part)", "",
                         "could not make it the work part: {0}".format(ex)))
    finally:
        session.Parts.SetWork(display_part)


def _update_holding_assemblies(session, display_part, changed, mass_updates):
    """Update the mass properties of every assembly that holds a part in `changed` (full paths of
    the parts that got new materials), so the assemblies' weights add up the new part weights:
    subassemblies deepest first, each made the work part while it is updated, then the displayed
    part. Appends (part, ok, why) to `mass_updates`."""
    holders = {}         # full path -> (depth, subassembly part, one of its components)
    for comp, depth in walk_components():
        try:
            if comp.IsSuppressed or comp.Prototype is None or comp.Prototype.FullPath not in changed:
                continue
            parent = comp.Parent
            while parent is not None and depth > 1:     # depth 0 is the displayed part: done last
                depth -= 1
                key = parent.Prototype.FullPath
                if key not in holders or holders[key][0] < depth:
                    holders[key] = (depth, parent.Prototype, parent)
                parent = parent.Parent
        except Exception:
            continue
    for _depth, part, comp in sorted(holders.values(), key=lambda h: -h[0]):
        try:
            session.Parts.SetWorkComponent(comp)
            ok, why = update_mass_properties(part)
        except Exception as ex:
            ok, why = False, "could not make it the work part: {0}".format(ex)
        finally:
            session.Parts.SetWork(display_part)
        mass_updates.append((part.Leaf, ok, why))
    if changed - {display_part.FullPath}:               # it holds changed components
        ok, why = update_mass_properties(display_part)
        mass_updates.append((display_part.Leaf, ok, why))


def run(clear_overrides, assign_missing=False, material_dialog=None):
    """Color every body in the displayed assembly by material.

    clear_overrides: also clear the assembly-level color override on every
    component first (so part colors are visible).

    assign_missing: when a body has no material, prompt for one from the material
    library (the BlockStyler dialog file `material_dialog`), assign it, and then
    color the body with that material's color. The mass properties of each part that
    got a material are then updated, and those of the assemblies holding it, so the
    weights use the new materials. This MODIFIES the parts (the material assignment,
    like the coloring, is not saved).
    """
    session = NXOpen.Session.GetSession()
    lw = session.ListingWindow
    lw.Open()
    _bad_colors.clear()

    display_part = session.Parts.Display
    if display_part is None:
        lw.WriteLine("No displayed part.")
        return

    material_styles = _load_material_styles()
    lw.WriteLine("{0} materials have a color and/or transparency in {1}".format(
        len(material_styles), MATERIALS_CSV))

    material_names = []
    material_libraries = {}
    if assign_missing:
        if not material_dialog or not os.path.isfile(material_dialog):
            lw.WriteLine("Cannot prompt for materials: dialog file not found: {0}".format(
                material_dialog))
            return
        material_names = _load_material_names()
        material_libraries = _load_material_libraries()
        lw.WriteLine("Bodies with no material will prompt for one of {0} library materials.".format(
            len(material_names)))
        lw.WriteLine("Materials are loaded from the MatML libraries in {0}".format(
            MATERIAL_LIBRARY_DIR))
    state = {"skip_all": False, "cancelled": False}
    assigned = []         # (part, body, material) assigned from the prompt
    assign_failures = []  # (part, body, material, reason)
    changed = set()       # full paths of the parts that got a material from the prompt
    mass_updates = []     # (part, ok, why) for each part whose mass properties were updated

    # One entry per distinct part: first component using it, and how many
    # instances there are.
    parts = {}           # part full path -> [part, first component, instances]
    # The displayed (active) part itself comes first: its own bodies count too, not
    # just those of its child components. It has no component (None) and is already
    # the work part, so nothing needs switching for it.
    parts[display_part.FullPath] = [display_part, None, 1]
    for comp, _depth in walk_components():
        try:
            proto = comp.Prototype
            if proto is None or comp.IsSuppressed:
                continue
            key = proto.FullPath
        except Exception:
            continue
        if key in parts:
            parts[key][2] += 1
        else:
            parts[key] = [proto, comp, 1]

    lw.WriteLine("{0} distinct parts in the assembly".format(len(parts)))
    if clear_overrides:
        n = clear_component_color_override([c for c, _d in walk_components()], display_part)
        lw.WriteLine("Cleared assembly color override on {0} components".format(n))
    lw.WriteLine("")
    lw.WriteLine("Bodies changed (part / body -> material, NX color, transparency):")
    if NO_MATERIAL_COLOR:
        lw.WriteLine("(bodies with no material get {0})".format(NO_MATERIAL_COLOR))

    n_bodies = 0
    n_parts = 0
    unchanged = {}       # material (or "(none)") -> count
    skipped = []         # (part, reason) -- parts that could not be changed
    read_only = []       # part names that were changed but are read-only
    not_processed = 0    # parts never reached because the user cancelled
    for proto, comp, instances in parts.values():
        if state["cancelled"]:
            not_processed += 1
            continue
        if assign_missing and not state["skip_all"]:
            assigned_before = len(assigned)
            _assign_missing_materials(session, display_part, proto, comp, material_names,
                                      material_dialog, state, assigned, assign_failures,
                                      material_libraries, mass_updates)
            if len(assigned) > assigned_before:
                changed.add(proto.FullPath)
        # (palette number or None, translucency or None) -> [(body, material)]
        by_style = {}
        for body in proto.Bodies:
            current = get_body_material(body)
            if state["cancelled"] and not current:
                continue         # cancelled: bodies we never got to are left alone (no magenta)
            style, material = _resolve_style(current, material_styles)
            if style is None:
                unchanged[material] = unchanged.get(material, 0) + 1
                continue
            hex_code, translucency = style
            number = _color_number(hex_code, display_part)
            by_style.setdefault((number, translucency), []).append((body, material))
        if not by_style:
            continue
        is_read_only = proto.IsReadOnly

        try:
            if comp is not None:
                session.Parts.SetWorkComponent(comp)
            for (number, translucency), items in by_style.items():
                set_body_color([b for b, _m in items], number, translucency)
        except Exception as ex:
            skipped.append((proto.Leaf, "could not make it the work part: {0}".format(ex)))
            continue
        finally:
            session.Parts.SetWork(display_part)

        n_parts += 1
        if is_read_only:
            read_only.append(proto.Leaf)
        for (number, translucency), items in by_style.items():
            for body, material in items:
                n_bodies += 1
                detail = []
                if number is not None:
                    detail.append("NX color {0}".format(number))
                if translucency is not None:
                    detail.append("transparency {0}".format(translucency))
                lw.WriteLine("  {0}{1} / {2} -> {3}, {4}{5}".format(
                    proto.Leaf, " (active part)" if comp is None else "",
                    _body_name(body), material, ", ".join(detail),
                    "  (used x{0})".format(instances) if instances > 1 else ""))

    if changed:
        _update_holding_assemblies(session, display_part, changed, mass_updates)

    if state["cancelled"]:
        lw.WriteLine("")
        lw.WriteLine("*** CANCELLED by you. Nothing more was changed; what was already done was kept. ***")
        lw.WriteLine("    {0} part(s) were not processed at all.".format(not_processed))
        if clear_overrides:
            lw.WriteLine("    (Assembly color overrides on the components had already been cleared at the start.)")
    lw.WriteLine("")
    lw.WriteLine("Changed {0} bodies in {1} parts (modified, NOT saved).".format(
        n_bodies, n_parts))
    lw.WriteLine("If a body still looks unchanged, it may carry a body-level override.")
    if assign_missing:
        lw.WriteLine("")
        lw.WriteLine("Materials assigned from the prompt: {0}{1}".format(
            len(assigned), "  (stopped asking early)" if state["skip_all"] else ""))
        for part_name, body_name, material in assigned:
            lw.WriteLine("  {0} / {1} -> {2}".format(part_name, body_name, material))
        if assign_failures:
            lw.WriteLine("Could not assign:")
            for part_name, body_name, material, why in assign_failures:
                lw.WriteLine("  {0} / {1} -> {2}: {3}".format(part_name, body_name, material, why))
        updated = list(dict.fromkeys(name for name, ok, _why in mass_updates if ok))
        if updated:
            lw.WriteLine("Mass properties updated for the new materials ({0} part{1}):".format(
                len(updated), "" if len(updated) == 1 else "s"))
            for name in updated:
                lw.WriteLine("  {0}".format(name))
        failed = [(name, why) for name, ok, why in mass_updates if not ok]
        if failed:
            lw.WriteLine("Could not update the mass properties:")
            for name, why in failed:
                lw.WriteLine("  {0}: {1}".format(name, why))
    if read_only:
        lw.WriteLine("Read-only parts (changed in this session, cannot be saved as-is):")
        for name in read_only:
            lw.WriteLine("  {0}".format(name))
    if skipped:
        lw.WriteLine("Skipped parts:")
        for name, reason in skipped:
            lw.WriteLine("  {0}: {1}".format(name, reason))
    if unchanged:
        lw.WriteLine("Left unchanged (no color or transparency for material):")
        for name, n in sorted(unchanged.items()):
            lw.WriteLine("  {0:<32} x{1}".format(name, n))
    _report_bad_colors(lw)


def run_assembly_level():
    """Color every body in the displayed assembly by material using ASSEMBLY-LEVEL
    display overrides only: the override is set on each body occurrence in the
    displayed assembly. No component part is touched, nothing is made the work
    part, and read-only parts are not a concern. The one exception is the active
    part's OWN bodies, which are colored directly (they are not occurrences). Existing component-level color
    overrides are left as they are.
    """
    session = NXOpen.Session.GetSession()
    lw = session.ListingWindow
    lw.Open()
    _bad_colors.clear()

    display_part = session.Parts.Display
    if display_part is None:
        lw.WriteLine("No displayed part.")
        return

    material_styles = _load_material_styles()
    lw.WriteLine("{0} materials have a color and/or transparency in {1}".format(
        len(material_styles), MATERIALS_CSV))
    lw.WriteLine("Assembly-level overrides only: component parts are not modified.")
    if NO_MATERIAL_COLOR:
        lw.WriteLine("(bodies with no material get {0})".format(NO_MATERIAL_COLOR))
    lw.WriteLine("")
    lw.WriteLine("Bodies changed (component / body -> material, NX color, transparency):")

    # (palette number or None, translucency or None) -> [occurrence bodies]
    by_style = {}
    listing = {}         # (component, body, material, number, translucency) -> count
    unchanged = {}       # material (or "(none)") -> count

    def collect(label, bodies):
        for body in bodies:
            style, material = _resolve_style(get_body_material(body), material_styles)
            if style is None:
                unchanged[material] = unchanged.get(material, 0) + 1
                continue
            hex_code, translucency = style
            number = _color_number(hex_code, display_part)
            by_style.setdefault((number, translucency), []).append(body)
            key = (label, _body_name(body), material, number, translucency)
            listing[key] = listing.get(key, 0) + 1

    # The displayed (active) part's own bodies come first. These are the part's
    # real bodies (not occurrences), so this colors the active part itself; there
    # is no assembly to override them in.
    collect(display_part.Leaf + " (active part)", display_part.Bodies)
    for comp, _depth in walk_components():
        collect(comp.DisplayName, get_bodies(comp))

    n_bodies = 0
    for (number, translucency), bodies in by_style.items():
        n_bodies += set_body_color(bodies, number, translucency)

    # One line per distinct component/body, with a quantity when repeated.
    for (comp_name, body_name, material, number, translucency), n in listing.items():
        detail = []
        if number is not None:
            detail.append("NX color {0}".format(number))
        if translucency is not None:
            detail.append("transparency {0}".format(translucency))
        lw.WriteLine("  {0} / {1} -> {2}, {3}{4}".format(
            comp_name, body_name, material, ", ".join(detail),
            "  x{0}".format(n) if n > 1 else ""))

    lw.WriteLine("")
    lw.WriteLine("Changed {0} body occurrences (assembly-level, NOT saved).".format(n_bodies))
    lw.WriteLine("These overrides live in the assembly; the component parts are unchanged.")
    lw.WriteLine("Bodies owned by the active part itself are colored on that part.")
    if unchanged:
        lw.WriteLine("Left unchanged (no color or transparency for material):")
        for name, n in sorted(unchanged.items()):
            lw.WriteLine("  {0:<32} x{1}".format(name, n))
    _report_bad_colors(lw)
