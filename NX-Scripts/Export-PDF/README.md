# Export PDF (NX Open)

NX Open (Python) script for **NX 2506**. One click exports **every sheet of the displayed drawing** to **one
PDF** in the repo's **`output\pdf`** folder, each page the size of its sheet, with **UNRELEASED** written large
and see-through diagonally across every page. STEP and DXF exports go to `output\step` and `output\dxf`
beside it.

Scripts: `NX-Scripts/Export-PDF/export_pdf.py` (the button) and `pdf_watermark.py` beside it (adds the
watermark; keep the two together). No `lib/` imports. Button icon: `pdf.bmp`.

**Status: trial.** First run in NX on 2026-10-30 worked (export and watermark); the out-of-date box has not
been seen in NX yet. Built from the NX Open API reference; no recorded journal yet. The watermark was also
tested on 184 Helion drawing PDFs made by NX.

## Run it

1. Open the drawing in **NX 2506** (it must be the **displayed** part; Drafting or any other application).
2. Click your **Export PDF** button, or **File → Execute → NX Open…** and pick `export_pdf.py`.
3. If any view is out of date, a box lists them and asks **Export the PDF anyway?** **Yes** exports the
   drawing as it is; **No** cancels, so you can update the views and click the button again.
4. The **Listing Window** lists the pages with their sizes and the file it wrote, e.g.
   `C:\Code\Helion-NX-Tools\output\pdf\1152103-001.01-UNRELEASED.pdf`.

## Make a button

The same way as the DXF and STEP buttons: a **New User Command** (right-click the ribbon → **Customize…** →
**Commands** → **New Item**) whose action is `export_pdf.py` in this folder, with `pdf.bmp` as its icon.

## What it exports

* **All sheets** of the displayed part, one page each, in sheet order: by the number each sheet name ends in
  (`Sheet 1`, `Sheet 2`, … `Sheet 10`) when every name has one, otherwise in the order NX lists them.
* **Page size = sheet size** (NX's *Full Scale*): an 11 x 17 in sheet gives an 11 x 17 in page, an A3 sheet an
  A3 page, so nothing is shrunk onto letter paper or cut off.
* **Everything else as File → Export → PDF**: colors, line widths and text come from NX's settings, which
  Helion's site defaults set (one thin line width). The PDF is written to a folder, not to Teamcenter.
* **UNRELEASED watermark** on every page, like Teamcenter's UNRELEASED PDFs (Helvetica, lower left to upper
  right) but **20% gray** (lighter than Teamcenter's 30%) and **centered on the drawing's border**: the
  script finds the border as the outermost lines on the page and lays the text along its diagonal, as large
  as fits in 90% of it. A page without lines is centered on the page itself. NX's own watermark option is
  not used: it puts the text about 3/4 in left of center.
* **File name:** `<part number>.<revision>-UNRELEASED.pdf` from the `DB_PART_NO` and `DB_PART_REV`
  attributes.
* **A file of the same name already in `output\pdf` is replaced.** If it is open in a PDF viewer that locks it
  (Acrobat does), the export stops and says so, and the file is left as it was. If the export fails, the
  older file is put back.
* **No PDF without its watermark is kept:** if the watermark cannot be added, the new PDF is deleted and the
  Listing Window says why.
* **Nothing in the drawing changes and nothing is saved.**

## Settings at the top of `export_pdf.py`

* `WATERMARK = "UNRELEASED"`: the text across every page, also added to the file name. `""` exports without
  a watermark and names the file `<part number>.<revision>.pdf`.
* `OUTPUT_DIR`: where the files go (`<repo>\output\pdf`, created when needed).

`pdf_watermark.py` has the look: `OPACITY = 0.2` (0 invisible, 1 solid black) and `FILL = 0.9` (the share of
the border the text spans).

## Good to know

* NX's PDF export only takes sheets of the displayed part, so open the drawing itself (not the model with the
  drawing as a component). A displayed part without sheets gets a message and no file.
* The watermark is added to the PDF NX writes, without changing NX's own content, so it does not depend on
  how the drawing is set up in NX.
* `output\` is git-ignored and `update.bat` never writes to it, so the files stay on your PC.
