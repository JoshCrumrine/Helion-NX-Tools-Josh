# NX 2506
# Author:  jo388c
# Created: 2026-11-02
# Copies the current NX view to the Windows clipboard as a picture, in one click, ready to paste
# (Ctrl+V) into Teams, Outlook, Word or Confluence.
#
# The picture is the graphics window on a white background (BACKGROUND). For the moment of the
# capture only, sketches, datums (planes, axes, coordinate systems, points) and assembly constraint
# symbols are hidden (HIDE_TYPES), the view triad and the WCS are turned off, and the selection is
# cleared so nothing shows highlighted. All of it is put back straight after: the hidden objects by
# undoing to a mark set just before hiding them, so exactly those come back. In a sketch or on a
# drawing sheet nothing is hidden: the picture shows the sketch or the sheet as it is on screen.
# Nothing is saved and no file is kept; the status line says what was copied.
#
# Run it from a button (see README.md), or File -> Execute -> NX Open... and pick this file.
#
# Self-contained on purpose (no lib/ imports): NX re-reads this file on every run, so a change to it
# works on the next click without restarting NX.
import ctypes
import os
import struct
import sys
import tempfile
import time
from ctypes import wintypes

import NXOpen
import NXOpen.Gateway     # the image export builder and its enums
import NXOpen.UF          # NX only creates NXOpen.UF once it is imported explicitly

TITLE = "Screenshot to Clipboard"           # the command, as the button names it
BACKGROUND = (1.0, 1.0, 1.0)    # picture background as red, green, blue (0-1 each); None keeps NX's
HIDE_TYPES = ("Sketches", "Datums", "AssemblyConstraints")  # NXOpen.DisplayManager.ShowHideType
                                                            # members hidden for the capture
DEBUG = False   # True logs, step by step, which parts NX counts as modified (it asks to save those
                # on close) and the view triad settings
_LOG_PREFIX = "[{0}] ".format(TITLE)


# ----------------------------------------------------------------------------- capture
def _model_view_shown(session, part):
    """True when the screen shows the model: no drawing sheet open and no sketch being edited."""
    try:
        return session.ActiveSketch is None and part.DrawingSheets.CurrentDrawingSheet is None
    except Exception:
        return False


def _log(message):
    try:
        NXOpen.Session.GetSession().LogFile.WriteLine(_LOG_PREFIX + message)
    except Exception:
        pass


def _hide_types(session):
    """Hide the HIDE_TYPES objects in the whole displayed assembly; returns how many were hidden. A
    type NX will not hide is skipped (and logged): the picture is still worth having."""
    manager = session.DisplayManager
    scope = NXOpen.DisplayManager.ShowHideScope.AnyInAssembly
    hidden = 0
    for name in HIDE_TYPES:
        try:
            hidden += manager.HideByType(getattr(NXOpen.DisplayManager.ShowHideType, name), scope)
        except Exception as ex:
            _log("could not hide {0}: {1}".format(name, ex))
    return hidden


class _ModifiedTrace(object):
    """DEBUG: called after each step, logs the parts that step made NX count as modified, or no
    longer modified. Hiding marks a part modified; the undo that shows the objects again clears it
    (seen in NX 2506, 2026-11-02)."""

    def __init__(self, session):
        self.session = session
        self.modified = self._modified()
        _log("modified before: {0}".format(", ".join(sorted(self.modified)) or "none"))

    def _modified(self):
        names = set()
        try:
            for part in self.session.Parts:
                if part.IsModified:
                    names.add(part.Leaf)
        except Exception as ex:
            _log("could not read which parts are modified: {0}".format(ex))
        return names

    def __call__(self, step):
        now = self._modified()
        for change, names in (("modified", now - self.modified), ("unmodified", self.modified - now)):
            if names:
                _log("{0} made {1}: {2}".format(step, change, ", ".join(sorted(names))))
        self.modified = now


def _no_trace(step):
    pass


def _log_triad_settings(session, part):
    """DEBUG: the three view triad switches NX has (session, part, work view)."""
    values = []
    for label, read in (("session", lambda: session.Preferences.ScreenVisualization.TriadVisibility),
                        ("part", lambda: part.Preferences.ScreenVisualization.TriadVisibility),
                        ("work view", lambda: part.Views.WorkView.TriadVisibility)):
        try:
            values.append("{0} {1!r}".format(label, read()))
        except Exception as ex:
            values.append("{0} unreadable ({1})".format(label, ex))
    _log("view triad: " + ", ".join(values))


