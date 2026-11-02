# NX 2506
# Author:  jo388c
# Created: 2026-10-29
# Exports all sheets of the displayed drawing to one PDF in the repo's output\pdf folder, in one click,
# with UNRELEASED written large and see-through across every page.
#
# Each page is the size of its sheet (Full Scale: an 11 x 17 in sheet gives an 11 x 17 in page), in
# sheet order: by the number each sheet name ends in (Sheet 1, Sheet 2, ...), or as NX lists them when
# a name has no number. Everything else (colors, line widths, text) comes from NX's settings for
# File > Export > PDF, which Helion's site defaults set (one thin line width). pdf_watermark.py (in
# this folder) then writes the watermark diagonally across each page, centered on the drawing's
# border. The file is named <part number>.<revision>-UNRELEASED.pdf; a file of that name already in
# output\pdf is replaced. STEP and DXF exports go to output\step and output\dxf beside it. Nothing
# in the drawing changes and nothing is saved.
#
# If any view is out of date, a warning lists them and asks whether to export anyway (Yes) or to
# cancel (No) so the views can be updated first.
#
# Run it from a button (see README.md), or File -> Execute -> NX Open... with the drawing displayed.
# The Listing Window lists the pages and their sizes, and the file it wrote.
#
# No lib/ imports on purpose, only pdf_watermark.py beside it: NX re-reads both on every run, so a
# change to either works on the next click without restarting NX.
import os
import re
import sys
import time

import NXOpen
import NXOpen.Drawings

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import pdf_watermark  # noqa: E402

WATERMARK = "UNRELEASED"    # written across every page and added to the file name; "" for neither
_WAIT_SECONDS = 30          # how long to wait for NX to finish writing the PDF

# <repo>\output\pdf: this file is <repo>\NX-Scripts\Export-PDF\export_pdf.py
_REPO = os.path.dirname(os.path.dirname(_HERE))
OUTPUT_DIR = os.path.join(_REPO, "output", "pdf")

_UNSAFE = r'[\\/:*?"<>|\x00-\x1f]'      # characters Windows does not allow in file names


# ----------------------------------------------------------------------------- what
def _string_attribute(part, title):
    """The string attribute `title` of `part`, or "" if it is missing or cannot be read."""
    try:
        if part.HasUserAttribute(title, NXOpen.NXObject.AttributeType.String, -1):
            return part.GetStringUserAttribute(title, -1).strip()
    except Exception:
        pass
    return ""


def pdf_file_name(part):
    """"<number>.<revision>-UNRELEASED.pdf": the part number and revision, then the watermark.

    Number and revision are the DB_PART_NO and DB_PART_REV attributes, falling back to the part
    name ("1152103-001/01"). Characters Windows does not allow in file names become "_". A part that
    is not in Teamcenter keeps its own name: bracket.prt -> bracket-UNRELEASED.pdf.
    """
    leaf_number, _, leaf_rest = str(part.Leaf or "").partition("/")
    number = _string_attribute(part, "DB_PART_NO") or leaf_number.strip()
    rev = _string_attribute(part, "DB_PART_REV") or re.split(r"[\s/]", leaf_rest.strip(), 1)[0]
    stem = re.sub(_UNSAFE, "_", number + ("." + rev if rev else "")).strip(" .") or "drawing"
    if WATERMARK:
        stem += "-" + re.sub(_UNSAFE, "_", WATERMARK).strip(" .")
    return stem + ".pdf"


def sheets_in_order(part):
    """The part's drawing sheets in page order: by the number each name ends in ("Sheet 2",
    "SHT10") when every name has one, otherwise in the order NX lists them."""
    sheets = list(part.DrawingSheets)
    numbers = [re.search(r"(\d+)\s*$", sheet.Name or "") for sheet in sheets]
    if all(numbers):
        order = sorted(range(len(sheets)), key=lambda i: int(numbers[i].group(1)))
        sheets = [sheets[i] for i in order]
    return sheets


def sheet_size(sheet):
    """'17 x 11 in': the sheet's width x height."""
    units = "in" if sheet.Units == NXOpen.Drawings.DrawingSheet.Unit.Inches else "mm"
    return "{0:g} x {1:g} {2}".format(round(sheet.Length, 3), round(sheet.Height, 3), units)


def _out_of_date(thing):
    """Whether a sheet or view says it is out of date (False when NX cannot tell)."""
    try:
        return bool(thing.IsOutOfDate)
    except Exception:
        return False


def stale_views(sheet):
    """None when nothing on `sheet` is out of date, else the names of its out-of-date views (an
    empty list when NX only says the sheet as a whole is out of date)."""
    try:
        views = [view.Name for view in sheet.GetDraftingViews() if _out_of_date(view)]
    except Exception:
        views = []
    return views if views or _out_of_date(sheet) else None


