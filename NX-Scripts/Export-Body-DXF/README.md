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
5. **Cleans the file up:** NX writes every line and arc twice (the top and bottom of a plate land on top of each
   other in the view), so each is kept once; zero-length lines are dropped.

   NX writes DXFs **in the background**: the export hands each one to a translator program, which takes about
   **40 seconds**. So the old file of the same name (and its `.log`) is deleted before the export, and the
   clean-up runs afterwards as a small background program (`lib/dxf_cleanup.py` in the repo's `.venv` Python, the
   same one the McMaster importer uses), which waits for each DXF. NX is free meanwhile.

   **Only usable DXFs stay in `output/dxf`.** The translator's own log beside each DXF (`<name>.log`) is deleted
   once the DXF is written, and a DXF that came out empty is deleted too. What the clean-up did goes to **`helion_dxf_cleanup.log` in the Windows temp folder**
   (`%TEMP%`, rewritten by every run), one line per DXF, e.g.
   `1156009-001.01-UNRELEASED.dxf: removed 8 bend lines; removed 36 doubled lines/arcs`. If a clean-up fails,
   that DXF is left as NX wrote it and the log says why.

## Sheet metal parts

A part counts as **sheet metal** when it has a sheet metal feature: a Flat Solid, a Flat Pattern, or any feature
whose type or name starts with `SB_` (SB Convert To Sheet Metal, SB Flange, ...). Bodies named after a Flat Solid,
like `SB_FLAT_SOLID(21:1B)`, count too. What the tool found is written to NX's log file (Help → Log File, lines
starting `[Export DXF]`), together with the Listing Window text.

A sheet metal part gets **one DXF, of its Flat Solid only** (Sheet Metal → Flat Solid), with the **outline and
holes, without bend lines**. The formed body (and anything else) is skipped and listed.

A **hidden** Flat Solid (Hide, Ctrl+B) is shown for the moment of the export and hidden again straight after: NX
leaves hidden objects out of a DXF, so it came out empty. Confirmed in NX on 2026-11-11.

A sheet metal part **without a Flat Solid** (no flat at all, or only a Flat Pattern) gets a **temporary Flat
Solid**: the tool adds one, exports it, and removes it again (undo), so the part is left as it was. It is made as
Sheet Metal → Flat Solid makes one (recorded in `example_journals/journal_flat_solid.py`), with the layer, color and
corner treatments from your sheet metal preferences. The **stationary face** (the face that stays put while the
rest unfolds) is the bent body's **largest flat face**: always on a flange, never a bend or an edge face. Which
flange it is only moves the flat body in space; a face on the other side of the sheet can give the mirror image,
which for a flat blank is the same part turned over (it matters only for one-sided details such as engraving). If
NX will not build it outside the Sheet Metal application, the tool switches there for the build and back. If it
cannot be made at all, the listing says why and asks you to add a Flat Solid.

A Flat Pattern is not exported itself: its own flat body (a hidden Flat Solid the Flat Pattern makes,
`FLAT_PATTERN(8:1B)`) has nothing NX's 2D step will draw, even when shown, and NX's Export Flat Pattern writes
empty DXFs too (both seen on 2026-11-11).

Bend lines:

* A flattened body keeps each bend region as a face of its own, in the same plane as the flanges, so its edges
  show up as lines across the part. The tool finds those edges in NX (straight edges where two flat faces meet in
  one plane) and removes the matching lines from the DXF.
* To match them it lines the part up with the DXF's coordinates (using the body's corners). If that fails, the
  bend lines are left in and `helion_dxf_cleanup.log` says **bend lines NOT removed**.

Sheet metal handling and the clean-up were added on 2026-11-11 and confirmed in NX the same day for a shown and
a hidden Flat Solid. The temporary Flat Solid was added the same day and has not been run in NX yet.

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
