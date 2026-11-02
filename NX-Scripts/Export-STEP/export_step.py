# NX 2506
# Author:  jo388c
# Created: 2026-10-29
# Exports the displayed part to a STEP file (AP214) in the repo's output\step folder, with a copy in
# U:\7 - 3D Prints, in one click.
#
# Made for single-body parts: it exports the solid bodies in the part's MODEL reference set (there
# should be just one), as File > Export > STEP does with "Selected Objects" and that body picked.
# The file is named <part number>.<revision>-UNRELEASED.stp, e.g. 1152103-001.01-UNRELEASED.stp, as
# Export-PDF and Export-Body-DXF name theirs; a file of that name already in output\step is replaced.
# The copy in U:\7 - 3D Prints (PRINT_COPY_DIR) never replaces one already there: a name that is
# taken there gets _2, _3, ... Export-Body-DXF writes to output\dxf beside output\step. Nothing in
# the part changes and nothing is saved.
#
# Run it from a button (see README.md), or File -> Execute -> NX Open... and pick this file. The
# Listing Window says what was written and whether NX's STEP translator reported a problem. The
# translator's .log is deleted after a clean translation and kept next to the .stp otherwise.
#
# Self-contained on purpose (no lib/ imports): NX re-reads this file on every run, so a change to it
# works on the next click without restarting NX.
import os
import re
import shutil
import sys
import time

import NXOpen

PROTOCOL = "AP214"          # STEP version written: "AP214", "AP242" or "AP203"
REFERENCE_SET = "MODEL"     # the solid bodies in this reference set are exported
SUFFIX = "UNRELEASED"       # file name <part number>.<revision>-UNRELEASED.stp; "" for none
PRINT_COPY_DIR = r"U:\7 - 3D Prints"    # a copy of each STEP file goes here too; "" for none
_WAIT_SECONDS = 30          # how long to wait for the file if the translator is still running

# <repo>\output\step: this file is <repo>\NX-Scripts\Export-STEP\export_step.py
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(_REPO, "output", "step")

_UNSAFE = r'[\\/:*?"<>|\x00-\x1f]'      # characters Windows does not allow in file names

# STEP version -> (StepCreator.ExportAsOption member, NX variable naming the translator folder, that
# folder under UGII_BASE_DIR, its settings file). File > Export > STEP uses the same settings files.
_PROTOCOLS = {
    "AP203": ("Ap203", "STEP203UG_DIR", "step203ug", "ugstep203.def"),
    "AP214": ("Ap214", "STEP214UG_DIR", "step214ug", "ugstep214.def"),
    "AP242": ("Ap242", "STEP242_DIR", os.path.join("translators", "step242"), "ugstep242.def"),
}

# The solid counts at the end of the translator's .log
_LOG_COUNTS = (
    ("input", "Total number of solids input for this translation"),
    ("clean", "Number of solids processed without problems"),
    ("as_sheets", "Number of solids with problems output as sheets"),
    ("not_processed", "Number of solids not processed"),
)


# ----------------------------------------------------------------------------- what
def _string_attribute(part, title):
    """The string attribute `title` of `part`, or "" if it is missing or cannot be read."""
    try:
        if part.HasUserAttribute(title, NXOpen.NXObject.AttributeType.String, -1):
            return part.GetStringUserAttribute(title, -1).strip()
    except Exception:
        pass
    return ""


def step_file_name(part):
    """"<number>.<revision>-UNRELEASED.stp", as Export-PDF and Export-Body-DXF name their files.

    Number and revision are the DB_PART_NO and DB_PART_REV attributes, falling back to the part
    name ("1152103-001/01"). Characters Windows does not allow in file names become "_". A part that
    is not in Teamcenter keeps its own name: bracket.prt -> bracket-UNRELEASED.stp.
    """
    leaf_number, _, leaf_rev = str(part.Leaf or "").partition("/")
    number = _string_attribute(part, "DB_PART_NO") or leaf_number.strip()
    rev = _string_attribute(part, "DB_PART_REV") or leaf_rev.strip()
    stem = re.sub(_UNSAFE, "_", number + ("." + rev if rev else "")).strip(" .") or "part"
    if SUFFIX:
        stem += "-" + re.sub(_UNSAFE, "_", SUFFIX).strip(" .")
    return stem + ".stp"


def find_reference_set(part, name):
    """The part's reference set called `name` (in any case), or None."""
    for refset in part.GetAllReferenceSets():
        if (refset.Name or "").strip().upper() == name.upper():
            return refset
    return None


