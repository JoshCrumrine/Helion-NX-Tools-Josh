# NX 2506
# Author:  br435t
# Created: 2026-07-10
# Journal created by br435t on Tue Jul 14 09:12:10 2026 Pacific Daylight Time
#
# User-facing flow only. Every helper this script calls lives in lib/ at the
# repo root (lib/mcmaster.py, lib/teamcenter.py, lib/nx_dialogs.py).
import os
import sys
import NXOpen # type: ignore

_HERE = os.path.dirname(os.path.abspath(__file__))


def _add_repo_root_to_path():
    """Walk up from this script to the repo root (the dir holding lib/) and
    put it on sys.path so `import lib...` works when NX runs the script."""
    d = _HERE
    for _ in range(6):
        if os.path.isfile(os.path.join(d, "lib", "__init__.py")):
            if d not in sys.path:
                sys.path.insert(0, d)
            return
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent


_add_repo_root_to_path()

from lib.layers import move_to_layer  # noqa: E402
from lib.mcmaster import MCMASTER_OUT, build_description, fetch_mcmaster, make_filename_safe  # noqa: E402
from lib.nx_dialogs import DeferredListing, ask_yes_no, prompt_string  # noqa: E402
from lib.teamcenter import (MCMASTER_TC_FOLDER, find_item_revision_spec, import_parasolid,  # noqa: E402
                            open_teamcenter_part)
from lib.vendor_part import create_vendor_part  # noqa: E402
from lib.views import fit_work_view  # noqa: E402

# Single-field BlockStyler dialogs (part-number and part-name prompts). These
# sit next to this script.
_PARTNO_DLX = os.path.join(_HERE, "CREATE_MCMASTER_PART_partno_dialog.dlx")
_PARTNAME_DLX = os.path.join(_HERE, "CREATE_MCMASTER_PART_partname_dialog.dlx")

# Revision the new part is created with (DB_PART_REV).
_PART_REVISION = "NC"

# Layer the imported geometry (all bodies) is moved to.
_BODY_LAYER = 71


def main(args) :

    theSession  = NXOpen.Session.GetSession() #type: NXOpen.Session
    # The log goes to the Listing Window only at the end, and only when the run
    # stopped without the part on screen (cancelled or failed). Written earlier,
    # the Information window pops up over the dialogs below and takes their
    # keyboard focus.
    lw = DeferredListing(theSession.ListingWindow)
    succeeded = False
    try:
        succeeded = _run(theSession, lw)
    finally:
        if not succeeded:
            lw.flush()


