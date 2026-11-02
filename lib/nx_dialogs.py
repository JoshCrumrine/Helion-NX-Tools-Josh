"""BlockStyler dialog helpers."""
import NXOpen


def prompt_string(dlx_path, block_id, default=None):
    """Show a single-field string BlockStyler dialog and return its value.

    Returns the stripped field value, or None if the user cancels. If `default`
    is given it is pre-filled into the field (editable by the user); otherwise
    the field is cleared, so a value from a previous run never carries over.
    The field gets the keyboard focus when the dialog opens, so the user can
    type straight away.

    BlockStyler dialogs require callback handlers to be registered (NX errors
    with "The Initialize callback is not registered" otherwise), and block
    values must be read inside the OK/Apply callback.
    """
    the_ui = NXOpen.UI.GetUI()
    dialog = the_ui.CreateDialog(dlx_path)
    captured = {}

    def _reset():
        """Set the field to `default`, or clear it when there is none."""
        text = default or ""
        props = dialog.GetBlockProperties(block_id)
        # Set both storages: a KeyIn field reads "Value", a Wide field
        # reads "WideValue". Best-effort — never block the dialog.
        for key in ("Value", "WideValue"):
            try:
                props.SetString(key, text)
            except Exception:
                pass

    def initialize_cb():
        _reset()

    def shown_cb():
        # NX restores saved field values after initialize; reset again once
        # the dialog is actually on screen so a previous run's text never shows.
        _reset()
        # Put the cursor in the field. Best-effort — never block the dialog.
        try:
            dialog.TopBlock.FindBlock(block_id).Focus()
        except Exception:
            pass

    def update_cb(block):
        return 0

    def apply_cb():
        props = dialog.GetBlockProperties(block_id)
        value = ""
        # Read WideValue first: for a Wide-presentation field that is the live
        # edited text, while "Value" may still hold the initialize prefill.
        for key in ("WideValue", "Value"):
            try:
                candidate = props.GetString(key)
            except Exception:
                candidate = ""
            if candidate:
                value = candidate
                break
        captured["value"] = value
        return 0

    def ok_cb():
        apply_cb()

    dialog.AddInitializeHandler(initialize_cb)
    dialog.AddDialogShownHandler(shown_cb)
    dialog.AddUpdateHandler(update_cb)
    dialog.AddOkHandler(ok_cb)
    dialog.AddApplyHandler(apply_cb)

    try:
        response = dialog.Show()
        if response != NXOpen.Selection.Response.Ok:
            return None
        return (captured.get("value") or "").strip()
    finally:
        dialog.Dispose()


class UserCancelled(Exception):
    """The user ticked the dialog's "cancel the whole operation" toggle (see choose_from_list)."""


def filter_items(items, text):
    """The `items` that match the search `text`, in their original order.

    Case-insensitive; the text is split on whitespace and EVERY word must appear somewhere
    in the item, so "alum 60" finds "Aluminum 6061" and "steel 304" finds
    "Stainless Steel AISI 304". Blank text matches everything.
    """
    terms = (text or "").lower().split()
    if not terms:
        return list(items)
    return [item for item in items if all(t in item.lower() for t in terms)]