def settings_file(protocol):
    """NX's settings file for the STEP version, the one File > Export > STEP uses; "" if missing."""
    _, variable, folder, name = _PROTOCOLS[protocol]
    base = os.environ.get(variable) or os.path.join(os.environ.get("UGII_BASE_DIR", ""), folder)
    path = os.path.join(base, name)
    return path if os.path.isfile(path) else ""


def _input_file(part):
    """The exporter's InputFile: "@DB/<number>/<rev>" for a Teamcenter part (as NX records it for
    File > Export, see example_journals/journal_export_dxf.py), otherwise the part's file path."""
    leaf = str(part.Leaf or "")
    return "@DB/" + leaf if "/" in leaf else str(part.FullPath)


# ----------------------------------------------------------------------------- export
def export_step(session, part, bodies, path, protocol=PROTOCOL):
    """Write `bodies` of the displayed `part` to the STEP file `path`.

    The settings are those of File > Export > STEP as used at Helion: displayed part, selected
    objects, solids only, absolute coordinates, written to the file system (the dialog starts on
    Teamcenter). Returns when the translator is done (ProcessHoldFlag).
    """
    creator = session.DexManager.CreateStepCreator()
    try:
        settings = settings_file(protocol)
        if settings:
            creator.SettingsFile = settings     # first: it loads defaults that the lines below override
        creator.ExportAs = getattr(NXOpen.StepCreator.ExportAsOption, _PROTOCOLS[protocol][0])
        creator.ExportFrom = NXOpen.StepCreator.ExportFromOption.DisplayPart
        creator.InputFile = _input_file(part)
        creator.ExportDestination = NXOpen.BaseCreator.ExportDestinationOption.NativeFileSystem
        creator.OutputFile = path
        creator.ExportSelectionBlock.SelectionScope = NXOpen.ObjectSelector.Scope.SelectedObjects
        for body in bodies:
            creator.ExportSelectionBlock.SelectionComp.Add(body)      # one object per call, as recorded
        creator.ObjectTypes.Solids = True
        creator.ReferenceType = NXOpen.StepCreator.CsysrefEnum.Absolute
        creator.LayerMask = "1-256"
        creator.FileSaveFlag = False
        creator.ProcessHoldFlag = True
        creator.Commit()
    finally:
        creator.Destroy()


def read_translator_log(path):
    """(counts, errors, warnings, finished) from the STEP translator's .log: the solid counts it ends
    with (keys of _LOG_COUNTS), its error and warning lines, and whether it reached its end."""
    counts, errors, warnings, finished = {}, [], [], False
    try:
        with open(path, encoding="utf-8", errors="replace") as log:
            for line in log:
                text = line.strip()
                kind = text[2:].split("-", 1)[0].strip().upper() if text.startswith("! ") else ""
                if kind in ("ERROR", "SEVERE", "FATAL"):
                    errors.append(text)
                elif kind == "WARNING":
                    warnings.append(text)
                if "End of Translation" in text:
                    finished = True
                for key, label in _LOG_COUNTS:
                    if label in text:
                        try:
                            counts[key] = int(text.rsplit(":", 1)[1])
                        except ValueError:
                            pass
    except OSError:
        pass
    return counts, errors, warnings, finished


def translation_problems(log_path, expected):
    """What the translator's log shows went wrong when `expected` solids were sent; [] if nothing."""
    if not os.path.isfile(log_path):
        return ["the translator wrote no log, so the result could not be checked"]
    counts, errors, warnings, finished = read_translator_log(log_path)
    problems = errors[:5]
    if not finished:
        problems.append("the translator's log stops before the end of the translation")
    if counts.get("input", expected) != expected:
        problems.append("only {0} of {1} reached the translator (it leaves hidden bodies out)".format(
            counts["input"], _solids(expected)))
    if counts.get("as_sheets"):
        problems.append("{0} had problems and became sheets".format(_solids(counts["as_sheets"])))
    if counts.get("not_processed"):
        problems.append("{0} not translated".format(_solids(counts["not_processed"])))
    if warnings:
        problems.append("{0} warning{1} in the translator's log".format(
            len(warnings), "" if len(warnings) == 1 else "s"))
    return problems


