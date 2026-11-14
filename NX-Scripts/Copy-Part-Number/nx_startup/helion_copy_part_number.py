# NX 2506
# Author:  jo388c
# Created: 2026-10-29
# NX startup script for Copy Part Number: adds "Copy Part Number" and "Copy Part Name" to the
# right-click menu of assembly components, in the Assembly Navigator and in the graphics window, and
# of the top node (the displayed part) in the Assembly Navigator.
#
# Not run by hand. Install-Copy-Part-Number.bat copies it to your NX startup folder
# (%LOCALAPPDATA%\Siemens\NX2506\startup); NX loads it when it starts and calls startup(), which
# registers a callback that NX runs just before it shows any right-click menu. For menus about
# components the callback adds the buttons in BUTTONS, which helion_copy_part_number.men (installed
# alongside) defines and which run copy_part_number.py and copy_part_name.py. NX reads this file
# only at startup, so after changing it: reinstall, then restart NX.
#
# DEBUG = True writes one line per right-click menu to the NX system log (Help > Log File): where
# the menu is, what NX built it for, and its entries. It was on for the trial, to confirm which
# menus get the entries; off since that was settled.
import NXOpen
import NXOpen.Assemblies
import NXOpen.MenuBar

# Defined in helion_copy_part_number.men; they go on the menu in this order
BUTTONS = ("HELION_COPY_PART_NUMBER", "HELION_COPY_PART_NAME")
DEBUG = False
_LOG_PREFIX = "[Copy Part Number] "
_SELECTION_CHECK_MAX = 50               # selected objects looked at per right-click

_callback_id = None                     # set once the callback is registered
_missing_buttons_logged = set()
_ant_contexts_logged = set()


def _log(message):
    try:
        NXOpen.Session.GetSession().LogFile.WriteLine(_LOG_PREFIX + message)
    except Exception:
        pass


def _plain(label):
    """A menu label as plain lower-case text: no '&' shortcut marker, no trailing '...'."""
    return (label or "").replace("&", "").rstrip(". ").strip().lower()


def _selection_counts():
    """(selected objects, components or parts among the first of them); (-1, 0) if the selection
    cannot be read. A part's component assembly (the navigator's top node) counts as a part."""
    try:
        selection = NXOpen.UI.GetUI().SelectionManager
        total = selection.GetNumSelectedObjects()
        kinds = (NXOpen.Assemblies.Component, NXOpen.Assemblies.ComponentAssembly, NXOpen.BasePart)
        return total, sum(1 for i in range(min(total, _SELECTION_CHECK_MAX))
                          if isinstance(selection.GetSelectedTaggedObject(i), kinds))
    except Exception:
        return -1, 0


def _menu_for_components(location, context):
    """True when NX built this right-click menu for assembly components or for the top node of the
    Assembly Navigator.

    `context` names the class of the object right-clicked, e.g. "Assemblies.Component" or
    "Features.Cylinder"; for the navigator's top node (the displayed part) NX 2506 gives
    "Assemblies.ComponentAssembly". Menus outside the graphics window also get the entries while the
    selection holds a component (or a part), which covers a multiple selection whose context may
    name no single class. In the graphics window only `context` counts, so a right-clicked face or
    body keeps its menu. In the Assembly Navigator ("ANT") a right-click with nothing selected also
    gets them, in case the top node leaves the selection empty; the copy scripts then copy the
    displayed part.
    """
    if context.split(".")[-1].lower() in ("component", "componentassembly"):
        return True
    if location.lower() == "graphicswindow":
        return False
    selected, parts = _selection_counts()
    return parts > 0 or (selected == 0 and location.upper() == "ANT")


def _insert_position(menu):
    """Index just below the menu's Copy entry, or -1 (the end) if it has none."""
    for i in range(menu.NumberOfEntries):
        entry = menu.GetEntry(i)
        if entry.Name == "UG_EDIT_COPY" or _plain(entry.Label) == "copy":
            return i + 1
    return -1


def _defined_buttons():
    """(name, button) for each of BUTTONS that NX knows, in order. Logs a missing one, once."""
    found = []
    for name in BUTTONS:
        try:
            button = NXOpen.UI.GetUI().MenuBarManager.GetButtonFromName(name)
            error = "not defined"
        except Exception as ex:
            button, error = None, ex
        if button is not None:
            found.append((name, button))
        elif name not in _missing_buttons_logged:
            _missing_buttons_logged.add(name)
            _log("button {0}: {1}. Is an up-to-date helion_copy_part_number.men in the NX startup "
                 "folder? Run Install-Copy-Part-Number.bat, then restart NX.".format(name, error))
    return found


def _add_entries(menu):
    """Add the buttons `menu` does not have yet, in order, just below its Copy entry (or at the
    end). Returns where they went, or None if it added none."""
    buttons = [button for name, button in _defined_buttons() if not menu.HasEntryWithName(name)]
    if not buttons:
        return None
    index = _insert_position(menu)
    if index < 0:
        last = menu.NumberOfEntries - 1
        if last >= 0 and menu.GetEntry(last).EntryType != NXOpen.MenuBar.ContextMenuEntry.Type.Separator:
            menu.AddSeparator(-1)
    where = "at end" if index < 0 else "at {0}".format(index)
    for button in buttons:
        menu.AddMenuButton(button, index)
        if index >= 0:
            index += 1
    return where


def _describe_entries(menu):
    """'0 NAME "Label" | 1 --- | ...' for the debug log."""
    entries = []
    for i in range(menu.NumberOfEntries):
        entry = menu.GetEntry(i)
        if entry.EntryType == NXOpen.MenuBar.ContextMenuEntry.Type.Separator:
            entries.append("{0} ---".format(i))
        else:
            entries.append('{0} {1} "{2}"'.format(i, entry.Name, (entry.Label or "").replace("&", "")))
    return " | ".join(entries)


def configure_context_menu(menu, props):
    """NX calls this just before it shows a right-click menu. Returning 0 tells NX all went well."""
    try:
        location, context = props.Location or "", props.Context or ""
        added = _add_entries(menu) if _menu_for_components(location, context) else None
        if DEBUG:
            _log("menu location={0!r} context={1!r} selected (objects, components or parts)={2} "
                 "added={3} entries: {4}".format(location, context, _selection_counts(),
                                                 added or "no", _describe_entries(menu)))
        elif location.upper() == "ANT" and context not in _ant_contexts_logged:
            _ant_contexts_logged.add(context)      # once per kind of navigator node, for support
            _log("Assembly Navigator menu context={0!r}: entries {1}".format(
                context, "added " + added if added else "not added"))
    except Exception as ex:
        _log("right-click menu callback failed: {0}".format(ex))
    return 0


def startup(argc=0, args=None):
    """Called by NX once, at startup: registers the right-click menu callback."""
    global _callback_id
    if _callback_id is not None:
        return 0
    try:
        _callback_id = NXOpen.UI.GetUI().MenuBarManager.RegisterConfigureContextMenuCallback(
            "HelionCopyPartNumber",
            "Adds Copy Part Number and Copy Part Name to the right-click menu of assembly components",
            configure_context_menu)
        _log("ready: right-click menu callback registered (debug log {0})".format(
            "on" if DEBUG else "off"))
    except Exception as ex:
        _log("could not register the right-click menu callback: {0}".format(ex))
    return 0


def GetUnloadOption(arg):
    """NX calls back into this file all session, so it must stay loaded until NX exits."""
    return NXOpen.Session.LibraryUnloadOption.AtTermination
