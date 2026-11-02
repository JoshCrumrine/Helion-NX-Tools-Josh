# NX 2506
# Author:  jo388c
# Created: 2026-10-29
# Copies the part number (Teamcenter item ID) of the selected components to the Windows clipboard.
# copy_part_name.py, in this folder, runs the same code to copy their part names instead.
#
# Once installed with Install-Copy-Part-Number.bat (see README.md), this runs when you right-click a
# component in the Assembly Navigator and choose "Copy Part Number", or choose Edit > Copy Part
# Number. It also works without installing anything: select components, then File -> Execute ->
# NX Open... and pick this file.
#
# Several selected components copy one part number per line, each number once, in selection order.
# A selected body, face or edge of a component counts as that component. The number is the part's
# DB_PART_NO attribute; for a component whose part is not loaded it is read from the part name
# ("1150201-500/01" -> "1150201-500"). The status line says what was copied. Nothing in the model
# changes.
#
# Self-contained on purpose (no lib/ imports): NX re-reads this file on every run, so a change to it
# works on the next click without restarting NX.
import ctypes
import os
import sys
import time
from ctypes import wintypes

import NXOpen
import NXOpen.Assemblies
import NXOpen.UF          # NX only creates NXOpen.UF once it is imported explicitly

NUMBER, NAME = "number", "name"         # what copy_selected() copies
PART_NUMBER_ATTRIBUTE = "DB_PART_NO"    # the Teamcenter item ID, kept on every managed part
PART_NAME_ATTRIBUTE = "DB_PART_NAME"    # the Teamcenter item name
_STATUS_LIST_MAX = 5                    # values spelled out on the status line


# ----------------------------------------------------------------------------- part numbers
def number_from_name(name):
    """Item ID in an NX part name, or "".

    "@DB/1150201-500/01" (a Teamcenter part file name) and "1150201-500/01" (its display name) both
    give "1150201-500". A native part file such as C:\\parts\\bracket.prt gives "bracket".
    """
    name = (name or "").strip()
    if name.startswith("@DB/"):
        try:
            number = NXOpen.UF.UFSession.GetUFSession().Ugmgr.DecodePartFileName(name)[0]
            if number:
                return number.strip()
        except Exception:
            pass
        name = name[len("@DB/"):]
    if "\\" in name or name.lower().endswith(".prt"):
        return os.path.splitext(os.path.basename(name))[0]
    return name.split("/")[0].strip()


def _string_attribute(part, title):
    """The string attribute `title` of `part`, or "" if it is missing or cannot be read."""
    try:
        if part.HasUserAttribute(title, NXOpen.NXObject.AttributeType.String, -1):
            return part.GetStringUserAttribute(title, -1).strip()
    except Exception:
        pass
    return ""


def part_number_of_part(part):
    """DB_PART_NO of a loaded part, else the item ID in its name. "" if neither can be read."""
    number = _string_attribute(part, PART_NUMBER_ATTRIBUTE)
    if not number:
        try:
            number = number_from_name(part.Leaf)
        except Exception:
            number = ""
    return number


def _loaded_part_number(component):
    part = component.Prototype          # None while the component's part is not loaded
    return part_number_of_part(part) if part is not None else ""


def _display_name_number(component):
    return number_from_name(component.DisplayName)


def _part_file_number(component):
    part_name = NXOpen.UF.UFSession.GetUFSession().Assem.AskComponentData(component.Tag)[0]
    return number_from_name(part_name)


def part_number_of_component(component):
    """Part number of the component's part, whether or not that part is loaded.

    Tries, in order: the loaded part (DB_PART_NO, then its name), the component's display name
    ("1150201-500/01") and the part file name the assembly stores ("@DB/1150201-500/01").
    """
    for read in (_loaded_part_number, _display_name_number, _part_file_number):
        try:
            number = read(component)
        except Exception:
            number = ""
        if number:
            return number
    return ""


# ----------------------------------------------------------------------------- part names
def _teamcenter_part_name(number):
    """Name of item `number` in Teamcenter, or "". Asks the database, so the part need not be
    loaded."""
    ugmgr = NXOpen.UF.UFSession.GetUFSession().Ugmgr
    database_tag = ugmgr.AskPartTag(number)
    if not database_tag:
        return ""
    name = ugmgr.AskPartNameDesc(database_tag)[0]
    if isinstance(name, (list, tuple)):     # NX documents this output as a list of str
        name = "".join(name)
    return (name or "").strip()


def part_name_of(source, number):
    """Part name of a selected component or part whose part number is `number`, or "".

    The part's DB_PART_NAME attribute when the part is loaded and has one, else the item's name in
    Teamcenter.
    """
    try:
        part = source if isinstance(source, NXOpen.BasePart) else source.Prototype
    except Exception:
        part = None
    name = _string_attribute(part, PART_NAME_ATTRIBUTE) if part is not None else ""
    if not name and number:
        try:
            name = _teamcenter_part_name(number)
        except Exception:           # not in Teamcenter, or NX is not running with Teamcenter
            name = ""
    return name


# ----------------------------------------------------------------------------- selection
def _component_of(obj):
    """The component a selected object stands for: the component itself, or the one a body, face
    or edge occurrence belongs to. None for anything else."""
    if isinstance(obj, NXOpen.Assemblies.Component):
        return obj
    try:
        if obj.IsOccurrence:
            return obj.OwningComponent
    except Exception:           # not an NXObject
        pass
    return None


def _describe(obj):
    try:
        return "{0} {1}".format(type(obj).__name__, obj.JournalIdentifier)
    except Exception:
        return type(obj).__name__


