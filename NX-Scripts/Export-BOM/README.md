# Export BOM (NX Open)

NX Open (Python) script for **NX 2506**. One click exports the **bill of materials of the displayed assembly**
to an **Excel file** in the repo's **`output\bom`** folder (beside `output\pdf`, `output\step` and `output\dxf`)
and opens it.

Script: `NX-Scripts/Export-BOM/export_bom.py` (self-contained, no `lib/` imports). Button icon: `bom.bmp`.

**Status: trial.** In use in NX since 2026-11-01 (the flat BOM). The Indented BOM sheet is new on
2026-11-13 and not yet run in NX; it was tested against a stand-in for NX and checked in Excel.

## Run it

1. Open the assembly in **NX 2506** (it must be the **displayed** part).
2. Click your **Export BOM** button, or **File → Execute → NX Open…** and pick `export_bom.py`.
3. Excel opens `<part number>.<revision>-BOM.xlsx`, e.g. `C:\Code\Helion-NX-Tools\output\bom\1150000-000.01-BOM.xlsx`.
   The **Listing Window** says how many parts and components there are, what was left out, and anything it
   could not read.

## Make a button

The same way as the other buttons: a **New User Command** (right-click the ribbon → **Customize…** →
**Commands** → **New Item**) whose action is `export_bom.py` in this folder, with `bom.bmp` as its icon.

## What is in the file

Each sheet starts with a title row naming the assembly (`Indented BOM – 1150000-000/01, TOP ASSY`).

* **Indented BOM** sheet (opens first): the nested BOM. The displayed assembly is the first row (level 0);
  under each subassembly come its parts, indented one step further. Subassembly rows are **bold**.
  Columns: **Level, PN, Rev, Name, QTY per Parent, Total QTY, Material, Release Status**.
  * **QTY per Parent**: how many are in one of the subassembly above (4 screws in each mount, say).
  * **Total QTY**: how many that row stands for in the whole assembly (4 mounts × 4 screws = 16).
    The same part in two different subassemblies has a row under each.
  * The rows are **grouped** by subassembly: Excel's **−** and **+** buttons at the left fold a
    subassembly's parts away and back, and the **1 2 3** buttons above them show that many levels.
  * If the instances of a subassembly differ (a part suppressed in one of them), QTY per Parent shows
    the range, e.g. `2-3`, and Total QTY is the exact count.
* **Parts List** sheet: one row per part, sorted by part number, with its **Total QTY** in the whole
  assembly (for ordering). Subassemblies are rows too; the displayed assembly is not. Columns: **PN, Rev,
  Name, Total QTY, Material, Release Status**.
* **PN, Rev, Name**: the `DB_PART_NO`, `DB_PART_REV` and `DB_PART_NAME` attributes. For a part that is not
  loaded, the number and revision come from its file name and the name from Teamcenter.
* **Material**: the materials of the part's solid bodies; several are listed with commas, and a body without
  one shows as `(no material)`. Blank for a subassembly with no bodies of its own.
* **Release Status**: the release status in Teamcenter (`Released`, ...). `Unreleased` when it has none,
  `?` if NX could not get it.
* Text stays text, so revision `01` stays `01` (a CSV file opened in Excel turns it into `1`). The header row
  is bold, frozen and has filters; each sheet prints landscape, one page wide, with the title and header
  repeated on every page.

## What it leaves out, and what it loads

* **Suppressed** and **reference-only** components, and everything under them. The Listing Window counts them.
* A **partially loaded** part is loaded fully, so the materials of its bodies can be read (nothing in it
  changes). The Listing Window lists those parts. On a big assembly this can take a while the first time.
* Loading a part fully can switch its components to the **Entire Part** reference set (datums and all
  showing). The script notes every component's reference set before it starts and puts back any that
  changed; the Listing Window says how many. (The first trial, on 2026-11-01, did not do this yet.)
* A component whose part is **not loaded at all**: its name comes from Teamcenter, and its material and
  status say `not loaded`. Load it and export again.

## Settings at the top of the script

* `OPEN_WHEN_DONE = True`: open the file in Excel when done.
* `UNRELEASED = "Unreleased"`: what Release Status shows when Teamcenter has no status for a part.
* `OUTPUT_DIR`: where the files go (`<repo>\output\bom`, created when needed).

## Good to know

* A file of the same name is replaced. If it is open in Excel, the export stops and says so: close it and click
  again.
* Nothing in the assembly changes and nothing is saved.
* `output\` is git-ignored and `update.bat` never writes to it, so the files stay on your PC.
