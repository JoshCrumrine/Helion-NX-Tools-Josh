<!-- fullWidth: false tocVisible: false tableWrap: true -->
# Color By Material (NX Open)

NX Open (Python) script for **NX 2506**. It walks the displayed assembly and\
colors every body according to its **NX physical material**, using the hex codes\
in `Materials/NX_Materials.csv`. A body whose material is `G-10 Garolite` gets\
whatever color that row has in the `color` column, and its transparency from the\
`Transparency` column.

Four scripts in `NX-Scripts/Color-By-Material/`:

| Script                               | Changes                                                                | Assembly color overrides                                                 |
| ------------------------------------ | ---------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `color_by_material.py`               | The **component parts**                                                | **Cleared** on every component first, so the new part colors show        |
| `color_by_material_asm_leave_color.py` | The **component parts**                                                | **Left alone**; a component with an assembly level override keeps showing it |
| `color_by_material_assembly_level.py` | **Only the assembly**: a display override on each body occurrence      | Not touched; no part is modified                                         |
| `assign_and_color_materials.py`      | The **component parts**, and it **assigns materials** to bodies that have none (and updates the mass properties) | **Cleared** first, like `color_by_material.py`                           |

The first two are otherwise identical. Use `color_by_material_asm_leave_color.py`\
when you want to keep colors someone set deliberately in the assembly.

