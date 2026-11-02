# NX 2506
# Author:  br435t
# Created: 2026-10-20
# Colors every body in the displayed assembly according to its NX physical
# material, like color_by_material.py, but when it meets a body with NO material it
# prompts you to pick one from the material library, assigns it, and then colors the
# body with that material's color.
#
# Run via File -> Execute -> NX Open... with an assembly displayed.
#
# The dialog has a Search box: type part of a material name (words in any order, e.g.
# "alum 60") and press Enter to narrow the list; clear it to see every material.
# One dialog per body without a material (Cancel skips that body; the "Stop asking"
# toggle skips all the rest; the "CANCEL THE WHOLE OPERATION" toggle stops the run, keeping
# what was already done). The body being asked about is highlighted in the graphics
# window while the dialog is open (no zoom; your view is left alone). A skipped body gets the no-material color, as in
# color_by_material.py. Assembly-level color overrides on components are cleared
# first, also as in color_by_material.py.
#
# Each part that gets a material then has its mass properties updated (Analysis > Mass
# Properties > Update Now, as Assign Material does), and so does every assembly that holds
# it, deepest first, so the weights use the new materials.
#
# This MODIFIES the component parts: the material assignment, the color and the weight are
# left unsaved. See README.md in this folder, and lib/color_by_material.py for the
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

from lib.color_by_material import run  # noqa: E402

# The material picker dialog sits next to this script.
_MATERIAL_DLX = os.path.join(_HERE, "ASSIGN_MATERIAL_dialog.dlx")

run(clear_overrides=True, assign_missing=True, material_dialog=_MATERIAL_DLX)
