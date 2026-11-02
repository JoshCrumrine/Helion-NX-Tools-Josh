"""Assign one library material to bodies of a part: the ones with no material, or ones you pick.

Used by NX-Scripts/Assign-Material. The material is picked in a BlockStyler dialog (the same
list-with-search dialog style as Color-By-Material's ASSIGN_MATERIAL_dialog.dlx).
"""
import NXOpen
import NXOpen.UF          # NX only creates NXOpen.UF once it is imported explicitly

from lib.assemblies import assign_material, get_body_material, update_mass_properties
from lib.color_by_material import (load_material_libraries, load_material_names,
                                   load_material_styles)
from lib.colors import color_number_from, set_body_color
from lib.nx_dialogs import choose_from_list


def _body_name(body):
    try:
        return body.Name or body.JournalIdentifier
    except Exception:
        return "?"


def _highlight(bodies):
    for b in bodies:
        try:
            b.Highlight()
        except Exception:
            pass


def _unhighlight(bodies):
    for b in bodies:
        try:
            b.Unhighlight()
        except Exception:
            pass


# ----------------------------------------------------------------------------- picking bodies
def _body_mask():
    """Selection mask that allows only solid bodies (not faces, edges or sheet bodies)."""
    c = NXOpen.UF.UFConstants
    return [NXOpen.Selection.MaskTriple(
        getattr(c, "UF_solid_type", 70),
        getattr(c, "UF_solid_body_subtype", 0),
        getattr(c, "UF_UI_SEL_FEATURE_SOLID_BODY", 36))]


def bodies_of_part(objects, part):
    """Keep only the solid bodies that belong to `part`.

    Returns (bodies, rejected): occurrences are mapped to their prototype bodies, duplicates are
    dropped, and `rejected` lists "<name>: <why>" for everything left out.
    """
    bodies, rejected, seen = [], [], set()
    for obj in objects:
        try:
            body = obj.Prototype if obj.IsOccurrence else obj
            if body.OwningPart.Tag != part.Tag:
                rejected.append("{0}: not a body of {1}".format(_body_name(obj), part.Leaf))
                continue
            if not body.IsSolidBody:
                rejected.append("{0}: not a solid body".format(_body_name(obj)))
                continue
            if body.Tag in seen:
                continue
            seen.add(body.Tag)
            bodies.append(body)
        except Exception as ex:
            rejected.append("{0}: {1}".format(_body_name(obj), ex))
    return bodies, rejected


def pick_bodies(session, part, ui=None):
    """Ask the user to select bodies in the graphics window.

    Returns (bodies, rejected, status) where status is "ok", "cancelled" (Back/Cancel) or "empty"
    (OK with nothing usable selected). The selected bodies stay highlighted; the caller
    un-highlights them (assign_material_to_part does).
    """
    if ui is None:
        ui = NXOpen.UI.GetUI()
    Sel = NXOpen.Selection
    response, objects = ui.SelectionManager.SelectObjects(
        "Select the bodies to assign a material to, then click OK",
        "Assign Material", Sel.SelectionScope.WorkPart, Sel.SelectionAction.ClearAndEnableSpecific,
        False, True, _body_mask())
    if response != Sel.Response.Ok:
        _unhighlight(objects or [])
        return [], [], "cancelled"
    bodies, rejected = bodies_of_part(objects or [], part)
    return bodies, rejected, ("ok" if bodies else "empty")


# ----------------------------------------------------------------------------- coloring
def _describe_style(style):
    hex_code, translucency = style
    parts = []
    if hex_code:
        parts.append(str(hex_code))
    if translucency is not None:
        parts.append("{0}% translucent".format(translucency))
    return ", ".join(parts)


def _apply_material_color(part, targets, result, material):
    """Color the bodies that took `material` from the CSV style; record it in `result`."""
    try:
        style = load_material_styles().get(material.lower())
        if not style:
            return
        hex_code, translucency = style
        number = color_number_from(hex_code, part) if hex_code else None
        done = set(result["assigned"])
        set_body_color([b for b in targets if _body_name(b) in done], number, translucency)
        if number is not None or translucency is not None:
            result["color"] = style
    except Exception as ex:
        result["color_error"] = str(ex)


def _update_mass_properties(session, part, result):
    """Update the part's mass properties (weight) so they use the new materials
    (lib.assemblies.update_mass_properties). A failure is recorded, not raised."""
    ok, why = update_mass_properties(part)
    if ok:
        result["mass_updated"] = True
    else:
        result["mass_error"] = why


