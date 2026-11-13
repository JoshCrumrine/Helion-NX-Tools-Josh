# NX 2506
# Author:  br435t
# Created: 2026-10-27
# Exports one DXF per solid body of the WORK part. For each body: measure every face, take the
# largest flat face, save a view looking straight at it (zoomed to fit) called DXF_<BODYNAME>, export
# the body to DXF through that view with all edges shown, as
# output/dxf/<partID>.<revision>-UNRELEASED.dxf in the repo's output folder (with _<bodyname> added
# when the part has several solid bodies), with each line once. A sheet metal part gets one DXF,
# of its Flat Solid only, without bend lines; one without a Flat Solid gets a temporary one,
# removed again after the export.
# NX writes DXFs in the background (~40 s), so the clean-up runs in the background too; it deletes
# the translator's .log beside each DXF and writes helion_dxf_cleanup.log in the Windows temp folder.
# The Listing Window text also goes to NX's log file.
# No feature Builder exists for saving views or the DXF exporter, so the views are not features
# (each one is its own undo step). See README.md in this folder and lib/body_dxf.py for the
# implementation.
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _find_repo_root():
    """Walk up from this script to the repo root (the dir holding lib/) and
    put it on sys.path so `import lib...` works when NX runs the script."""
    d = _HERE
    for _ in range(6):
        if os.path.isfile(os.path.join(d, "lib", "__init__.py")):
            if d not in sys.path:
                sys.path.insert(0, d)
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    raise RuntimeError("Could not find the repo root (folder containing lib/)")


REPO_ROOT = _find_repo_root()

import NXOpen  # noqa: E402
from lib.body_dxf import export_part_bodies  # noqa: E402


def main(args):
    session = NXOpen.Session.GetSession()
    lw = session.ListingWindow
    lw.Open()

    def say(line):
        """A line to the Listing Window, also written to NX's log file (Help > Log File)."""
        lw.WriteLine(line)
        try:
            session.LogFile.WriteLine("[Export DXF] " + line)
        except Exception:
            pass

    part = session.Parts.Work
    if part is None:
        say("No work part. Open a part first.")
        return
    if session.Parts.Display is None or session.Parts.Display.Tag != part.Tag:
        say("Make the part the displayed part first (the views are made in the graphics window).")
        return

    say("Exporting DXF files for {0} ...".format(part.Leaf))
    result = export_part_bodies(session, part, log=say)

    say("")
    say("Exported {0} DXF file(s) to: {1}".format(len(result["exported"]), result["out_dir"]))
    for name, why in result["skipped"]:
        say("Skipped {0}: {1}".format(name, why))
    for name, why in result["failures"]:
        say("Failed {0}: {1}".format(name, why))


if __name__ == '__main__':
    main(sys.argv[1:])
