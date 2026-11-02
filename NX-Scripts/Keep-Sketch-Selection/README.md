# Keep Sketch Selection (NX Open)

NX Open (Python) startup script for **NX 2506** sketches. NX deselects the curves after each relation
you apply, so adding a second relation to the same curves means picking them again. With this
installed, **the curves stay selected**: select two lines once, then click **Make Parallel**, **Make
Equal** and **Convert To/From Reference** one after the other.

**Status: trial.** Installed per user, by hand. Not yet run in NX.

## What you get

* After a relation command in a sketch, the objects that were selected for it are selected again.
  This covers Make Parallel, Make Perpendicular, Make Collinear, Make Horizontal, Make Vertical,
  Make Tangent, Make Equal and Make Symmetric (and their "to String" forms), plus Convert To/From
  Reference and Fix. It works the same from the Sketch Scene Bar, the toolbar that pops up on a
  selection, the right-click menu or a keyboard shortcut.
* Everything else behaves as before:
  * **Esc**, or a click on empty space, still clears the selection.
  * Trim, offset, delete, dimensions and the rest are left alone.
  * The selection is not kept outside sketches.
* **Not kept** after Make Coincident or Make Midpoint Aligned. Those are usually picked on end points,
  and selecting again could select whole curves instead.
* **Not kept** when the selection held anything other than curves or points of the sketch, such as a
  dimension or an edge of the solid.
* Nothing in the model changes and nothing pops up. It only selects again what you had selected.

Tip: NX's sketch comes with one-key shortcuts for most relations: **P** Make Parallel, **Q** Make
Equal, **L** Make Perpendicular, **H** / **V** Make Horizontal / Vertical, **C** Make Collinear,
**O** Make Tangent, **S** Make Symmetric. With the selection kept, *select two lines, P, Q* gives
parallel and equal. Convert To/From Reference has no key; you can give it one in **Customize →
Keyboard**.

## Install (your Windows user only)

1. Double-click **`Install-Keep-Sketch-Selection.bat`** in this folder.
2. **Restart NX** (it reads startup scripts only when it starts).

The installer copies one file, `helion_keep_sketch_selection.py`, to your personal NX startup folder,
`%LOCALAPPDATA%\Siemens\NX2506\startup`, the same folder Copy Part Number uses. Nothing else changes.
Run the installer again after changing the file in `nx_startup\`.

## Uninstall

Double-click **`Uninstall-Keep-Sketch-Selection.bat`**, then restart NX. It deletes that one file and
the compiled copy of it in `startup\__pycache__`, and nothing else.

## Trial checklist

1. After installing and restarting NX, open a sketch, select two lines and click **Make Parallel**.
   The lines should still be selected afterwards. Then click **Make Equal**, then **Convert To/From
   Reference**.
2. Press **Esc**: the selection should clear as usual.
3. Try a command that is not a relation (for example Quick Trim or Offset Curve) with curves
   selected: it should behave as it always has.

During the trial `DEBUG = True`. Every selection change in a sketch writes one line starting with
`[Keep Sketch Selection]` to the NX system log (Help → Log File, or
[Export-System-Log](../Export-System-Log/README.md)). The line gives:

* the objects now selected,
* NX's newest undo mark (its number and name),
* what the script did: holding them, selected them again, or why not.

That is how to tell why a selection did or did not come back. Set `DEBUG = False` and reinstall once
the trial is over.

## If it does not work

* **No `[Keep Sketch Selection] ready` line in the system log:** NX did not run the script. Check that
  `helion_keep_sketch_selection.py` is in `%LOCALAPPDATA%\Siemens\NX2506\startup` and that NX was
  restarted.
* **`not selected again: the last command is not a relation`** after a relation: NX names that
  command's undo mark differently than expected. The name is in the same line; add a word from it to
  `RELATION_COMMANDS` in `nx_startup\helion_keep_sketch_selection.py`, reinstall and restart NX.
* **`selected the 2 again (0 now selected)`:** NX turned down the request to select them again. Send
  the system log.
* **Lines saying `a dialog owns the selection`, then nothing:** NX reported the change while the
  command was still running and nothing after it ended. Send the system log.
* **It gets in the way:** uninstall it (above).

## How it works

* `nx_startup\helion_keep_sketch_selection.py` subscribes to NX's selection changes
  (`SelectionManager.CreateSelectionSubscriber`). NX calls it at the end of every user action that
  changes the selection. It does nothing outside a sketch, or while a command's dialog owns the
  selection.
* While objects are selected in a sketch, it remembers them, together with NX's newest undo mark.
* When the selection then empties, it checks three things:
  * NX has a newer undo mark, so a command ran. Clearing the selection yourself makes no undo mark.
  * The mark's name matches `RELATION_COMMANDS`.
  * Every remembered object is still a curve or point of the active sketch.

  If all three hold, it selects the remembered objects again (`SelectionManager.RequestSelections`),
  in the order they were picked. That keeps the last-picked curve last, which NX's Make commands
  leave in place.
* NX reads it only at startup. It stays loaded for the whole session (`GetUnloadOption` returns
  `AtTermination`).

## Files

* `nx_startup\helion_keep_sketch_selection.py`: the startup script (copied by the installer).
* `Install-Keep-Sketch-Selection.bat` / `Uninstall-Keep-Sketch-Selection.bat`: double-click wrappers.
* `Install-Keep-Sketch-Selection.ps1`: does the work for both (`-Uninstall`, `-ProfileDir <folder>`).
