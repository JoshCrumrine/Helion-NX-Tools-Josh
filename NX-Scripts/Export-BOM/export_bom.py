# NX 2506
# Author:  jo388c
# Created: 2026-10-30
# Exports the bill of materials (BOM) of the displayed assembly to an Excel file in the repo's
# output\bom folder, in one click: part number, revision, name, quantity, material and Teamcenter
# release status of every part in it.
#
# Two sheets:
#   BOM        one row per part with its total quantity in the whole assembly, by part number
#   Structure  the assembly tree: the displayed assembly, then each part under its parent with the
#              quantity per parent, indented by level
# Suppressed and reference-only components (and everything under them) are left out. A part that is
# only partially loaded is loaded fully so its materials can be read; nothing in it changes, and any
# component reference set that loading switches (to Entire Part, say) is put back afterwards. For a
# component whose part is not loaded at all, the name comes from Teamcenter and the material and
# release status say "not loaded".
#
# The file is named <part number>.<revision>-BOM.xlsx; a file of that name already in output\bom is
# replaced (close it in Excel first). It opens in Excel when done. Nothing in the assembly changes
# and nothing is saved.
#
# Run it from a button (see README.md), or File -> Execute -> NX Open... with the assembly displayed.
#
# Self-contained on purpose (no lib/ imports): NX re-reads this file on every run, so a change to it
# works on the next click without restarting NX.
import os
import re
import sys
import zipfile
from xml.sax.saxutils import escape

import NXOpen
import NXOpen.Assemblies
import NXOpen.UF          # NX only creates NXOpen.UF once it is imported explicitly

OPEN_WHEN_DONE = True       # open the file in Excel after exporting
UNRELEASED = "Unreleased"   # shown when Teamcenter has no release status for the part
NOT_LOADED = "not loaded"   # material and status of a part that is not loaded in NX

# <repo>\output\bom: this file is <repo>\NX-Scripts\Export-BOM\export_bom.py
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(_REPO, "output", "bom")

COLUMNS = ("PN", "Rev", "Name", "QTY", "Material", "Release Status")
_UNSAFE = r'[\\/:*?"<>|\x00-\x1f]'      # characters Windows does not allow in file names


# ----------------------------------------------------------------------------- one part
def _string_attribute(part, title):
    """The string attribute `title` of `part`, or "" if it is missing or cannot be read."""
    try:
        if part.HasUserAttribute(title, NXOpen.NXObject.AttributeType.String, -1):
            return part.GetStringUserAttribute(title, -1).strip()
    except Exception:
        pass
    return ""


def decode_name(name):
    """(part number, revision) in an NX part name: "@DB/1150201-500/01" (a Teamcenter part file),
    "1150201-500/01" (a display name) or a native file path (its file name, no revision)."""
    name = (name or "").strip()
    if name.startswith("@DB/"):
        try:
            decoded = NXOpen.UF.UFSession.GetUFSession().Ugmgr.DecodePartFileName(name)
            if decoded[0]:
                return decoded[0].strip(), (decoded[1] or "").strip()
        except Exception:
            pass
        name = name[len("@DB/"):]
    if "\\" in name or name.lower().endswith(".prt"):
        return os.path.splitext(os.path.basename(name))[0], ""
    number, _, rest = name.partition("/")
    rest = rest.strip()
    return number.strip(), (re.split(r"[\s/]", rest, 1)[0] if rest else "")


def _prototype(component):
    try:
        return component.Prototype          # None while the component's part is not loaded
    except Exception:
        return None


def _names_of(component):
    """The names that identify a component's part: its part's name, the component's display name and
    the part file name the assembly stores. Some cannot be read while the part is not loaded."""
    readers = (lambda: component.Prototype.Leaf, lambda: component.DisplayName,
               lambda: NXOpen.UF.UFSession.GetUFSession().Assem.AskComponentData(component.Tag)[0])
    for read in readers:
        try:
            name = read()
        except Exception:
            continue
        if name:
            yield name


def identity(component=None, part=None):
    """(part number, revision) of a component's part (or of `part`), loaded or not: the DB_PART_NO and
    DB_PART_REV attributes, else what its names say."""
    part = part if part is not None else _prototype(component)
    number = _string_attribute(part, "DB_PART_NO") if part is not None else ""
    rev = _string_attribute(part, "DB_PART_REV") if part is not None else ""
    names = _names_of(component) if component is not None else iter([getattr(part, "Leaf", "")])
    for name in names:
        if number and rev:
            break
        n, r = decode_name(name)
        number, rev = number or n, rev or r
    return number or "?", rev