def selected_parts(selection):
    """(parts, skipped) for NX's current selection.

    parts: (part number, selected component or part), one per part number, in selection order.
    skipped: one line per selected object that gave no part number (not a component, or its number
    could not be read).
    """
    parts, numbers, skipped = [], set(), []
    for i in range(selection.GetNumSelectedObjects()):
        obj = selection.GetSelectedTaggedObject(i)
        source = _component_of(obj)
        if source is not None:
            number = part_number_of_component(source)
        elif isinstance(obj, NXOpen.BasePart):          # e.g. the top node of the navigator
            source, number = obj, part_number_of_part(obj)
        else:
            skipped.append("{0}: not a component".format(_describe(obj)))
            continue
        if not number:
            skipped.append("{0}: no part number found".format(_describe(obj)))
        elif number not in numbers:
            numbers.add(number)
            parts.append((number, source))
    return parts, skipped


def selected_values(selection, what):
    """(values, skipped): the part numbers (what=NUMBER) or part names (what=NAME) of the selected
    parts, in the order selected_parts() gives them. skipped: one line per object or part left out.
    """
    parts, skipped = selected_parts(selection)
    if what == NUMBER:
        return [number for number, source in parts], skipped
    names = []
    for number, source in parts:
        name = part_name_of(source, number)
        if name:
            names.append(name)
        else:
            skipped.append("{0}: no part name found".format(number))
    return names, skipped


# ----------------------------------------------------------------------------- clipboard
_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002
_HWND_MESSAGE = -3      # parent for an invisible, message-only window


def _win32():
    """user32 and kernel32 with the signatures used here. Private copies, so NX's shared Python
    (ctypes.windll) is left as it was."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                       wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                       wintypes.HINSTANCE, wintypes.LPVOID]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    return user32, kernel32


def copy_to_clipboard(text):
    """Put `text` on the Windows clipboard as Unicode text. Raises OSError if Windows refuses.

    Windows needs a window to own the clipboard (with none, SetClipboardData may fail), so a hidden
    message-only window is made for the moment and destroyed again.
    """
    user32, kernel32 = _win32()
    data = (text + "\0").encode("utf-16-le")
    hwnd = user32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, _HWND_MESSAGE, None, None, None)
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        # Another program can hold the clipboard for a moment; keep trying for half a second.
        deadline = time.time() + 0.5
        while not user32.OpenClipboard(hwnd):
            if time.time() > deadline:
                raise OSError("The clipboard is in use by another program. Try again.")
            time.sleep(0.01)
        try:
            if not user32.EmptyClipboard():
                raise ctypes.WinError(ctypes.get_last_error())
            handle = kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(data))
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            buffer = kernel32.GlobalLock(handle)
            if not buffer:
                kernel32.GlobalFree(handle)
                raise ctypes.WinError(ctypes.get_last_error())
            ctypes.memmove(buffer, data, len(data))
            kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(_CF_UNICODETEXT, handle):
                kernel32.GlobalFree(handle)     # Windows only takes ownership on success
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            user32.CloseClipboard()
    finally:
        user32.DestroyWindow(hwnd)


# ----------------------------------------------------------------------------- main
def _summary(values, noun):
    """Status line text for the copied values, e.g. "Copied part number 1050105-020"."""
    if len(values) == 1:
        return "Copied {0} {1}".format(noun, values[0])
    # Part names often hold commas ("SCREW, HEX"); list them with semicolons then
    separator = "; " if any("," in value for value in values) else ", "
    shown = separator.join(values[:_STATUS_LIST_MAX])
    if len(values) > _STATUS_LIST_MAX:
        shown += "{0}... ({1} more)".format(separator, len(values) - _STATUS_LIST_MAX)
    return "Copied {0} {1}s: {2}".format(len(values), noun, shown)


def copy_selected(what):
    """Copy the part number (what=NUMBER) or part name (what=NAME) of each selected part to the
    clipboard, one per line, and say on the status line what was copied."""
    title = "Copy Part " + what.capitalize()        # the command, as the menus name it
    noun = "part " + what
    log_prefix = "[{0}] ".format(title)
    session = NXOpen.Session.GetSession()
    ui = NXOpen.UI.GetUI()
    values, skipped = selected_values(ui.SelectionManager, what)
    for line in skipped:
        session.LogFile.WriteLine(log_prefix + "skipped " + line)

    if not values:
        reason = ("No {0} found for the selection.".format(noun) if skipped
                  else "Nothing is selected.")
        ui.NXMessageBox.Show(title, NXOpen.NXMessageBox.DialogType.Warning,
                             reason + "\n\nSelect one or more components in the Assembly Navigator "
                             "or the graphics window, then choose {0}.".format(title))
        return

    try:
        copy_to_clipboard("\r\n".join(values))
    except Exception as ex:
        session.LogFile.WriteLine(log_prefix + "could not copy to the clipboard: {0}".format(ex))
        ui.NXMessageBox.Show(title, NXOpen.NXMessageBox.DialogType.Error,
                             "Could not copy to the clipboard:\n{0}".format(ex))
        return

    message = _summary(values, noun)
    if skipped:
        message += " ({0} other selected object{1} skipped)".format(
            len(skipped), "" if len(skipped) == 1 else "s")
    session.LogFile.WriteLine(log_prefix + message)
    try:
        NXOpen.UF.UFSession.GetUFSession().Ui.SetStatus(message)
    except Exception:
        pass        # the copy worked; the status line is only a courtesy


def main(args):
    copy_selected(NUMBER)


if __name__ == '__main__':
    main(sys.argv[1:])
