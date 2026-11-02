# Export STEP (NX Open)

NX Open (Python) script for **NX 2506**. One click exports the **displayed part** as a **STEP AP214** file
to the repo's **`output\step`** folder, beside `output\dxf` where [Export-Body-DXF](../Export-Body-DXF/README.md)
writes, and puts a **copy in `U:\7 - 3D Prints`** for 3D printing. Made for single-body parts.

Script: `NX-Scripts/Export-STEP/export_step.py` (self-contained, no `lib/` imports). Button icon: `step.bmp`.

**Status: trial.** First run in NX on 2026-10-30 worked. The exporter settings copy File → Export → STEP as
it was used on this PC (read from the NX system log); no recorded journal yet.

## Run it

1. Open the part in **NX 2506** (it must be the **displayed** part).
2. Click your **Export STEP** button, or **File → Execute → NX Open…** and pick `export_step.py`.
3. The **Listing Window** shows the file it wrote, e.g.
   `C:\Code\Helion-NX-Tools\output\step\1152103-001.01-UNRELEASED.stp`,
   whether the STEP translator processed the body without problems, and where the copy went
   (`Copied to U:\7 - 3D Prints\1152103-001.01-UNRELEASED.stp`).

## Make a button

The same way as the DXF button: add a **New User Command** (right-click the ribbon → **Customize…** →
**Commands** → **New Item**), set its action to `export_step.py` in this folder, and give it `step.bmp` as its
icon.

## What it exports

* **The solid bodies in the part's `MODEL` reference set** (there should be just one). Sheet bodies, datums and
  curves in `MODEL` are left out. If the part has no `MODEL` reference set, or `MODEL` holds no solid body,
  nothing is exported and the Listing Window says why.
* **Settings as File → Export → STEP** with this site's defaults: AP214 with NX's own settings file
  (`%UGII_BASE_DIR%\step214ug\ugstep214.def`), export from the displayed part, selected objects (the `MODEL`
  bodies), solids only, absolute coordinates, layers 1-256, written to the file system (the dialog starts on
  Teamcenter).
* **File name:** `<part number>.<revision>-UNRELEASED.stp` from the `DB_PART_NO` and `DB_PART_REV`
  attributes, the same form as Export PDF and Export Body DXF (NX's own suggestion adds the part name).
* **A file of the same name already in `output\step` is replaced.** If it is open in another program, the
  export stops and says so, and the file is left as it was. If the export fails, the older file is put back.
* **Translator check:** NX's STEP translator writes a `.log` next to the `.stp`. The script reads its summary
  (solids in, solids without problems, solids turned into sheets or not translated, errors, warnings). A clean
  translation deletes the `.log`; otherwise the Listing Window lists the problems and the `.log` is kept.
* **A copy for 3D printing** goes to `U:\7 - 3D Prints` (the `.stp` only). It **never replaces** a file there:
  if the name is taken, the copy gets `_2`, `_3`, ... so earlier print versions are kept. If the folder cannot
  be reached (U: drive not connected) or the copy fails, the file in `output\step` still stands and the
  Listing Window says why there is no copy. A failed export makes no copy.
* **Nothing in the part changes and nothing is saved.** Unsaved changes are exported as they are on screen.

## Settings at the top of the script

* `PROTOCOL = "AP214"`: change to `"AP242"` or `"AP203"` for another STEP version (each uses NX's matching
  settings file).
* `REFERENCE_SET = "MODEL"`: the reference set whose solid bodies are exported.
* `SUFFIX = "UNRELEASED"`: added to the file name after a dash; `""` names the file
  `<part number>.<revision>.stp`.
* `PRINT_COPY_DIR = r"U:\7 - 3D Prints"`: where the copy goes; `""` for no copy. It is a personal folder:
  someone you share the tool with sets their own (or `""`), else the listing just says it is not there.
* `OUTPUT_DIR`: where the files go (`<repo>\output\step`, created when needed).

## Good to know

* The translator leaves **hidden** bodies out (`PROCESS_HIDDEN_OBJECTS=No` in NX's settings file). A hidden
  `MODEL` body gives a STEP file without it; the Listing Window then says that fewer solids reached the
  translator than were sent.
* `output\` is git-ignored and `update.bat` never writes to it, so the files stay on your PC.