def _teamcenter_name(number):
    """Name of item `number` in Teamcenter, or "" (the part need not be loaded)."""
    try:
        ugmgr = NXOpen.UF.UFSession.GetUFSession().Ugmgr
        database_tag = ugmgr.AskPartTag(number)
        if not database_tag:
            return ""
        name = ugmgr.AskPartNameDesc(database_tag)[0]
        if isinstance(name, (list, tuple)):     # NX documents this output as a list of str
            name = "".join(name)
        return (name or "").strip()
    except Exception:
        return ""


def _materials(part, notes):
    """The materials of the part's solid bodies, in body order: "Aluminum 6061", "Aluminum 6061,
    Copper", "(no material)" for a body without one, "" when the part has no solid body."""
    try:
        if not part.IsFullyLoaded:
            status = part.LoadThisPartFully()       # partial loading leaves out the bodies' data
            try:
                status.Dispose()
            except Exception:
                pass
            notes["loaded fully"].append(part.Leaf)
    except Exception as ex:
        notes["load failed"].append("{0}: {1}".format(part.Leaf, ex))
        return "?"
    found = []
    try:
        for body in part.Bodies:
            if not body.IsSolidBody:
                continue
            material = part.MaterialManager.PhysicalMaterials.AskMaterialOfObject(body)
            found.append(material.Name if material is not None else "(no material)")
    except Exception as ex:
        notes["load failed"].append("{0}: {1}".format(part.Leaf, ex))
        return "?"
    if "(no material)" in found:
        notes["no material"].append(part.Leaf)
    return ", ".join(dict.fromkeys(found))


def _release_status(part):
    """The part's Teamcenter release status, UNRELEASED when it has none, "?" if NX cannot say."""
    try:
        status = part.PDMPart.GetReleaseStatus()
    except Exception:
        return "?"
    return (status or "").strip() or UNRELEASED


# ----------------------------------------------------------------------------- the assembly
def _reference_value(display_part, components):
    builder = display_part.PropertiesManager.CreateAssembliesGeneralPropertiesBuilder(components)
    try:
        return builder.ReferenceComponent           # read only: the builder is never committed
    finally:
        builder.Destroy()


def reference_only(display_part, components):
    """Tags of the reference-only components among `components`, as Edit > Properties shows them. One
    question covers them all in the usual case (none is); "Mixed" means each one is asked."""
    options = NXOpen.Assemblies.AssembliesGeneralPropertiesBuilder.ReferenceComponentOptions
    try:
        value = _reference_value(display_part, components)
        if value == options.No:
            return set()
        if value == options.Yes:
            return {c.Tag for c in components}
        return {c.Tag for c in components if _reference_value(display_part, [c]) == options.Yes}
    except Exception:
        return set()                                # NX cannot tell: count them all


def _by_path(root):
    """[(path, component)] for every component under `root`, parents before children. A path is the
    JournalIdentifiers from the top, so it still finds a component whose object NX has rebuilt."""
    found = []

    def walk(parent, path):
        for child in parent.GetChildren():
            here = path + (child.JournalIdentifier,)
            found.append((here, child))
            walk(child, here)
    walk(root, ())
    return found


def reference_sets(root):
    """{path: reference set} of the components under `root` whose reference set NX can read."""
    sets = {}
    for path, component in _by_path(root):
        try:
            if not component.IsSuppressed:
                sets[path] = component.ReferenceSet
        except Exception:
            pass
    return sets


def restore_reference_sets(display_part, root, before):
    """Put back the reference sets in `before` (from reference_sets) that have changed since: loading
    a part fully can switch its components to Entire Part. Parents go first, so a child is set after
    whatever its parent's change did to it. Returns (number put back, [errors])."""
    levels = {}                 # depth -> {reference set: [components]}
    for path, component in _by_path(root):
        name = before.get(path)
        try:
            if name and component.ReferenceSet != name:
                levels.setdefault(len(path), {}).setdefault(name, []).append(component)
        except Exception:
            pass
    restored, errors = 0, []
    assembly = display_part.ComponentAssembly
    for depth in sorted(levels):
        for name, components in levels[depth].items():
            try:
                result = assembly.ReplaceReferenceSetInOwners(name, components)
                try:
                    result.Dispose()
                except Exception:
                    pass
                restored += len(components)
            except Exception as ex:
                errors.append("{0} ({1} components): {2}".format(name, len(components), ex))
    return restored, errors


