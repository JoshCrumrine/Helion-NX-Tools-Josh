# Copy Part Number and Copy Part Name (NX Open)

NX Open (Python) tool for **NX 2506** in Teamcenter managed mode. Right-click a component in the
**Assembly Navigator** and choose:

* **Copy Part Number**: its part number (the Teamcenter item ID, e.g. `1050105-020`), or
* **Copy Part Name**: its part name (the Teamcenter item name, the part's `DB_PART_NAME` attribute).

The text is then on the Windows clipboard, ready to paste into Teamcenter, Excel, Teams or a ticket.

**Status: trial.** Installed per user, by hand. Copy Part Number works in NX (right-click in the
Assembly Navigator, 2026-10-29). Copy Part Name is new and not yet tried in NX.

## What you get

* **Right-click → Copy Part Number / Copy Part Name** on components in the Assembly Navigator, and
  on a component picked in the graphics window. They sit just below **Copy** when the menu has
  one, otherwise at the bottom.
* **Menu → Edit → Copy Part Number / Copy Part Name**, for whatever is selected.
* **Several components selected:** one value per line, each part once, in the order they were
  selected (five instances of the same bolt give one line). Both commands list the parts in the same
  order, so numbers and names pasted side by side (e.g. two Excel columns) line up. A part with no
  name is left out, and the status line says so.
* **A body, face or edge** of a component counts as that component.
* **Components whose part is not loaded** work too: the number comes from the part name
  (`1150201-500/01` → `1150201-500`) and the name from Teamcenter.
* The **status line** shows what was copied, e.g. `Copied part number 1050105-020`. Nothing in the
  model changes and nothing is saved.

## Install (your Windows user only)

1. Double-click **`Install-Copy-Part-Number.bat`** in this folder.
2. **Restart NX** (it reads the new files only at startup).

Already installed? Run it again and restart NX: it overwrites the same two files.

The installer writes two files to your personal NX startup folder,
`%LOCALAPPDATA%\Siemens\NX2506\startup`. The Helion NX launcher already registers that folder with
NX (it keeps `NX_title.men`, the window title, there), so nothing else has to change: no environment
variables, nothing on the network share, no other file in that folder, no existing script in this
repo.

| Installed file | What it does |
| --- | --- |
| `helion_copy_part_number.men` | Defines the **Copy Part Number** and **Copy Part Name** commands (Edit menu). They run `copy_part_number.py` and `copy_part_name.py` from **this folder**, by their full paths. |
| `helion_copy_part_number.py` | NX runs it at startup. It adds the commands to right-click menus about components. |

The repo has to sit at a path without spaces (e.g. `C:\Code\Helion-NX-Tools`); the installer says
so if it does not. **Run the installer again** after moving the repo or changing a file in
`nx_startup\`.

## Uninstall

Double-click **`Uninstall-Copy-Part-Number.bat`**, then restart NX. It deletes the two files above,
plus the compiled copy of the startup script that NX's Python keeps in `startup\__pycache__`, and
nothing else.

## Try it without installing

Select one or more components, then **File → Execute → NX Open…** and pick `copy_part_number.py` or
`copy_part_name.py`. Same result, no right-click entry.

## Trial checklist

1. After installing and restarting NX, **Menu → Edit** should list **Copy Part Number** and **Copy
   Part Name** below **Copy**. That shows NX loaded the commands.
2. Open an assembly, right-click a component in the Assembly Navigator, choose **Copy Part Name**,
   and paste into Notepad.
3. Try a few selected components, an unloaded component, and a body picked in the graphics window.

During the trial `helion_copy_part_number.py` has `DEBUG = True`: every right-click menu adds one line
starting `[Copy Part Number]` to the NX system log (Help → Log File, or
[Export-System-Log](../Export-System-Log/README.md)). The line says where the menu is, what NX built
it for, and its entries; that is how to tell why the entries did or did not appear. Set
`DEBUG = False` and reinstall once the trial is over.

## If it does not work

* **No Copy Part Number in Menu → Edit:** NX did not load `helion_copy_part_number.men`. Check the
  file is in `%LOCALAPPDATA%\Siemens\NX2506\startup` and that NX was restarted. The system log lists
  each menu file NX loads (`MB_LOADED_MENU_FILE`).
* **Copy Part Number is there but Copy Part Name is not:** NX still has the menu file from before
  Copy Part Name existed. Run the installer again, then restart NX.
* **In the Edit menu, but not on the right-click menu:** look for `[Copy Part Number]` in the system
  log. No `ready:` line means NX did not run the startup script; `menu location=... context=...`
  lines show the menus NX offered and why the entries were not added.
* **"Nothing is selected"** when it is: the selection was lost on the way to the command. Note what
  you right-clicked and send the system log.
* **"No part name found"**: the part has no `DB_PART_NAME`, and Teamcenter gave no name for its
  number either (for example, a part that is not in Teamcenter). The system log has a
  `[Copy Part Name] skipped` line for it.
* **"Could not copy to the clipboard"**: another program held the clipboard. Try again.
* **Fallback:** the commands can also go on the Assembly Navigator's shortcut toolbar or radial menu
  via NX's **Customize → Shortcuts**, or on the ribbon via **Customize → Commands** (search "Copy
  Part").

## How it works

* `copy_part_number.py` reads NX's selection, finds each part number (the part's `DB_PART_NO`
  attribute; for a part that is not loaded, the item ID in the part name) and puts the text on the
  clipboard through the Windows API (`ctypes`, which NX's Python includes). It is self-contained, so
  NX re-reads it on every click: a change to it works without restarting NX.
* `copy_part_name.py` runs the same code from `copy_part_number.py`, asking for names: the part's
  `DB_PART_NAME` attribute, or, for a part that is not loaded, the item's name in Teamcenter
  (`UF_UGMGR_ask_part_tag` and `UF_UGMGR_ask_part_name_desc`).
* `nx_startup\helion_copy_part_number.py` registers a callback with
  `MenuBarManager.RegisterConfigureContextMenuCallback`, which NX calls just before it shows any
  right-click menu. For menus about a component it adds the `HELION_COPY_PART_NUMBER` and
  `HELION_COPY_PART_NAME` buttons with `ContextMenu.AddMenuButton`. This is the method of Siemens'
  `ConfigureContextMenu` sample in `%UGII_BASE_DIR%\UGOPEN\SampleNXOpenApplications`. NX only reads
  it at startup.
* `nx_startup\helion_copy_part_number.men` is the MenuScript that defines the buttons. The installer
  fills in the full path of each script on its `ACTIONS` line.

## Files

* `copy_part_number.py`: the Copy Part Number command, and the code both commands share.
* `copy_part_name.py`: the Copy Part Name command.
* `nx_startup\helion_copy_part_number.py`: startup script (copied by the installer).
* `nx_startup\helion_copy_part_number.men`: menu file template (filled in and copied by the installer).
* `Install-Copy-Part-Number.bat` / `Uninstall-Copy-Part-Number.bat`: double-click wrappers.
* `Install-Copy-Part-Number.ps1`: does the work for both (`-Uninstall`, `-ProfileDir <folder>`).