def _solids(count):
    return "{0} solid{1}".format(count, "" if count == 1 else "s")


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def export_to_file(session, part, bodies, path, write):
    """Export `bodies` to `path`, replacing an older file of that name, and report through
    write(line). Returns True when the STEP file was written."""
    log_path = os.path.splitext(path)[0] + ".log"   # where the translator writes its log
    old = path + ".old"
    replacing = os.path.isfile(path)
    if replacing:
        try:
            os.replace(path, old)       # kept until the new file is there
        except OSError as ex:
            write("Could not replace {0} ({1}). If it is open in another program, close it and "
                  "try again.".format(path, ex.strerror or ex))
            return False
    _remove(log_path)                   # from an earlier export to the same name

    error = None
    try:
        export_step(session, part, bodies, path)
    except Exception as ex:
        error = ex
    # Normally the file is there already (Commit waits for the translator); give it a moment if not.
    deadline = time.time() + _WAIT_SECONDS
    while (error is None and not os.path.isfile(path) and time.time() < deadline
           and not read_translator_log(log_path)[3]):
        time.sleep(0.25)

    if not os.path.isfile(path):
        write("NX did not write {0}{1}".format(path, ": {0}".format(error) if error else "."))
        if os.path.isfile(log_path):
            write("The translator's log may say why: " + log_path)
        if replacing:
            try:
                os.replace(old, path)   # put the older file back
            except OSError:
                write("The older file is kept as " + old)
        return False

    if replacing:
        _remove(old)
    write("Exported {0}".format(path))
    if replacing:
        write("  (replaced the older file of the same name)")
    problems = translation_problems(log_path, len(bodies))
    if problems:
        write("  Check the file: " + "; ".join(problems) + ".")
        if os.path.isfile(log_path):
            write("  The translator's log: " + log_path)
    else:
        write("  The translator processed {0} without problems.".format(_solids(len(bodies))))
        _remove(log_path)
    return True


def copy_for_printing(path, folder, write):
    """Copy the STEP file `path` into `folder` (the 3D-print folder) under its own name, or with _2,
    _3, ... added when that name is taken there, so earlier copies are kept. Reports through
    write(line) and returns the copy's path, or None when no copy was made."""
    if not folder:
        return None
    if not os.path.isdir(folder):
        write("  Not copied to {0}: the folder is not there (is its drive connected?).".format(folder))
        return None
    stem, ext = os.path.splitext(os.path.basename(path))
    target, n = os.path.join(folder, stem + ext), 1
    while os.path.exists(target):
        n += 1
        target = os.path.join(folder, "{0}_{1}{2}".format(stem, n, ext))
    temp = target + ".copying"          # so a broken copy never sits there under the real name
    try:
        shutil.copyfile(path, temp)
        os.replace(temp, target)
    except OSError as ex:
        _remove(temp)
        write("  Not copied to {0}: {1}".format(folder, ex.strerror or ex))
        return None
    write("  Copied to {0}".format(target))
    return target


# ----------------------------------------------------------------------------- main
def main(args):
    session = NXOpen.Session.GetSession()
    lw = session.ListingWindow
    lw.Open()
    part = session.Parts.Display
    if part is None:
        lw.WriteLine("No part is displayed. Open the part first.")
        return

    refset = find_reference_set(part, REFERENCE_SET)
    if refset is None:
        names = ", ".join(r.Name for r in part.GetAllReferenceSets())
        lw.WriteLine("{0} has no {1} reference set, so nothing was exported (its reference sets: "
                     "{2}).".format(part.Leaf, REFERENCE_SET, names or "only Entire Part and Empty"))
        return
    bodies = [m for m in refset.AskAllDirectMembers() if isinstance(m, NXOpen.Body)]
    solids = [b for b in bodies if b.IsSolidBody]
    if not solids:
        lw.WriteLine("The {0} reference set of {1} has no solid body, so nothing was exported."
                     .format(REFERENCE_SET, part.Leaf))
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, step_file_name(part))
    lw.WriteLine("Exporting {0} from the {1} reference set of {2} as STEP {3} ...".format(
        "1 solid body" if len(solids) == 1 else "{0} solid bodies".format(len(solids)),
        REFERENCE_SET, part.Leaf, PROTOCOL))
    if len(bodies) > len(solids):
        lw.WriteLine("  ({0} sheet bod{1} in {2} left out: only solids are exported)".format(
            len(bodies) - len(solids), "y" if len(bodies) - len(solids) == 1 else "ies",
            REFERENCE_SET))
    if export_to_file(session, part, solids, path, lw.WriteLine):
        copy_for_printing(path, PRINT_COPY_DIR, lw.WriteLine)


if __name__ == '__main__':
    main(sys.argv[1:])