class Bom:
    """The parts of the displayed assembly: each distinct part once (its number, revision, name,
    material and release status), its total quantity, and the tree for the Structure sheet."""

    def __init__(self, display_part):
        self.display_part = display_part
        self.parts = {}             # key -> {"number", "rev", "name", "material", "status"}
        self.quantity = {}          # key -> total count in the whole assembly
        self.tree = []              # (level, key, quantity under its parent), the Structure rows
        self.excluded = {"suppressed": 0, "reference-only": 0}
        self.notes = {"loaded fully": [], "not loaded": [], "no material": [], "load failed": [],
                      "reference sets": []}
        self.restored = 0           # components whose reference set was put back
        root = display_part.ComponentAssembly.RootComponent
        components = [c for c in self._walk(root) if not c.IsSuppressed] if root is not None else []
        self._reference = reference_only(display_part, components) if components else set()
        before = reference_sets(root) if root is not None else {}
        try:
            self.tree.append((0, self._describe(None, display_part), 1))
            if root is not None:
                self._count(root)
                self._branch(root, 1)
        finally:
            if before:
                self.restored, self.notes["reference sets"] = restore_reference_sets(
                    display_part, root, before)

    @staticmethod
    def _walk(parent):
        for child in parent.GetChildren():
            yield child
            for below in Bom._walk(child):
                yield below

    def _left_out(self, component):
        """Why `component` (and all under it) is not in the BOM: "suppressed", "reference-only", or None."""
        if component.IsSuppressed:
            return "suppressed"
        if component.Tag in self._reference:
            return "reference-only"
        return None

    def _describe(self, component, part=None):
        """The key of a component's part (or of `part`), describing it the first time it is seen."""
        if part is None:
            part = _prototype(component)
        number, rev = identity(component, part)
        key = (number.upper(), rev.upper())
        if key not in self.parts:
            name = _string_attribute(part, "DB_PART_NAME") if part is not None else ""
            if part is None:
                self.notes["not loaded"].append("{0}/{1}".format(number, rev) if rev else number)
            self.parts[key] = {
                "number": number, "rev": rev,
                "name": name or (_teamcenter_name(number) if number != "?" else ""),
                "material": _materials(part, self.notes) if part is not None else NOT_LOADED,
                "status": _release_status(part) if part is not None else NOT_LOADED}
        return key

    def _count(self, parent):
        """Count every component under `parent`, instance by instance, for the total quantities."""
        for child in parent.GetChildren():
            why = self._left_out(child)
            if why:
                self.excluded[why] += 1
                continue
            key = self._describe(child)
            self.quantity[key] = self.quantity.get(key, 0) + 1
            self._count(child)

    def _branch(self, parent, level):
        """The Structure rows under `parent`: one per distinct part with its count under this parent,
        then what is under the first of those components."""
        groups = {}                 # key -> [components], in tree order
        for child in parent.GetChildren():
            if not self._left_out(child):
                groups.setdefault(self._describe(child), []).append(child)
        for key, components in groups.items():
            self.tree.append((level, key, len(components)))
            self._branch(components[0], level + 1)

    def row(self, key):
        part = self.parts[key]
        return [part["number"], part["rev"], part["name"], self.quantity.get(key, 1),
                part["material"], part["status"]]

    def bom_rows(self):
        """One row per part (the displayed assembly itself left out), by part number then revision."""
        def order(key):
            return self.parts[key]["number"].upper(), self.parts[key]["rev"].upper()
        return [self.row(key) for key in sorted(self.quantity, key=order)]

    def structure_rows(self):
        """[(level, row)] in tree order, the quantity being per parent."""
        rows = []
        for level, key, count in self.tree:
            row = self.row(key)
            row[3] = count
            rows.append((level, row))
        return rows


# ----------------------------------------------------------------------------- the Excel file
_NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
_INDENT_STYLE = 2           # cell style of indent level 1; level n is style 1 + n
_MAX_INDENT = 15


