# Export Body DXF (NX Open)

NX Open (Python) script for **NX 2506**. For **every solid body** of the work part it writes a flat **DXF**
of that body, seen **square-on to its largest flat face**, with all edges shown.

Script: `NX-Scripts/Export-Body-DXF/export_body_dxf.py`. Logic: `lib/body_dxf.py`.

## Run it

1. Open the part in **NX 2506** and make it the **displayed** (and work) part.
2. **File → Execute → NX Open…** and pick `export_body_dxf.py`.
3. Read the **Listing Window**: one line per body with its file, view and face area, then the folder.

## What it does, per solid body

1. **Measures the area of every face** of the body.
2. Takes the **largest planar face** and saves a **view looking straight at it** (the face normal points at you,
   zoomed to fit), named **`DXF_<BODYNAME>`** (upper-case, illegal characters as `_`, shortened to 30 characters).
   If the largest face is curved (a cylinder, say) it has no single normal, so the largest **flat** face is used
   and the listing says so. A body with **no** flat face is skipped and listed.
3. **Exports the body only** to DXF through that view: 2D, model data, wireframe with every edge visible.
4. Names the file **`<partID>.<revision>-UNRELEASED.dxf`** in the repo's **`output/dxf/`** folder (git-ignored;
   STEP files from [Export-STEP](../Export-STEP/README.md) go to `output/step/` beside it), the same form as the
   STEP and PDF exports. A part with more than one solid body gets **`_<bodyname>`** added to each file
   (`<partID>.<revision>-UNRELEASED_<bodyname>.dxf`), so the files do not overwrite each other.
   Part ID and revision are the `DB_PART_NO` and `DB_PART_REV` attributes; if either is missing the part name
   (`1150201-500/01` → `1150201-500` and `01`) is used and the listing notes it. A name used twice gets
   `_2`, `_3`; an existing file of the same name is overwritten. `SUFFIX` at the top of `lib/body_dxf.py` sets
   the `UNRELEASED` part (`""` leaves it out).

## Good to know

* **The views stay in the part** so you can look at them (Part Navigator → Model Views). Each body is its own
  undo step (**Edit → Undo** removes that body's view); a body that fails is rolled back automatically.
  **Nothing is saved**.
* Saving views and the DXF exporter have no feature Builder in NX Open, so the views are not features.
* The work view is left looking at the last body's face, but its display style (rendering style and Shaded Type) is put
  back (it is made wireframe only while the views are saved, so the part is not left in wireframe). NX can swap the
  saved copy in as the displayed view, so the restore is applied to the current work view as well.
* Only solid bodies are exported; sheet bodies are listed as skipped.
* **Face normal:** taken from `UF Modl.AskFaceData` when this NX build has it (the first run showed it does not),
  otherwise from a temporary "dumb" Direction on the face (works for round faces too; it is deleted again), otherwise
  from the face's edge vertices, and for a round face (one vertex per circle) from the cylinder's seam edge, which
  runs along the disc's normal. If every method fails the error lists why each one did. Unless UF supplied it, the normal is pointed away from the body's material (the side
  most of the body's vertices are on counts as inside). That is right for plates, blocks and discs; a face whose plane
  cuts through the middle of the body could come out flipped (the DXF would then be mirrored).
* **Needs a run in NX to confirm**: the exporter settings follow the recorded `example_journals/journal_export_dxf.py`
  (views saved as in `journal_face_normal.py`; view names quoted as `"DXF_NAME"`, one `SelectionComp.Add(body)` per body, curves/annotations/structures,
  layers 1-256). The journal exported 3D curves without setting 2D, so `ExportAs = TwoD` with the view, and the
  "all edges" wireframe setting, are still unverified.