def _undo_hiding(session, mark):
    """Show exactly what _hide_types hid, by undoing to the mark set before it, and drop the mark.
    If the undo fails the mark stays, so Edit > Undo (Ctrl+Z) still brings the objects back."""
    session.UndoToMark(mark, None)
    session.DeleteUndoMark(mark, None)


def _turn_off(obj, flag, what, put_back):
    """Set the bool property `flag` of `obj` to False if it is True, and note how to set it back.
    Not every view has a triad (a drawing sheet's), so a property NX will not read or set is
    skipped (and logged) rather than stopping the picture."""
    try:
        if getattr(obj, flag):
            setattr(obj, flag, False)
            put_back.append((what, lambda: setattr(obj, flag, True)))
    except Exception as ex:
        _log("left {0} as it was: {1}".format(what, ex))


def tidy_view(session, ui, part, put_back, trace=_no_trace):
    """Make the changes the picture needs. Each change adds (what, how to put it back) to
    `put_back` as it is made, so a failure part way leaves only those to put back. Returns how
    many objects were hidden. trace(step) is called after each step."""
    selection = ui.SelectionManager
    try:
        selected = [selection.GetSelectedTaggedObject(i)
                    for i in range(selection.GetNumSelectedObjects())]
        if selected:
            selection.ClearGlobalSelectionList()
            put_back.append(("the selection", lambda: selection.RequestSelections(selected)))
    except Exception as ex:     # e.g. a command's dialog owns the selection: keep the highlight
        _log("left the selection as it was: {0}".format(ex))
    trace("clearing the selection")
    hidden = 0
    if HIDE_TYPES and _model_view_shown(session, part):
        mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, TITLE)
        put_back.append(("the hidden sketches and datums (Edit > Undo shows them again)",
                         lambda: _undo_hiding(session, mark)))
        hidden = _hide_types(session)
        trace("hiding " + ", ".join(HIDE_TYPES))
    _turn_off(part.Views.WorkView, "TriadVisibility", "the view triad", put_back)
    trace("turning off the view triad")
    _turn_off(part.WCS, "Visibility", "the WCS", put_back)
    trace("turning off the WCS")
    return hidden


def put_back_all(put_back, trace=_no_trace):
    """Undo the changes tidy_view made, last first. Returns one line per change that would not go
    back. trace(step) is called after each."""
    problems = []
    for what, how in reversed(put_back):
        try:
            how()
        except Exception as ex:
            problems.append("{0}: {1}".format(what, ex))
        trace("putting back " + what)
    return problems


def export_view(part, path):
    """Save the graphics window as a BMP file at `path`, on the BACKGROUND colour."""
    options = NXOpen.Gateway.ImageExportBuilder
    builder = part.Views.CreateImageExportBuilder()
    try:
        builder.RegionMode = False      # the whole graphics window
        builder.DeviceWidth = 0         # 0: the window's own size
        builder.DeviceHeight = 0
        builder.FileFormat = options.FileFormats.Bmp
        builder.FileName = path
        if BACKGROUND is None:
            builder.BackgroundOption = options.BackgroundOptions.Original
        else:
            builder.BackgroundOption = options.BackgroundOptions.CustomColor
            builder.SetCustomBackgroundColor(list(BACKGROUND))
        builder.EnhanceEdges = False
        builder.Commit()
    finally:
        builder.Destroy()
    if not os.path.isfile(path):
        raise RuntimeError("NX wrote no picture file ({0})".format(path))


# ----------------------------------------------------------------------------- picture
_BI_RGB, _BI_BITFIELDS = 0, 3
_BGRA_MASKS = (0x00FF0000, 0x0000FF00, 0x000000FF)     # red, green, blue masks of a BGRA BMP
_PIXELS_PER_METRE = 3780                                # 96 dpi, as Windows screenshots