def _column(index):
    """Excel's name of column `index` (0 -> A, 26 -> AA)."""
    name, index = "", index + 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def _cell(ref, value, style=0):
    style_text = ' s="{0}"'.format(style) if style else ""
    if value is None or value == "":
        return '<c r="{0}"{1}/>'.format(ref, style_text) if style else ""
    if isinstance(value, int) and not isinstance(value, bool):
        return '<c r="{0}"{1}><v>{2}</v></c>'.format(ref, style_text, value)
    text = escape(_NOT_XML.sub("", str(value)))
    keep = ' xml:space="preserve"' if text != text.strip() else ""
    return '<c r="{0}"{1} t="inlineStr"><is><t{2}>{3}</t></is></c>'.format(ref, style_text, keep, text)


def _sheet_xml(columns, rows, indents=None, indent_column=None):
    """A worksheet: bold header row (frozen, with filters) over `rows`; text stays text, so revision
    "01" is not turned into 1. `indents` gives each row's indent for column `indent_column`."""
    widths = []
    for i, title in enumerate(columns):
        lengths = [len(str(row[i])) + (2 * indents[r] if indents and i == indent_column else 0)
                   for r, row in enumerate(rows) if row[i] is not None]
        widths.append(min(70, max(len(str(title)) + 5, max(lengths or [0]) + 2)))  # + 5: the filter arrow
    last = _column(len(columns) - 1)
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           '<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>',       # prints one page wide
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
           'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>',
           '<sheetFormatPr defaultRowHeight="15"/><cols>']
    out += ['<col min="{0}" max="{0}" width="{1}" customWidth="1"/>'.format(i + 1, w)
            for i, w in enumerate(widths)]
    out.append('</cols><sheetData><row r="1">')
    out += [_cell("{0}1".format(_column(i)), title, 1) for i, title in enumerate(columns)]
    out.append('</row>')
    for r, row in enumerate(rows, 2):
        out.append('<row r="{0}">'.format(r))
        for i, value in enumerate(row):
            style = 0
            if indents and i == indent_column and indents[r - 2]:
                style = _INDENT_STYLE - 1 + min(indents[r - 2], _MAX_INDENT)
            out.append(_cell("{0}{1}".format(_column(i), r), value, style))
        out.append('</row>')
    out.append('</sheetData><autoFilter ref="A1:{0}{1}"/>'.format(last, len(rows) + 1))
    out.append('<pageMargins left="0.5" right="0.5" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
               '<pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/></worksheet>')
    return "".join(out)


def _styles_xml():
    indents = "".join('<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
                      '<alignment indent="{0}"/></xf>'.format(n) for n in range(1, _MAX_INDENT + 1))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="3"><fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="gray125"/></fill>'
            '<fill><patternFill patternType="solid"><fgColor rgb="FFD9E1F2"/><bgColor indexed="64"/>'
            '</patternFill></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="{0}"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
            '{1}</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/>'
            '</cellStyles></styleSheet>').format(2 + _MAX_INDENT, indents)


def write_xlsx(path, sheets):
    """Write an Excel workbook: `sheets` is [(name, columns, rows, indents or None, indent column)]."""
    ns_rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ns_package = "http://schemas.openxmlformats.org/package/2006/relationships"
    head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    types = (head + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" '
             'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
             'officedocument.spreadsheetml.sheet.main+xml"/>'
             '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-'
             'officedocument.spreadsheetml.styles+xml"/>'
             + "".join('<Override PartName="/xl/worksheets/sheet{0}.xml" ContentType="application/'
                       'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'.format(i)
                       for i in range(1, len(sheets) + 1)) + '</Types>')
    package_rels = (head + '<Relationships xmlns="{0}">'
                    '<Relationship Id="rId1" Type="{1}/officeDocument" Target="xl/workbook.xml"/>'
                    '</Relationships>').format(ns_package, ns_rel)
    workbook = (head + '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="{0}"><sheets>'.format(ns_rel)
                + "".join('<sheet name="{0}" sheetId="{1}" r:id="rId{1}"/>'.format(escape(name), i)
                          for i, (name, _c, _r, _i, _ic) in enumerate(sheets, 1)) + '</sheets></workbook>')
    workbook_rels = (head + '<Relationships xmlns="{0}">'.format(ns_package)
                     + "".join('<Relationship Id="rId{0}" Type="{1}/worksheet" '
                               'Target="worksheets/sheet{0}.xml"/>'.format(i, ns_rel)
                               for i in range(1, len(sheets) + 1))
                     + '<Relationship Id="rId{0}" Type="{1}/styles" Target="styles.xml"/>'
                       '</Relationships>'.format(len(sheets) + 1, ns_rel))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types.encode("utf-8"))
        z.writestr("_rels/.rels", package_rels.encode("utf-8"))
        z.writestr("xl/workbook.xml", workbook.encode("utf-8"))
        z.writestr("xl/_rels/workbook.xml.rels", workbook_rels.encode("utf-8"))
        z.writestr("xl/styles.xml", _styles_xml().encode("utf-8"))
        for i, (_name, columns, rows, indents, indent_column) in enumerate(sheets, 1):
            z.writestr("xl/worksheets/sheet{0}.xml".format(i),
                       _sheet_xml(columns, rows, indents, indent_column).encode("utf-8"))


