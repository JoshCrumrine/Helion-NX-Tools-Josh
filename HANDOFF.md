# Handoff — NX Open "Create Part" automation

Automates creating a McMaster-Carr COTS part in **NX 2506** running in
**Teamcenter managed mode**: enter a part number, scrape its data + CAD, and
create the `BE9_COTS` item with the imported geometry.

## Environment

- **NX 2506**, Python (CPython) journals run via **File → Execute → NX Open…**.
- Runs in **Teamcenter managed mode** (not native/filesystem mode). This changes
  everything about how parts are created (see gotchas).
- Custom Helion item types: `BE9_Design, BE9_Electrical, BE9_COTS, BE9_Tooling`
  (the part is created as `BE9_COTS`).
- Default template: `@DB/model-plain-1-inch-template/A` (units = inches).
- An `nxopen` MCP server (shipped as `NX_Open_MCP.zip`; `setup.bat` extracts it to
  the git-ignored `MCP/` and writes `.mcp.json` via `setup_mcp.ps1`) indexes the NX 2506 Python API and
  stubs — use it to look up signatures. **Note:** it does **not** index
  `NXOpen.UF` (that subsystem has no stubs on disk).

## Repository layout

Organized by where the code runs:

- **`NX-Scripts/`** — scripts executed **inside NX** (File → Execute → NX Open…).
- **`lib/`** — shared helpers the NX scripts import. `lib/scraper/` is external
  code run **outside NX** as a subprocess.
- **`example_journals/`** — journals **recorded in NX** (Tools → Journal →
  Record), kept as reference for reverse-engineering NX Open calls. Not run
  directly.
- **Repo root** — `setup.bat`, `requirements.txt`, `.venv/` (git-ignored), and
  the docs.

An NX script finds the repo root by walking up, so it locates `lib/` and
`.venv/` no matter how deep it sits under `NX-Scripts/`.

### Files

| Path | Purpose |
|------|---------|
| `NX-Scripts/Create-McMaster-Part/CREATE_MCMASTER_PART.py` | **Main tool.** Scraper-driven COTS flow: prompt for a part number → scrape JSON + download CAD → derive attributes → prompt for part name → create the `BE9_COTS` part → import the CAD. |
| `NX-Scripts/Create-McMaster-Part/CREATE_MCMASTER_PART_partno_dialog.dlx` | Single-field "Part Number" dialog (block id `partNo`) — step 1. |
| `NX-Scripts/Create-McMaster-Part/CREATE_MCMASTER_PART_partname_dialog.dlx` | Single-field "Part Name" dialog (block id `partName`) — prefilled with the description; sets `DB_PART_NAME`. |
| `NX-Scripts/Check-Part-Exists/check_part_exists.py` | Standalone diagnostic: checks whether an item id already exists in Teamcenter by trying `GetConfiguredRevisionOfItems` across several revision rules and printing which resolve it. Used to find the working rules for the main tool's pre-check. |
| `lib/scraper/` | Vendored copy of the McMaster-Carr scraper (`br435t/McMaster-scraper`). See `lib/scraper/VENDORED.md`. Run as a subprocess, not imported into NX. |
| `example_journals/journal_create_vendor_part.py` | Fresh **working** recording of the COTS create (creates `ID.A/Name`). Source of truth for the required attributes; `lib/vendor_part.py::create_vendor_part` is built from it. |
| `example_journals/journal_import_Parasolid.py` | Recorded File → Import → Parasolid journal the `import_parasolid()` helper was derived from. |
| `NX_Open_MCP.zip` / `MCP/` / `.mcp.json` | NX Open API MCP server: zip is committed; `setup.bat` extracts it to `MCP/` and writes `.mcp.json` (both git-ignored) pointing at `.venv` python. |

## COTS / vendor parts (`CREATE_MCMASTER_PART.py`)

Creates a `BE9_COTS` item. Differs from the Design flow in three ways:

- **Item type** is `BE9_COTS` (not `BE9_Design`).
- **Part number is user-supplied** (the vendor/manufacturer PN), written as the
  `DB_PART_NO` attribute — *not* auto-assigned from a naming pattern.