def export_anyway(sheets, stale):
    """Warn that views are out of date (`stale`: stale_views of each of `sheets`) and ask whether to
    export anyway. True means export."""
    listed = "\n".join(sheet.Name + (": " + ", ".join(views) if views else "")
                       for sheet, views in zip(sheets, stale) if views is not None)
    answer = NXOpen.UI.GetUI().NXMessageBox.Show(
        "Export PDF: Views Out of Date", NXOpen.NXMessageBox.DialogType.Question,
        "Some views on this drawing are out of date:\n\n{0}\n\n"
        "The PDF will show them as they are now, not as the model is.\n\n"
        "Export the PDF anyway?\n"
        "Yes: export it.   No: cancel, so you can update the views first.".format(listed))
    return answer == 1          # 1 is Yes, 2 is No


# ----------------------------------------------------------------------------- export
def export_pdf(part, sheets, path):
    """Write `sheets` of the displayed drawing `part` to the PDF file `path`, one page per sheet at
    full scale (each page the size of its sheet). The rest is NX's File > Export > PDF defaults."""
    builder = part.PlotManager.CreatePrintPdfbuilder()
    try:
        builder.Action = NXOpen.PrintPDFBuilder.ActionOption.Native     # a file, not a Teamcenter dataset
        builder.Size = NXOpen.PrintPDFBuilder.SizeOption.FullScale
        builder.Append = False
        builder.AddWatermark = False    # NX's own is off center; pdf_watermark adds one afterwards
        builder.SourceBuilder.SetSheets(sheets)
        builder.Filename = path
        builder.Commit()
    finally:
        builder.Destroy()


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _finished(path):
    """Whether `path` is a complete PDF: it ends with the %%EOF marker."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 1024))
            return b"%%EOF" in f.read()
    except OSError:
        return False


def _wait_until_finished(path):
    """Wait up to _WAIT_SECONDS for NX to finish writing `path`; True once it has."""
    deadline = time.time() + _WAIT_SECONDS
    while not _finished(path):
        if time.time() >= deadline:
            return False
        time.sleep(0.2)
    return True


def export_to_file(part, sheets, path, write):
    """Export `sheets` to `path` with the watermark on every page, replacing an older file of that
    name, and report through write(line). Returns True when the PDF was written."""
    old = path + ".old"
    replacing = os.path.isfile(path)
    if replacing:
        try:
            os.replace(path, old)       # kept until the new file is there
        except OSError as ex:
            write("Could not replace {0} ({1}). If it is open in a PDF viewer, close it and try "
                  "again.".format(path, ex.strerror or ex))
            return False

    error = None
    try:
        export_pdf(part, sheets, path)
    except Exception as ex:
        error = ex

    problem, pages = None, 0
    if not (_finished(path) if error else _wait_until_finished(path)):
        problem = "NX did not write {0}{1}".format(path, ": {0}".format(error) if error else ".")
    elif WATERMARK:
        try:
            pages = pdf_watermark.add_watermark(path, WATERMARK)
        except Exception as ex:
            problem = "Could not add the {0} watermark, so the PDF was not kept: {1}".format(WATERMARK, ex)

    if problem:
        write(problem)
        _remove(path)                   # nothing, an empty file, or a PDF without its watermark
        if os.path.exists(path):
            write("  Delete {0} by hand: it has no watermark.".format(path))
        if replacing:
            try:
                os.replace(old, path)   # put the older file back
            except OSError:
                write("The older file is kept as " + old)
        return False

    if replacing:
        _remove(old)
    write("Exported {0}".format(path))
    if WATERMARK:
        write("  {0} watermark on {1}".format(
            WATERMARK, "the page" if pages == 1 else "all {0} pages".format(pages)))
    if replacing:
        write("  (replaced the older file of the same name)")
    if error:
        write("  NX also reported: {0}".format(error))
    return True


# ----------------------------------------------------------------------------- main
def main(args):
    session = NXOpen.Session.GetSession()
    lw = session.ListingWindow
    lw.Open()
    part = session.Parts.Display
    if part is None:
        lw.WriteLine("No part is displayed. Open the drawing first.")
        return

    sheets = sheets_in_order(part)
    if not sheets:
        lw.WriteLine("{0} has no drawing sheets, so nothing was exported. Open the drawing and try "
                     "again.".format(part.Leaf))
        return

    stale = [stale_views(sheet) for sheet in sheets]
    lw.WriteLine("Exporting {0} of {1} to PDF ...".format(
        "1 sheet" if len(sheets) == 1 else "{0} sheets".format(len(sheets)), part.Leaf))
    for page, (sheet, views) in enumerate(zip(sheets, stale), 1):
        lw.WriteLine("  page {0}: {1}, {2}{3}".format(
            page, sheet.Name, sheet_size(sheet),
            "" if views is None else "  (out of date{0})".format(": " + ", ".join(views) if views else "")))
    if any(views is not None for views in stale) and not export_anyway(sheets, stale):
        lw.WriteLine("Cancelled: nothing was exported. Update the out-of-date views, then run Export PDF "
                     "again.")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    export_to_file(part, sheets, os.path.join(OUTPUT_DIR, pdf_file_name(part)), lw.WriteLine)


if __name__ == '__main__':
    main(sys.argv[1:])
