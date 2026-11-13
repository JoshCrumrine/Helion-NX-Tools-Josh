# Screenshot to Clipboard (NX Open)

NX Open (Python) script for **NX 2506**. One click copies the **current view** to the **Windows clipboard** as a
picture on a **white background**, with **sketches and datums left out**, ready to paste (**Ctrl+V**) into Teams,
Outlook, Word, PowerPoint or a Confluence page.

Script: `NX-Scripts/Screenshot-To-Clipboard/screenshot_to_clipboard.py` (self-contained, no `lib/` imports).
Button icon: `screenshot.bmp`.

**Status: trial.** First runs in NX on 2026-11-02 worked: the picture comes out on white without the view
triad, pastes into Teams and Confluence, and leaves the part with no unsaved changes. Also tested outside NX
with a stand-in for NX Open (what is hidden and put back, and in what order) and with sample BMP files in
every layout NX might write.

## Run it

1. Set the view up as you want it in the picture: orientation, zoom, shaded or wireframe.
2. Click your **Screenshot to Clipboard** button, or **File → Execute → NX Open…** and pick
   `screenshot_to_clipboard.py`.
3. The status line says `Copied the view to the clipboard (1920 x 1080 pixels). Paste it with Ctrl+V.`
4. Paste with **Ctrl+V**.

## Make a button

The same way as the other buttons: add a **New User Command** (right-click the ribbon → **Customize…** →
**Commands** → **New Item**), set its action to `screenshot_to_clipboard.py` in this folder, and give it
`screenshot.bmp` as its icon. It works in Modeling, Assemblies, Drafting and in a sketch, so a place you see in all
of them (such as the Quick Access Toolbar) suits it.

## What it does

* **The picture is the graphics window** at its size on screen, on **white** instead of NX's background. No file is
  kept: NX writes the picture to your `%TEMP%` folder, the script puts it on the clipboard and deletes the file.
* **For the moment of the capture only:**
  * **sketches, datums** (planes, axes, coordinate systems, points) and **assembly constraint symbols** are hidden,
    in the whole displayed assembly;
  * the **view triad** and the **WCS** are turned off;
  * the **selection is cleared**, so nothing shows highlighted.
* **Then everything is put back.** The hidden objects come back by undoing to a mark set just before they were
  hidden, so exactly those reappear: anything you had hidden yourself stays hidden. The triad, the WCS and the
  selection go back as they were, and the undo step is removed again.
* **In a sketch or on a drawing sheet nothing is hidden:** the picture shows the sketch or the sheet as it is on
  screen (still on white, without the triad and the selection highlight).
* **Quiet when it works:** only the status line. A message box appears only if something went wrong, and then says
  what, including anything that could not be put back.
* **Nothing is saved, and the part is left unchanged:** NX counts the part as modified while the objects are
  hidden, and the undo that shows them again clears that, so closing the part does not ask you to save.

## Settings at the top of the script

* `BACKGROUND = (1.0, 1.0, 1.0)`: the picture's background as red, green, blue from 0 to 1; `None` keeps NX's own
  background.
* `HIDE_TYPES = ("Sketches", "Datums", "AssemblyConstraints")`: what is left out of the picture, as names from NX
  Open's `DisplayManager.ShowHideType` (for example add `"Pmi"` to leave out PMI, or `"Curves"`); `()` hides
  nothing.
* `DEBUG = False`: `True` writes to the NX log (Help → Log File), step by step, which parts NX counts as
  modified, and the view triad settings.

## Good to know

* If NX could not show the hidden objects again, the message box says so: **Edit → Undo** (Ctrl+Z) brings them
  back; the undo step is named "Screenshot to Clipboard".
* A bigger NX window gives a bigger picture.
* If NX asks to save a part after a screenshot, look for an edit of your own: an edit to a component (an Offset
  Region, say) also makes the assembly count as modified.