- **Attributes span two categories:** `DB_PART_NO`/`DB_PART_NAME` on `BE9_COTS`;
  `HE_Manufacturer`/`Item:revision:ItemRevision:be9_PartClass`/`DB_PART_REV` on
  `BE9_COTSRevision`. (`DB_PART_DESC` is no longer set.) The revision is `"NC"`
  (`_PART_REVISION` in the script; recording
  `example_journals/journal_create_vendor_part_with_NC_rev.py`), so the part is
  `<id>.NC` instead of `<id>.A`. `DB_PART_REV` is set *before* the naming-map
  step, as in that recording.

### Flow (`main()`)

This is the recorded journal wired to the scraper. `main()` does:

1. **Prompt for a part number** (`CREATE_MCMASTER_PART_partno_dialog.dlx`).
1b. **Existence pre-check** (`find_item_revision_spec`) — if the id already exists
   in Teamcenter, stop before the scrape and **open the existing part**
   (`open_teamcenter_part` → `Parts.OpenActiveDisplay(spec, AllowAdditional)`,
   using the `ItemRevisionCliSpec` the check returned). If it can't be opened, an
   error box is shown. Nothing is created or scraped. See gotcha #9.
2. **`fetch_mcmaster(pn)`** — runs the external scraper's `fetch` command, one Edge
   session that writes `<pn>.json` and downloads the default 3-D Parasolid,
   **no-threads** `*.X_T` into `C:\TEMP\MCMASTER` (about 3-4 s). There is no
   notice for this step; NX is busy until the part-name prompt (step 4) appears.
2b. **No-CAD prompt** — if no `*.X_T` was downloaded (part has no 3-D model, e.g.
   `5887K51`; no no-threads Parasolid variant; download failed), show the reason
   and ask (`ask_yes_no`, `lib/nx_dialogs.py`) whether to create the part
   **without geometry**. **No** aborts before anything is created; **Yes**
   continues with `cad_file = None` and step 6 is skipped. (An empty part has to
   be deleted by hand if it wasn't wanted, hence the prompt.)
3. **Derive attributes:** `part_no` = scraped `part_number`; the default part
   name = `build_description()` = `title_primary` + `title_secondary`, concatenated and
   **UPPERCASED**; `HE_Manufacturer` = `"MCMASTER"`; `Part Class` = `"Class III"`.
4. **Prompt for the part name** (`CREATE_MCMASTER_PART_partname_dialog.dlx`), prefilled
   with the description as an editable default → `DB_PART_NAME`.
5. **`create_vendor_part()`** (`lib/vendor_part.py`) creates the `BE9_COTS` part
   in `:MCMASTER` (empty naming map, `DB_PART_NO` as an attribute).
   Mapping: ID → `DB_PART_NO`, Name → `DB_PART_NAME`, Manufacturer →
   `HE_Manufacturer`, Part Class → `be9_PartClass`, Revision → `DB_PART_REV`
   (`"NC"`).
6. **Import the downloaded Parasolid** (`import_parasolid()`) into the newly
   created work part — using the actual `*.X_T` path from step 2. Import happens
   after `Commit()` because the part must exist first. Skipped when the user chose
   to continue without CAD in step 2b.

Notes: a scrape failure aborts (the description depends on it); a missing CAD file prompts
(step 2b). Output dir is `C:\TEMP\MCMASTER`
(constant `MCMASTER_OUT`). Auto-login is left enabled, so an expired session
pops a sign-in window. The full flow (dialogs, existence pre-check, create, and
Parasolid import) is verified end to end in NX on a fresh part.

### McMaster scraper integration

`CREATE_MCMASTER_PART.py` shells out to the vendored `lib/scraper/mcmaster_scraper.py`
to fetch property data by part number. **It runs the scraper as a subprocess in
an external Python interpreter**, because the scraper needs Selenium + a real
Edge browser, which are not available in NX's embedded Python.

- Interpreter selection (`scraper_python()` in `lib/mcmaster.py`): `MCMASTER_SCRAPER_PYTHON` env var
  → the repo-root `.venv` (found by walking up from the script) → `python` on
  PATH. No env var needed if `.venv` exists — the script auto-detects it.
- Setup (once): run `setup.bat` at the repo root (creates `.venv`, installs
  `requirements.txt` behind the corporate proxy, and runs the
  McMaster `login` to cache the session).
- `wait_for_fetch()` (and the one-call `fetch_mcmaster()`) returns a dict with
  `data` / `json_file` / `cad_file` and `error` / `cad_error`; it never raises.
  Either error aborts creation: the scrape supplies the description, and a part
  with no CAD has nothing to import.
- The scraper reports its outcome, including errors such as "no 'parasolid' (no
  threads) option for this part", in `C:\TEMP\MCMASTER\<pn>.result.json`, which
  it writes **before** closing Edge. `wait_for_fetch()` returns as soon as that
  file appears instead of waiting the ~2 s Edge takes to quit. The scraper's
  console output goes to `C:\TEMP\MCMASTER\<pn>.log`.