def choose_from_list(dlx_path, list_id, items, heading=None, heading_id=None, skip_id=None,
                     on_shown=None, search_id=None, cancel_id=None):
    """Show a BlockStyler dialog with a single-select list box; return (item, skip).

    `dlx_path` is the dialog file; `list_id` is the API name of its list box and
    `items` the strings to list. `heading` is put into the label block `heading_id`
    (if both are given), and `skip_id` names an optional toggle (for example "stop
    asking") whose state is returned as `skip`. `on_shown`, if given, is called with no
    arguments just before the dialog opens and again once it is on screen (a modal
    dialog can redraw the graphics window and drop a highlight, so callers use it to
    re-apply one). Errors raised by `on_shown` are ignored.

    `search_id` names an optional string block used as a search box: when its text changes
    (NX reports that when the user presses Enter or Tab in the field) the list is narrowed
    to the items that match it (see filter_items), and a single match is selected for
    you. Clearing the text brings the full list back. A plain click in the list, or the
    toggle, never resets the list or the selection.

    `cancel_id` names an optional toggle that means "cancel the whole operation". If it is
    ticked when the dialog is closed (with OK or Cancel), UserCancelled is raised, after the
    dialog has been disposed, and any selection is ignored. Callers catch it to stop their run.

    Returns (chosen string, skip): the chosen string is None if the user cancelled,
    closed the dialog, or pressed OK with nothing selected. `skip` is the toggle's
    state at the end (False when there is no toggle), also reported on Cancel so a
    "skip all" can be combined with skipping this one.

    Like prompt_string, BlockStyler needs its callbacks registered and block values
    read inside the callbacks; the selection is read in the OK/Apply callback.
    """
    items = list(items)
    the_ui = NXOpen.UI.GetUI()
    dialog = the_ui.CreateDialog(dlx_path)
    captured = {"item": None, "skip": False, "cancel": False}
    # What the list box currently shows (filtered by the search text); OK maps the
    # selected row back to a name through this, never through the full `items`.
    view = {"items": items, "text": ""}

    def _search_text():
        if not search_id:
            return ""
        props = dialog.GetBlockProperties(search_id)
        for key in ("WideValue", "Value"):    # same order as prompt_string
            try:
                text = props.GetString(key)
            except Exception:
                text = ""
            if text:
                return text
        return ""

    def _show_items(shown):
        view["items"] = shown
        try:
            dialog.TopBlock.FindBlock(list_id).SetListItems(shown)
        except Exception:
            dialog.GetBlockProperties(list_id).SetStrings("ListItems", shown)

    def _refilter():
        text = _search_text()
        if text == view["text"]:
            return                      # nothing typed: leave the list and selection alone
        view["text"] = text
        _show_items(filter_items(items, text))
        if len(view["items"]) == 1:
            try:
                dialog.TopBlock.FindBlock(list_id).SetSelectedItems([0])
            except Exception:
                pass

    def _skip_value():
        if not skip_id:
            return False
        try:
            return bool(dialog.GetBlockProperties(skip_id).GetLogical("Value"))
        except Exception:
            return False

    def _cancel_value():
        if not cancel_id:
            return False
        try:
            return bool(dialog.GetBlockProperties(cancel_id).GetLogical("Value"))
        except Exception:
            return False

    def _clear_remembered_state():
        """Untick the toggles and empty the search box.

        NX REMEMBERS the last value of toggles (and text boxes) between runs and restores it
        AFTER the initialize callback, so a "cancel" or "stop asking" ticked once would come
        back ticked on every later run and silently discard the user's selection. So this is
        done on initialize and again once the dialog is on screen (prompt_string does the same).
        """
        for toggle in (skip_id, cancel_id):
            if toggle:
                try:
                    dialog.GetBlockProperties(toggle).SetLogical("Value", False)
                except Exception:
                    pass
        if search_id:
            for key in ("Value", "WideValue"):
                try:
                    dialog.GetBlockProperties(search_id).SetString(key, "")
                except Exception:
                    pass
        captured["skip"] = False
        captured["cancel"] = False
        view["text"] = ""

    def initialize_cb():
        if heading_id and heading:
            try:
                dialog.GetBlockProperties(heading_id).SetString("Label", heading)
            except Exception:
                pass
        _show_items(items)
        _clear_remembered_state()

    def _notify_shown():
        if on_shown is not None:
            try:
                on_shown()
            except Exception:
                pass

    def shown_cb():
        # NX has restored its remembered values by now: clear them, and make sure the list shows
        # everything (a remembered search text must not leave it filtered).
        _clear_remembered_state()
        _show_items(items)
        _notify_shown()

    def update_cb(block):
        captured["skip"] = _skip_value()
        captured["cancel"] = _cancel_value()
        if search_id:
            try:
                _refilter()
            except Exception:
                pass
        return 0

    def apply_cb():
        chosen = None
        try:
            selected = dialog.TopBlock.FindBlock(list_id).GetSelectedItems()
            if selected:
                chosen = view["items"][selected[0]]
        except Exception:
            try:
                chosen = dialog.TopBlock.FindBlock(list_id).SelectedItemString or None
            except Exception:
                chosen = None
        captured["item"] = chosen
        captured["skip"] = _skip_value()
        captured["cancel"] = _cancel_value()
        return 0

    def ok_cb():
        return apply_cb()

    def cancel_cb():
        captured["skip"] = _skip_value()
        captured["cancel"] = _cancel_value()
        return 0

    dialog.AddInitializeHandler(initialize_cb)
    dialog.AddDialogShownHandler(shown_cb)
    dialog.AddUpdateHandler(update_cb)
    dialog.AddOkHandler(ok_cb)
    dialog.AddApplyHandler(apply_cb)
    dialog.AddCancelHandler(cancel_cb)

    try:
        _notify_shown()
        response = dialog.Show()
        if captured["cancel"]:
            raise UserCancelled("the user cancelled the whole operation")
        if response != NXOpen.Selection.Response.Ok:
            return None, captured["skip"]
        return captured["item"], captured["skip"]
    finally:
        dialog.Dispose()


def ask_yes_no(title, message):
    """Show a modal Yes/No question box; True if the user chose Yes.

    NXMessageBox.Show returns the 1-based index of the clicked button; for
    DialogType.Question the first button is Yes. Anything else (No, closing
    the box) counts as No.
    """
    response = NXOpen.UI.GetUI().NXMessageBox.Show(
        title, NXOpen.NXMessageBox.DialogType.Question, message)
    return response == 1


class DeferredListing:
    """Stands in for the Listing Window and writes to it only when flushed.

    Writing to the Listing Window brings up NX's Information window, and when
    that happens just before a dialog is shown, the window comes up over the
    dialog and takes its keyboard focus (seen 2026-11-01 with
    CREATE_MCMASTER_PART.py's part-number prompt). A script that shows dialogs
    along the way can write its progress here and call flush() when it is done,
    e.g. in a `finally`. Has WriteLine like a ListingWindow, so it can be passed
    wherever one is expected.
    """

    def __init__(self, listing_window):
        self._listing_window = listing_window
        self._lines = []

    def WriteLine(self, line):
        self._lines.append(line)

    def flush(self):
        """Open the Listing Window and write the held lines, if there are any."""
        if not self._lines:
            return
        self._listing_window.Open()
        for line in self._lines:
            self._listing_window.WriteLine(line)
        self._lines = []