# ----------------------------------------------------------------------------- assigning
def assign_material_to_part(session, part, dialog_path, bodies=None):
    """Ask for a material and assign it to bodies of `part`.

    `part` must be the current work part (NX assigns materials in the work part's context).

    bodies=None   every body of the part that has NO material gets it; bodies that already have
                  one are left alone.
    bodies=[...]  exactly these bodies get it, EVEN IF they already have a material (it is
                  replaced); the dialog heading says how many will be replaced.

    After the material is assigned, the bodies that took it are colored (and given the translucency)
    from the material's row in Materials/NX_Materials.csv; a material with no color/translucency
    there leaves the body's color alone. Finally the part's mass properties (weight) are updated so
    they reflect the new material densities.

    One dialog is shown; cancelling it, or pressing OK with nothing selected, changes nothing. The
    bodies about to change are highlighted while it is open. Everything done is a single undo step
    ("Assign Material to Part"); nothing is saved. Writes a report to the Listing Window and
    returns a dict:
        status    "assigned" | "nothing_to_do" | "cancelled" | "no_bodies" | "error"
        material  the chosen name (or None)
        assigned  [body names]   skipped [body names left alone]
        replaced  [(body name, old material)]   failures [(body name, reason)]
        color     the (hex or ID, translucency) applied, or None; color_error  why it failed, or None
        mass_updated  True once the part's mass properties were updated; mass_error  why not, or None
    """
    lw = session.ListingWindow
    lw.Open()
    result = {"status": "error", "material": None, "assigned": [], "skipped": [],
              "replaced": [], "failures": [], "color": None, "color_error": None,
              "mass_updated": False, "mass_error": None}

    all_bodies = list(part.Bodies)
    if bodies is None:
        if not all_bodies:
            lw.WriteLine("'{0}' has no bodies. Nothing to do.".format(part.Leaf))
            result["status"] = "no_bodies"
            return result
        targets = [b for b in all_bodies if get_body_material(b) is None]
        result["skipped"] = [_body_name(b) for b in all_bodies if b not in targets]
        if not targets:
            lw.WriteLine("All {0} bodies of '{1}' already have a material. Nothing to do.".format(
                len(all_bodies), part.Leaf))
            result["status"] = "nothing_to_do"
            return result
        heading = "{0}: {1} of {2} bodies have no material. Pick one for them:".format(
            part.Leaf, len(targets), len(all_bodies))
    else:
        targets = list(bodies)
        if not targets:
            lw.WriteLine("No bodies selected. Nothing was changed.")
            result["status"] = "nothing_to_do"
            return result
        has = sum(1 for b in targets if get_body_material(b) is not None)
        heading = "{0}: {1} bodies selected".format(part.Leaf, len(targets))
        if has:
            heading += ", {0} already have a material that will be REPLACED".format(has)
        heading += ". Pick one:"

    before = {id(b): get_body_material(b) for b in targets}
    names = load_material_names()
    libraries = load_material_libraries()

    _highlight(targets)
    try:
        chosen, _skip = choose_from_list(
            dialog_path, "materialList", names, heading=heading,
            heading_id="heading", search_id="searchBox",
            on_shown=lambda: _highlight(targets))
    except Exception as ex:
        lw.WriteLine("Could not show the material dialog: {0}".format(ex))
        return result
    finally:
        _unhighlight(targets)

    if not chosen:
        lw.WriteLine("No material chosen. Nothing was changed.")
        result["status"] = "cancelled"
        return result

    result["material"] = chosen
    if getattr(part, "IsReadOnly", False):
        lw.WriteLine("Note: '{0}' is read-only, so the assignment can be made in this session "
                     "but cannot be saved over the original.".format(part.Leaf))

    mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Assign Material to Part")
    lib_files = libraries.get(chosen.lower(), ())
    for body in targets:
        name = _body_name(body)
        ok, why = assign_material(part, body, chosen, lib_files)
        old = before[id(body)]
        if ok and old and old != chosen and get_body_material(body) == old:
            ok, why = False, "NX accepted it but the body still has '{0}'".format(old)
        if ok:
            result["assigned"].append(name)
            if old and old != chosen:
                result["replaced"].append((name, old))
        else:
            result["failures"].append((name, why))

    if result["assigned"]:
        session.SetUndoMarkName(mark, "Assign Material to Part")
    else:
        try:
            session.UndoToMark(mark, None)       # nothing took: drop what loading the material may have added
            session.DeleteUndoMark(mark, None)
        except Exception:
            pass

    if result["assigned"]:
        _apply_material_color(part, targets, result, chosen)
        _update_mass_properties(session, part, result)

    result["status"] = "assigned" if result["assigned"] else "error"
    lw.WriteLine("Material: {0}".format(chosen))
    lw.WriteLine("Assigned to {0} of {1} bodies in {2} (not saved):".format(
        len(result["assigned"]), len(targets), part.Leaf))
    old_of = dict(result["replaced"])
    for name in result["assigned"]:
        lw.WriteLine("  {0}{1}".format(name, "   (replaced {0})".format(old_of[name]) if name in old_of else ""))
    if result["color"]:
        lw.WriteLine("Color set from the material: {0}".format(_describe_style(result["color"])))
    elif result["color_error"]:
        lw.WriteLine("Material assigned, but the color could not be set: {0}".format(result["color_error"]))
    elif result["assigned"]:
        lw.WriteLine("No color for this material in NX_Materials.csv; body colors left as they were.")
    if result["mass_updated"]:
        lw.WriteLine("Mass properties of {0} updated.".format(part.Leaf))
    elif result["mass_error"]:
        lw.WriteLine("Material assigned, but the mass properties could not be updated: {0}".format(result["mass_error"]))
    if result["skipped"]:
        lw.WriteLine("Left alone, already had a material: {0}".format(len(result["skipped"])))
    if result["failures"]:
        lw.WriteLine("Could not assign ({0}):".format(len(result["failures"])))
        for name, why in result["failures"]:
            lw.WriteLine("  {0}: {1}".format(name, why))
    return result