## How to run

1. One-time setup: run `setup.bat` at the repo root (creates `.venv`, installs
   `requirements.txt`, and caches the McMaster login).
2. Open NX 2506 with a Teamcenter session active.
3. **File → Execute → NX Open…** → select
   `NX-Scripts/Create-McMaster-Part/CREATE_MCMASTER_PART.py`.
4. Enter the McMaster part number. The tool scrapes the data, downloads the CAD,
   prompts for the part name, creates the `BE9_COTS` part, and imports the CAD.
   A run that ends with the part open (created, or already in Teamcenter and
   opened) shows no window. Otherwise (cancelled or failed) its log goes to the
   Listing Window at the end. The log is held in `DeferredListing`
   (`lib/nx_dialogs.py`) because, written earlier, the Information window pops
   up over the dialogs and takes their keyboard focus.

## Gotchas discovered (hard-won — don't re-learn these)

1. **Managed vs native mode.** In Teamcenter mode you must drive creation through
   `theSession.PdmSession.CreateCreateOperationBuilder(...)` →
   `PDM.PartOperationCreateBuilder`. A plain `FileNew.Commit()` (native path) fails
   with "The selected template doesn't exist".
2. **Template ref format:** `@DB/<template>/<rev>`, e.g. `@DB/model-plain-1-inch-template/A`.
3. **`FileNew.UsesMasterModel` is a string** (`"No"`/`"Yes"`), not a bool.
4. **Explicit subpackage imports:** `import NXOpen` does not pull in subpackages —
   need `import NXOpen.PDM`, `import NXOpen.BlockStyler`, etc.
5. **Destination folder** comes from `theSession.PdmSession.GetUserName()` — don't
   hardcode the user.
6. **UF `AskStringInput` is a trap** (this is why we moved to BlockStyler):
   - Its `str` arg is a **ref buffer** that must be exactly **133 chars**
     (`" " * 133`); `""` returns empty regardless of input.
   - It needs `Ui.LockUgAccess(UF_UI_FROM_CUSTOM)` / `UnlockUgAccess` around it or
     no dialog appears.
   - Its `cue` shows in the **status/cue line**, never inside the box.
7. **BlockStyler dialogs require callbacks** registered before `Show()`, or NX
   raises "The Initialize callback is not registered in automation code". Register
   `AddInitializeHandler`, `AddUpdateHandler` (cb takes a `block` arg, returns 0),
   `AddOkHandler`, `AddApplyHandler`. Read block values **inside** the OK/Apply
   callback, not after `Show()`.
8. The `.dlx` was hand-built from NX's own sample
   `C:\SPLM\NX\NX2506\MACH\auxiliary\sme\setLicense.dlx` to guarantee a valid schema.