def _run(theSession, lw):
    """The tool's flow. True when it ends with the part open (new or existing)."""

    # --- 1. Ask for the McMaster part number ---
    entered_pn = prompt_string(_PARTNO_DLX, "partNo")
    if entered_pn is None:
        return  # dismissed before anything happened: nothing to report
    lw.WriteLine("=" * 60)
    lw.WriteLine("Running CREATE_MCMASTER_PART.py (McMaster -> Teamcenter COTS part)")
    lw.WriteLine("=" * 60)
    if not entered_pn:
        lw.WriteLine("Cancelled: no part number entered.")
        return

    # --- 1b. Part already exists in Teamcenter -> open it ---
    # COTS item ids are the vendor part number (DB_PART_NO). Re-creating an
    # existing id fails at Commit() with the opaque "The new filename is not a
    # valid file specification", so check up front (before the scrape). If the
    # part exists, open it instead of creating a duplicate.
    lw.WriteLine("Checking Teamcenter for existing part {0} ...".format(entered_pn))
    existing_spec = find_item_revision_spec(theSession, entered_pn, log=lw.WriteLine)
    if existing_spec:
        lw.WriteLine("Part {0} already exists - opening {1} ...".format(
            entered_pn, existing_spec))
        try:
            opened = open_teamcenter_part(theSession, existing_spec)
        except Exception as ex:
            NXOpen.UI.GetUI().NXMessageBox.Show(
                "Part Already Exists",
                NXOpen.NXMessageBox.DialogType.Error,
                "Part {0} already exists in Teamcenter, but it could not be "
                "opened:\n\n{1}".format(entered_pn, ex))
            lw.WriteLine("Aborted: could not open existing part {0}: {1}".format(
                entered_pn, ex))
            return
        lw.WriteLine("Opened existing part: {0}".format(opened.Leaf))
        return True

    # --- 2. Scrape JSON + download the no-threads Parasolid CAD ---
    # NX is busy for the few seconds this takes; the part-name dialog (step 4)
    # comes up when it is done.
    lw.WriteLine("Fetching McMaster data for {0} -> {1} ...".format(
        entered_pn, MCMASTER_OUT))
    fetched = fetch_mcmaster(entered_pn, log=lw.WriteLine)
    if fetched["error"]:
        lw.WriteLine("Aborted: {0}".format(fetched["error"]))
        return
    data = fetched["data"]
    if fetched.get("json_file"):
        lw.WriteLine("  JSON: {0}".format(fetched["json_file"]))

    # --- 2b. No CAD -> ask the user whether to continue ---
    # Some items (raw stock, bulk goods, e.g. 5887K51) have no 3-D Parasolid
    # model. Creating the Teamcenter item without geometry leaves an empty
    # BE9_COTS item, so ask before going on; "No" aborts before anything is
    # created. "Yes" creates the part and skips the geometry import (step 6).
    cad_file = fetched.get("cad_file")
    if not cad_file or not os.path.exists(cad_file):
        reason = fetched.get("cad_error") or "no CAD file was downloaded"
        if cad_file and not os.path.exists(cad_file):
            reason = "downloaded CAD file is missing: {0}".format(cad_file)
        lw.WriteLine("No CAD for {0}: {1}".format(entered_pn, reason))
        if not ask_yes_no(
                "No CAD Available",
                "No CAD model could be downloaded for part {0}.\n\n"
                "{1}\n\n"
                "Create the part in Teamcenter WITHOUT geometry?\n\n"
                "Yes = create an empty part (no CAD imported)\n"
                "No  = cancel; nothing is created.".format(entered_pn, reason)):
            lw.WriteLine("Aborted: no CAD for {0}; user declined to create "
                         "an empty part.".format(entered_pn))
            return
        cad_file = None
        lw.WriteLine("  Continuing without CAD (empty part will be created).")
    else:
        lw.WriteLine("  CAD : {0}".format(cad_file))

    # --- 3. Derive attribute values ---
    part_no = (data.get("part_number") or entered_pn).strip()
    part_desc = build_description(data)          # title_primary + secondary, UPPER
    manufacturer = "MCMASTER-CARR"               # hardcoded
    part_class = "Class II"                      # hardcoded
    lw.WriteLine("  Description: {0}".format(part_desc))

    # --- 4. Ask the user for the part name (DB_PART_NAME), prefilled with the
    #        description as an editable default ---
    part_name = prompt_string(_PARTNAME_DLX, "partName", default=part_desc)
    if part_name is None:
        lw.WriteLine("Cancelled: part name dialog dismissed.")
        return
    if not part_name:
        lw.WriteLine("Cancelled: no part name entered.")
        return

    # The part name becomes the part filename; strip illegal filename chars
    # (the DB_PART_DESC attribute is no longer set).
    safe_name = make_filename_safe(part_name).upper()  # all caps
    if safe_name != part_name:
        lw.WriteLine("  Part name sanitized for filename: {0}".format(safe_name))
    part_name = safe_name
    lw.WriteLine("  Name       : {0}".format(part_name))

    # --- 5. Create the BE9_COTS item (File > New > Item) ---
    lw.WriteLine("Creating COTS part {0} ...".format(part_no))
    workPart = create_vendor_part(part_no, part_name, manufacturer, part_class,
                                  destination_folder=MCMASTER_TC_FOLDER, lw=lw,
                                  revision=_PART_REVISION)
    lw.WriteLine("Created COTS part: {0}  (requested revision {1})".format(
        workPart.Leaf, _PART_REVISION))

    # --- 6. Import the downloaded Parasolid geometry into the new part ---
    # cad_file is None when the user chose to create the part without CAD
    # (step 2b); there is nothing to import in that case.
    if cad_file:
        lw.WriteLine("Running Parasolid import (import_parasolid)")
        lw.WriteLine("  > {0}".format(cad_file))
        import_parasolid(theSession, cad_file)
        lw.WriteLine("  imported geometry into {0}.".format(workPart.Leaf))

        # --- 7. Move all bodies to layer 71 ---
        moved = move_to_layer(_BODY_LAYER, part=workPart)
        lw.WriteLine("  moved {0} body(ies) to layer {1}.".format(moved, _BODY_LAYER))

        # --- 7b. Zoom to fit all the imported bodies ---
        # Best effort: if NX cannot fit the view, the part is still fully created.
        if fit_work_view(theSession.Parts.Display or workPart):
            lw.WriteLine("  zoomed to fit all bodies.")
        else:
            lw.WriteLine("  could not zoom to fit (use View > Fit).")
    else:
        lw.WriteLine("  skipped Parasolid import (no CAD).")

    theSession.CleanUpFacetedFacesAndEdges()

    # --- 8. Done: the new part on screen is the confirmation (no Listing Window) ---
    return True


if __name__ == '__main__':
    main(sys.argv[1:])
