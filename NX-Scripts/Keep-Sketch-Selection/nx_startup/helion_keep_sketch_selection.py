# NX 2506
# Author:  jo388c
# Created: 2026-11-01
# NX startup script for Keep Sketch Selection: in a sketch, the curves you selected stay selected
# after you apply a relation to them, so the next relation needs no new pick. Select two lines, then
# click Make Parallel, Make Equal and Convert To/From Reference one after the other.
#
# Not run by hand. Install-Keep-Sketch-Selection.bat copies it to your NX startup folder
# (%LOCALAPPDATA%\Siemens\NX2506\startup); NX loads it when it starts and calls startup(), which
# subscribes to NX's selection changes. NX empties the selection when a relation command finishes.
# When the selection in the active sketch empties and NX's newest undo mark is newer than the
# selection and is named like a relation command (RELATION_COMMANDS), the objects selected before
# are selected again. Emptying the selection yourself (Esc, a click on empty space) creates no undo
# mark, so it still empties it; other commands (trim, offset, delete, dimensions, ...) are left alone.
# NX reads this file only at startup, so after changing it: reinstall, then restart NX.
#
# DEBUG = True writes one line per selection change in a sketch to the NX system log (Help > Log
# File): what is selected, NX's newest undo mark and what this script did. It is on for the trial, to
# see how NX reports the changes and what it names its undo marks; turn it off once that is settled.
import re

import NXOpen

DEBUG = True
_LOG_PREFIX = "[Keep Sketch Selection] "

# Undo mark names after which the selection comes back: relations between whole curves, Convert
# To/From Reference, Fix. Not Make Coincident or Make Midpoint Aligned: those are usually picked on
# end points, and selecting the objects again could select whole curves instead.
RELATION_COMMANDS = re.compile(
    r"parallel|perpendicular|collinear|horizontal|vertical|tangent|equal|symmetr|concentric"
    r"|reference|constrain|\bfix", re.IGNORECASE)

_session = None
_selection = None           # NX's selection manager
_subscriber = None          # set once subscribed; kept so NX keeps calling back
_held = None                # (sketch tag, objects selected in it, newest undo mark then), or None


def _log(message):
    try:
        NXOpen.Session.GetSession().LogFile.WriteLine(_LOG_PREFIX + message)
    except Exception:
        pass


def _describe(sketch):
    try:
        return sketch.Name or sketch.JournalIdentifier
    except Exception:
        return "sketch"


def _class_names(objects):
    """'Line, Line' for the debug log."""
    return ", ".join(type(obj).__name__ for obj in objects) or "nothing"


def _newest_undo_mark():
    """(id, name) of NX's newest visible undo mark; (0, "") if there is none. Mark ids grow with
    each new mark."""
    mark = _session.GetNewestUndoMark(NXOpen.Session.MarkVisibility.Visible)
    if not mark:
        return 0, ""
    try:
        return mark, _session.GetUndoMarkName(mark) or ""
    except Exception:
        return mark, ""


def _selected_objects():
    return [_selection.GetSelectedTaggedObject(i) for i in range(_selection.GetNumSelectedObjects())]


def _why_not_reselect(sketch, held, mark, mark_name):
    """None when the held objects should be selected again, else the reason they are not."""
    sketch_tag, objects, held_mark = held
    if sketch.Tag != sketch_tag:
        return "another sketch is active"
    if mark <= held_mark:
        return "no command ran since they were selected"
    if not RELATION_COMMANDS.search(mark_name):
        return "the last command is not a relation"
    in_sketch = set(geometry.Tag for geometry in sketch.GetAllGeometry())
    if any(obj.Tag not in in_sketch for obj in objects):
        return "not all of them are curves or points of this sketch"
    return None


def _on_change(clear_all, deselected, selected):
    global _held
    sketch = _session.ActiveSketch
    if sketch is None:
        _held = None
        return
    current = _selected_objects()
    mark, mark_name = _newest_undo_mark()
    if not _selection.IsGlobalSelectionActive():
        # A command's dialog owns the selection. Keep what is held: it can come back once the
        # command ends.
        what = "left alone: a dialog owns the selection"
    elif current:
        _held = (sketch.Tag, current, mark)
        what = "holding them"
    elif _held is None:
        what = "nothing held"
    else:
        held, _held = _held, None   # selecting them again calls back here and holds them anew
        reason = _why_not_reselect(sketch, held, mark, mark_name)
        if reason:
            what = "not selected again: " + reason
        else:
            _selection.RequestSelections(held[1])
            what = "selected the {0} again ({1} now selected)".format(
                len(held[1]), _selection.GetNumSelectedObjects())
    if DEBUG:
        _log("{0}: -{1} +{2}{3}, selected: {4}; undo mark {5} {6!r}; {7}".format(
            _describe(sketch), len(deselected or ()), len(selected or ()),
            " (clear all)" if clear_all else "", _class_names(current), mark, mark_name, what))


def on_selection_change(clear_all, deselected, selected):
    """NX calls this at the end of each user action that changed the selection, in any
    application; it acts only while a sketch is active."""
    try:
        _on_change(clear_all, deselected, selected)
    except Exception as ex:
        _log("selection callback failed: {0}".format(ex))


def startup(argc=0, args=None):
    """Called by NX once, at startup: subscribes to selection changes."""
    global _session, _selection, _subscriber
    if _subscriber is not None:
        return 0
    try:
        _session = NXOpen.Session.GetSession()
        _selection = NXOpen.UI.GetUI().SelectionManager
        subscriber = _selection.CreateSelectionSubscriber()
        subscriber.RegisterOnSelectionChangeCallback(on_selection_change)
        subscriber.Activate()
        _subscriber = subscriber
        _log("ready: watching selections in sketches (debug log {0})".format(
            "on" if DEBUG else "off"))
    except Exception as ex:
        _log("could not subscribe to selection changes: {0}".format(ex))
    return 0


def GetUnloadOption(arg):
    """NX calls back into this file all session, so it must stay loaded until NX exits."""
    return NXOpen.Session.LibraryUnloadOption.AtTermination