9. **A duplicate item id is the *real* cause of "The new filename is not a valid
   file specification" at `Commit()`.** The message is a red herring — it is NOT
   about illegal filename characters (`/`, `"`) or the create call sequence.
   `GetOperationFailures()` after `ValidateLogicalObjectsToCommit()` reveals the
   truth: operation-failure **code 940519**, *"Cannot create a new revision of an
   existing part using New. Use Save As for this operation."* The item already
   exists in Teamcenter.
   - **Pre-check:** `find_item_revision_spec()` (`item_exists_in_teamcenter()` is a
     True/False wrapper) uses
     `PdmSession.GetConfiguredRevisionOfItems` to resolve the id *before*
     creating. This needs a **revision rule**: an empty rule resolves nothing
     (false "not found"). The rules that work here are **`Latest Working`** and
     **`Any Status; Working`**; `Latest Released` / `Precise` / `Latest` / empty
     do **not** (verified via `check_part_exists.py`). The check returns the spec
     of the first rule that resolves the id (`Latest Working` first, so the latest
     working revision is the one opened).
   - **Reading the failure:** `ErrorMessageHandler.GetErrorMessages()` returns
     NULL for these PDM builders; use `GetOperationFailures()` →
     `NXOpen.ErrorList` → `GetErrorInfo(i)` → `.ErrorCode` / `.Description`
     instead. `dump_pdm_errors()` in `lib/teamcenter.py` wraps this.
10. **BlockStyler string fields re-show the previous run's text (even after an NX
   restart).** The Part Number dialog opened with the last Part Name
   pre-fill (a product description) in its field instead of blank. Both `.dlx`
   dialogs share the title "Create Vendor Part", and NX restores saved field
   values **after** the initialize callback runs, so clearing only in
   `AddInitializeHandler` did **not** stick. What was tried:
   - Setting the string block's `RetainValue` property to `False` in both `.dlx`
     files: kept (it made the part-name dialog open empty before its pre-fill),
     but alone it was **not enough** for the Part Number field.
   - Clearing/setting `Value` + `WideValue` in the initialize callback: not enough.
   - **Fix that works:** also reset the field in an **`AddDialogShownHandler`**
     callback, which fires once the dialog is on screen, after NX has restored
     values. `prompt_string()` in `lib/nx_dialogs.py` calls the same `_reset()`
     (set `default`, or `""`) from both callbacks.
   - Diagnosing it needed before/after logging of `GetString("Value")` /
     `("WideValue")` at each callback; that logging has since been removed.
11. **Restart NX after editing anything under `lib/`.** NX's embedded Python keeps
   imported modules for the whole NX session, so a changed `lib/*.py` file is not
   re-read on the next *File → Execute → NX Open…* run — the old code keeps
   running. Seen when setting the part revision to `NC`: the updated
   `create_vendor_part(..., revision="NC")` still produced revision `A` until NX was
   restarted, then worked. The script file you select in the Execute dialog is
   re-read each run; the `lib` modules it imports are the cached part. The same
   applies to `.dlx` edits (see #10). **Rule: edit `lib/` or a `.dlx` → restart NX
   before testing**, and don't conclude a fix failed until you have.

## Status / open items

- **Verified end to end in NX:** prompt flow, existence pre-check, Teamcenter
  `BE9_COTS` creation, and Parasolid import all confirmed on a fresh part.
  Creating an id that already exists is now caught up front (gotcha #9) instead
  of failing cryptically at `Commit()`.
- The `.dlx` dialogs were authored by hand and haven't been round-tripped through
  Block UI Styler, but load and work in practice.
- The created part is not explicitly **saved to Teamcenter** after `Commit()` (the
  recorded journal didn't either). If a DB save is needed, add it.
- `part_class` is fixed at `"Class III"` — make it a dialog field if it should vary.
- **COTS flow:** the scraper is wired for **log-only**. Next step (when ready) is
  to map scraped fields onto attributes (e.g. title → `DB_PART_NAME`, secondary/
  specs, `HE_Manufacturer` → `McMaster-Carr`) and optionally
  write each spec as its own NX user attribute.
- **COTS dialogs (`.dlx`)** are hand-authored and not round-tripped through NX's
  Block UI Styler.
- `Part Class` is fixed at `"Class III"`; make it a dialog field if it needs to
  vary.