def dib_from_bmp(data):
    """(dib, width, height) for the bytes of a BMP file: the picture as a 24-bit bottom-up DIB, the
    clipboard's CF_DIB format, which every program that takes a pasted picture reads. Takes the
    uncompressed 24- and 32-bit BMPs (any header version) that NX writes."""
    if data[:2] != b"BM" or len(data) < 54:
        raise ValueError("not a BMP file")
    offset, = struct.unpack_from("<I", data, 10)
    width, height, bits, compression = struct.unpack_from("<iixxHI", data, 18)
    if width <= 0 or height == 0 or bits not in (24, 32) or compression not in (_BI_RGB, _BI_BITFIELDS):
        raise ValueError("unexpected BMP: {0} x {1}, {2} bits, compression {3}".format(
            width, height, bits, compression))
    if compression == _BI_BITFIELDS and struct.unpack_from("<III", data, 54) != _BGRA_MASKS:
        raise ValueError("unexpected BMP colour masks")
    rows = abs(height)
    source_stride = (width * bits // 8 + 3) & ~3        # BMP rows are padded to 4 bytes
    stride = (width * 3 + 3) & ~3
    pixels = data[offset:offset + source_stride * rows]
    if len(pixels) < source_stride * rows:
        raise ValueError("BMP file is cut short")
    if bits == 24 and height > 0:
        out = pixels                                    # already the CF_DIB layout
    else:
        out = bytearray(stride * rows)
        # A DIB lists its rows bottom first; a BMP with a negative height lists them top first.
        order = range(rows) if height > 0 else range(rows - 1, -1, -1)
        for i, row in enumerate(order):
            start = row * source_stride
            if bits == 32:                              # BGRA -> BGR
                line = bytearray(width * 3)
                for channel in range(3):
                    line[channel::3] = pixels[start + channel:start + width * 4:4]
            else:
                line = pixels[start:start + width * 3]
            out[i * stride:i * stride + width * 3] = line
        out = bytes(out)
    header = struct.pack("<IiiHHIIiiII", 40, width, rows, 1, 24, _BI_RGB, len(out),
                         _PIXELS_PER_METRE, _PIXELS_PER_METRE, 0, 0)
    return header + out, width, rows


# ----------------------------------------------------------------------------- clipboard
_CF_DIB = 8
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


def copy_picture_to_clipboard(dib):
    """Put a CF_DIB picture on the Windows clipboard. Raises OSError if Windows refuses.

    Windows needs a window to own the clipboard (with none, SetClipboardData may fail), so a hidden
    message-only window is made for the moment and destroyed again.
    """
    user32, kernel32 = _win32()
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
            handle = kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(dib))
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            buffer = kernel32.GlobalLock(handle)
            if not buffer:
                kernel32.GlobalFree(handle)
                raise ctypes.WinError(ctypes.get_last_error())
            ctypes.memmove(buffer, dib, len(dib))
            kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(_CF_DIB, handle):
                kernel32.GlobalFree(handle)     # Windows only takes ownership on success
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            user32.CloseClipboard()
    finally:
        user32.DestroyWindow(hwnd)


# ----------------------------------------------------------------------------- main
def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def take_screenshot():
    """Copy the graphics window to the clipboard as a picture with the clutter left out, and say on
    the status line what was copied."""
    session = NXOpen.Session.GetSession()
    ui = NXOpen.UI.GetUI()
    part = session.Parts.Display
    if part is None:
        ui.NXMessageBox.Show(TITLE, NXOpen.NXMessageBox.DialogType.Warning,
                             "No part is displayed. Open a part, then choose {0} again.".format(TITLE))
        return

    path = os.path.join(tempfile.gettempdir(), "nx_screenshot_{0}_{1}.bmp".format(
        os.getpid(), int(time.time() * 1000)))
    put_back, hidden, picture, error = [], 0, None, None
    trace = _no_trace
    if DEBUG:
        _log_triad_settings(session, part)
        trace = _ModifiedTrace(session)
    try:
        hidden = tidy_view(session, ui, part, put_back, trace)
        export_view(part, path)
        trace("capturing the picture")
        with open(path, "rb") as f:
            picture = dib_from_bmp(f.read())
    except Exception as ex:
        error = "Could not capture the view: {0}".format(ex)
    finally:
        problems = put_back_all(put_back, trace)    # the view goes back before the clipboard work
        _remove(path)
    if picture is not None:
        try:
            copy_picture_to_clipboard(picture[0])
        except Exception as ex:
            error = "Could not copy the picture to the clipboard: {0}".format(ex)

    for line in problems:
        _log("could not put back " + line)
    not_back = ("\n\nThese could not be put back as they were:\n" + "\n".join(problems)
                if problems else "")
    if error:
        _log(error)
        ui.NXMessageBox.Show(TITLE, NXOpen.NXMessageBox.DialogType.Error, error + not_back)
        return
    message = "Copied the view to the clipboard ({0} x {1} pixels). Paste it with Ctrl+V.".format(
        picture[1], picture[2])
    _log(message + " {0} object{1} hidden for the picture.".format(hidden, "" if hidden == 1 else "s"))
    if problems:
        ui.NXMessageBox.Show(TITLE, NXOpen.NXMessageBox.DialogType.Warning, message + not_back)
        return
    try:
        NXOpen.UF.UFSession.GetUFSession().Ui.SetStatus(message)
    except Exception:
        pass        # the copy worked; the status line is only a courtesy


def main(args):
    take_screenshot()


if __name__ == '__main__':
    main(sys.argv[1:])