def bom_file_name(display_part):
    """"<number>.<revision>-BOM.xlsx" for the displayed assembly."""
    number, rev = identity(part=display_part)
    stem = re.sub(_UNSAFE, "_", number + ("." + rev if rev else "")).strip(" .") or "assembly"
    return stem + "-BOM.xlsx"


def save_workbook(bom, path, write):
    """Write the two sheets to `path`, replacing an older file of that name. Returns True if done."""
    temp = path + ".writing"
    structure = bom.structure_rows()
    sheets = [("BOM", COLUMNS, bom.bom_rows(), None, None),
              ("Structure", ("Level",) + COLUMNS, [[level] + row for level, row in structure],
               [level for level, _row in structure], 1)]
    try:
        write_xlsx(temp, sheets)
        os.replace(temp, path)
    except OSError as ex:
        try:
            os.remove(temp)
        except OSError:
            pass
        write("Could not write {0} ({1}). If it is open in Excel, close it and try again.".format(
            path, ex.strerror or ex))
        return False
    return True


# ----------------------------------------------------------------------------- main
def _list(write, title, names, limit=10):
    if names:
        shown = ", ".join(names[:limit])
        if len(names) > limit:
            shown += ", ... ({0} more)".format(len(names) - limit)
        write("  {0} ({1}): {2}".format(title, len(names), shown))


def main(args):
    session = NXOpen.Session.GetSession()
    lw = session.ListingWindow
    lw.Open()
    part = session.Parts.Display
    if part is None:
        lw.WriteLine("No part is displayed. Open the assembly first.")
        return
    root = part.ComponentAssembly.RootComponent
    if root is None or not root.GetChildren():
        lw.WriteLine("{0} has no components, so there is no BOM to export. Open the assembly and try "
                     "again.".format(part.Leaf))
        return

    lw.WriteLine("Reading the BOM of {0} ...".format(part.Leaf))
    bom = Bom(part)
    rows = bom.bom_rows()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, bom_file_name(part))
    if not save_workbook(bom, path, lw.WriteLine):
        return
    lw.WriteLine("Exported {0}".format(path))
    lw.WriteLine("  {0} parts, {1} components in all".format(len(rows), sum(row[3] for row in rows)))
    left_out = ["{0} {1}".format(n, what) for what, n in bom.excluded.items() if n]
    if left_out:
        lw.WriteLine("  Left out: {0} components".format(" and ".join(left_out)))
    _list(lw.WriteLine, "Loaded fully to read their materials", bom.notes["loaded fully"])
    _list(lw.WriteLine, "Not loaded, so material and status are not known (load them and export again)",
          bom.notes["not loaded"])
    _list(lw.WriteLine, "With a body that has no material", bom.notes["no material"])
    _list(lw.WriteLine, "Could not be read", bom.notes["load failed"])
    if bom.restored:
        lw.WriteLine("  Reference sets put back on {0} component(s) (loading parts fully had changed "
                     "them)".format(bom.restored))
    _list(lw.WriteLine, "Could not put back the reference set", bom.notes["reference sets"])
    if OPEN_WHEN_DONE:
        try:
            os.startfile(path)
        except Exception as ex:
            lw.WriteLine("  (Could not open it in Excel: {0})".format(ex))


if __name__ == '__main__':
    main(sys.argv[1:])