Use **`assign_and_color_materials.py`** when some bodies have no material yet: it is\
`color_by_material.py` plus a prompt for each such body. See\
[Assign and color script](#assign-and-color-script).

Use **`color_by_material_assembly_level.py`** when you only want to *look* at the\
assembly colored by material without changing any part: nothing is made the work\
part, read-only parts do not matter, and the colors exist only in this assembly.\
See [Assembly-level script](#assembly-level-script). The rest of this README\
describes the part-modifying scripts, except where noted.

## Before you run it

- Open the **assembly** in NX 2506 (it must be fully loaded, or unloaded\
  components are skipped).
- **Check out the parts you want to change** if you are in Teamcenter. The color\
  is written into each component's own part, and read-only parts cannot be saved\
  (see [Read-only parts](#read-only-parts)).
- Add hex codes to the `color` column, and optionally a value in the `Transparency`\
  column, of `Materials/NX_Materials.csv` for the materials you want changed (see\
  [Material colors and transparency](#material-colors-and-transparency)).
- **Try it on a copy of the assembly first.** It modifies the component parts,\
  and a part's color then changes in every assembly that uses it.

## Run it

1. In NX: **File → Execute → NX Open…** and pick `color_by_material.py` (or\
   `color_by_material_asm_leave_color.py`).
2. Read the Listing Window.
3. Review the result in the graphics window, then **File → Save All** to keep it.\
   The script never saves for you.

## What it does

1. Loads every row of `Materials/NX_Materials.csv` that has a `color` and/or a\
   `Transparency`.
2. **`color_by_material.py` only:** clears the assembly-level color override on\
   every component (the same as unticking *Specific color* in Edit → Properties),\
   so part colors are visible. `color_by_material_asm_leave_color.py` skips this\
   step, which is the only difference (each script is a few lines that call\
   `lib/color_by_material.py` with `clear_overrides` `True` or `False`).
3. Collects each **distinct part** in the assembly once, however many instances\
   there are. The **active (displayed) part itself is included**, so bodies modeled\
   directly in it are colored too, not only those in its child components. They\
   show as `<part> (active part)` in the Listing Window.
4. For each part, makes it the work part, reads the NX material of each body, and\
   sets the body (and all its faces) to the color and transparency for that\
   material. Then it\
   switches back to your displayed part.

Suppressed and unloaded components are ignored.

## Assembly-level script

`color_by_material_assembly_level.py` sets the color and transparency as a display\
override on each **body occurrence** in the displayed assembly. The same CSV,\
palette mapping and no-material color apply.

- **Child component parts are not modified**, so there is nothing to check out and\
  no read-only problem. The override is stored in the assembly.
- It does **not clear** existing component-level overrides, and it does not need\
  to. If a component carries its own override and a body still looks unchanged, run\
  `color_by_material.py` first, or clear that override in Edit → Properties.
- **Exception, the active part's own bodies:** bodies modeled directly in the\
  displayed part are not occurrences, so there is nothing to override. They are\
  colored on that part itself (it becomes modified), and listed as\
  `<part> (active part)`.
- Nothing is saved for you. Save the assembly if you want to keep the changes.
- Listing Window lines are `component / body -> material, NX color, transparency`,\
  with `x<count>` when the same component and body repeat.
- To undo, use Edit → Undo, or close the assembly without saving. NXOpen has no\
  call to remove an override (see the note on body-level overrides below).

## Assign and color script

`assign_and_color_materials.py` does everything `color_by_material.py` does. The difference\
is what happens to a body that has **no material**: instead of just coloring it with the\
no-material color, it asks you which material it should have.

- **One dialog per body** without a material. The dialog's heading names the part and the\
  body (`1150201-500/01 / BODY 1: no material. Pick one:`) and the list is the whole material\
  library (the names in `Materials/NX_Materials.csv`, sorted).
- **Search box:** type part of a material name and press **Enter** (or Tab) to narrow the list.\
  Every word you type must appear in the name, in any order, ignoring case: `alum 60` finds\
  `Aluminum 6061`, `steel 304` finds `Stainless Steel AISI 304`. If exactly one material matches\
  it is selected for you, so you can just press OK. Clear the box and press Enter to see the\
  whole library again. The list filters when you press Enter, not as you type (a limit of NX
  text boxes).
- **The body is highlighted** in the graphics window while its dialog is open, and\
  un-highlighted when you answer, so you can see which one you are choosing for. The view is\
  never moved or zoomed. If the body is hidden the heading says `(this body is hidden)`; a body\
  outside the current view or on a hidden layer cannot be seen even though it is highlighted, so\
  Fit the view first if you cannot find it.
- **OK** with a material selected assigns it to the body, and the body is then colored with that\
  material's `color` and `Transparency` from the CSV, exactly as if it had had the material all along.
- **Cancel**, or OK with nothing selected, **skips that body**. A skipped body gets the no-material\
  color (`#ff00ff`), as in `color_by_material.py`.
- **"CANCEL THE WHOLE OPERATION"** (the other toggle in the dialog) ends the run. Tick it and press OK or\
  Cancel; no more dialogs are shown and no more parts are changed. **What was already done is kept** (the\
  parts finished so far stay assigned and colored, and the one you were on keeps the materials you had\
  already picked for it), nothing is rolled back, and the Listing Window says how many parts were never\
  reached. Cancel on its own still only skips the current body. This is the only place the run can be\
  stopped, because NX gives a script no other way to interrupt it; the run between dialogs takes seconds.
- **"Stop asking"** (a toggle in the dialog) skips every remaining body without a material, with no\
  more dialogs. Tick it together with a selection and that body is still assigned.
- Prompts are **per body of each distinct part**: a part used 20 times is asked once per body, not\
  20 times, because the material belongs to the part. The active part's own bodies are included.
- **Mass properties:** once a part's bodies have their new materials, the part's mass properties are\
  updated (Analysis → Mass Properties → Update Now, as the Assign Material script does), so its weight\
  uses the new densities. Then every assembly that holds such a part is updated too, deepest\
  subassembly first and the displayed assembly last, so the assembly weights add up. A part whose bodies\
  all had a material already is not touched. This happens after a cancel too, for what was assigned.
- The Listing Window ends with `Materials assigned from the prompt`, one line per assignment,\
  `Could not assign` for any failure with NX's reason, and `Mass properties updated for the new\
  materials` with the parts and assemblies whose weight was updated.

**This modifies the parts three ways**: the material assignment, the color and the weight. None is saved;\
review, then File -> Save All. A read-only part (for example not checked out of Teamcenter) can\
still be assigned and colored in the session but cannot be saved as-is, same as for the coloring.\
Try it on a copy first.

The assignment itself is what NX records in `example_journals/journal_assign_material.py`:\
the library material is loaded into the part if it is not already there, then assigned to the body.\
It is loaded from the Helion MatML library file the material came from (the `source_file` column of\
`NX_Materials.csv`: `helion_material_library.xml`, or `Gas_and_Liquid_helion_material_library.xml`\
for the gas and liquid materials), found in `MATERIAL_LIBRARY_DIR` at the top of\
`lib/color_by_material.py` (the site's "Site MatML Library" folder). NX's own built-in default library\
is switched off at Helion, so it is only tried as a last resort.\
NX's own Assign Material dialog cannot be driven from a script (the recorded journal captures\
nothing from it), so this is a native NX BlockStyler dialog (`ASSIGN_MATERIAL_dialog.dlx`) built for\
the purpose, like the part-number dialog in Create-McMaster-Part.

If the library material cannot be loaded (for example the library folder is unreachable, or the name\
is not in the file) the body is reported under `Could not assign`, listing each place that was tried and\
what NX said about it, and colored with the no-material color.

## Material colors and transparency

`Materials/NX_Materials.csv` lists every material from the Helion NX libraries.\
The `color` and `Transparency` columns are hand-maintained:

```
name,...,color,Transparency
G-10 Garolite,...,#03fcad,0
Glass,...,#fcf8f0,90
Stainless Steel 304,...,#bcc3c4,
Rubber,...,91,
```

- `color` is a **hex code** (`#03fcad`) **or an NX color ID** (`91`).
  - Starts with `#` → hex, mapped to the nearest NX palette color.
  - A whole number from **1 to 216** → used directly as the NX color ID. There is\
    no approximation, so this is how to get an exact NX palette color.
  - Exactly six hex digits with no `#` (`03fcad`) → hex.
  - Anything else is ignored and listed at the end of the Listing Window.
  - Watch out when a spreadsheet strips the `#`: a six-digit all-number hex code\
    such as `100000` is read as hex, but `91` is read as ID 91. Keep the `#` to\
    be safe.
- `Transparency` is a number from **0 (opaque) to 100 (fully clear)**, which is NX's\
  translucency setting. Values outside that range are clamped, and a value that is\
  not a number is ignored.
- Either column can be left blank. A blank `color` keeps the body's current color\
  and a blank `Transparency` keeps its current transparency. **A `0` is not the\
  same as blank**: `0` actively sets the body to opaque.
- Materials are matched by **name**, case-insensitively, against the material\
  assigned to the body in NX.
- A material with neither a `color` nor a `Transparency` leaves its bodies unchanged.
- **Bodies with no material** are colored `#ff00ff` (magenta, so they stand out) and\
  listed as `(no material)`. Change `NO_MATERIAL_COLOR` at the top of\
  `lib/color_by_material.py`, or set it to `None` to leave them alone.
- Rebuilding the CSV with `Materials/build_nx_materials_csv.py` keeps both columns;\
  it carries them over by material name.

### The NX palette limit

NX bodies can only use the **216-color NX palette**, so each hex code is mapped to\
the **nearest palette color**. `#03fcad` will be close, not exact. Use an NX color\
ID in the `color` column when you need an exact palette color. The Listing\
Window shows the NX color number that was used for each body so you can see what\
you got.

## The Listing Window

```
12 materials have a color in ...\Materials\NX_Materials.csv
36 distinct parts in the assembly
Cleared assembly color override on 36 components   (color_by_material.py only)

Bodies changed (part / body -> material, NX color, transparency):
  91247A505/NC / 91247A505_... Hex Head Screw -> Alloy Steel, NX color 91, transparency 0  (used x4)

Changed 34 bodies in 21 parts (modified, NOT saved).
```

At the end it also lists:

- **Read-only parts**, which were colored in this session only.
- **Skipped parts**, which NX would not let the script change, with the reason.
- **Left unchanged**, the materials that had no color or transparency in the CSV, plus bodies with\
  no material only when `NO_MATERIAL_COLOR` is `None`, each with a count.

## Read-only parts

Read-only parts (for example, not checked out of Teamcenter) are still colored in\
your session and are listed in the Listing Window. They cannot be saved over their\
own file, so those colors will not persist. Check the part out and run the script\
again if you want to keep them.

## If a body doesn't change color

- **No material** — it should get the magenta `#ff00ff`. If you see it left\
  unchanged, `NO_MATERIAL_COLOR` has been set to `None`. To give such bodies a real material\
  instead, run `assign_and_color_materials.py`.
- **No color or transparency for its material** — add a hex code and/or a\
  transparency value for that material in the CSV. Check\
  the spelling matches the material name in NX.
- **An assembly color override** — with `color_by_material_asm_leave_color.py`\
  this is expected: the override on the component hides the new part color. Run\
  `color_by_material.py` to clear it.
- **A body-level color override** — neither script clears these. A color set\
  directly on a body occurrence in the assembly can still hide the part color.

## Related files

- `lib/color_by_material.py` — the shared implementation (`run(clear_overrides)`)\
  both scripts call. Change behavior here, not in the scripts.
- `lib/colors.py` — hex → nearest NX color, `set_body_color` (color and/or\
  translucency),\
  `clear_component_color_override`.
- `lib/assemblies.py` — `walk_components`, `get_bodies`, `get_body_material`.
- `Materials/build_nx_materials_csv.py` — regenerates the CSV from the XML\
  material libraries in a dated folder under `Materials/`.
- `example_journals/remove_assebly_color_override.py` — the recorded journal the\
  override-clearing code is based on.