# Create McMaster Part (NX Open)

NX Open (Python) automation for **NX 2506** in **Teamcenter managed mode**. Enter
a McMaster-Carr part number and it scrapes the product data, downloads the CAD,
creates a `BE9_COTS` part in Teamcenter, and imports the geometry — prompting
through BlockStyler dialogs along the way.

The main tool is `NX-Scripts/Create-McMaster-Part/CREATE_MCMASTER_PART.py` —
the McMaster/COTS flow (part number → scrape → create → import).

## Prerequisites

* **NX 2506** with an active **Teamcenter** session (managed mode).
* **Microsoft Edge** (pre-installed on Windows 10/11) — the scraper drives it.
* **Python 3.10+** on the machine (for the scraper). Get it from
  <https://www.python.org/downloads/> and tick *"Add python.exe to PATH"*.

## Create a part


1. Open **NX 2506** with a Teamcenter session.
2. **File → Execute → NX Open…** → select `NX-Scripts/Create-McMaster-Part/CREATE_MCMASTER_PART.py`.
3. Enter the **McMaster part number** when prompted. If that part already exists in
   Teamcenter the tool opens it and stops (see Notes).
4. The tool scrapes the product data, downloads the no-threads Parasolid CAD to
   `C:\TEMP\MCMASTER` (NX is busy for a few seconds), and shows a **Part Name** dialog
   pre-filled with the description (edit if you like).
5. It creates the `BE9_COTS` part, sets its attributes, and imports the CAD, moves the
   imported bodies to **layer 71**, and **zooms the view to fit** them. When it is done, the
   new part is on screen and nothing pops up (the same when the part already existed and
   was opened). The **Listing Window** opens only when a run stops without a part on screen
   (you cancel after entering a part number, or something fails), and shows what happened.

Attributes set: `DB_PART_NO` = part number, `DB_PART_NAME` = the name you
confirm (pre-filled with the product title, all caps), `HE_Manufacturer` =
`MCMASTER-CARR`, `Part Class` (`be9_PartClass`) = `Class II`, and the part revision is set to `NC`
(`DB_PART_REV`). Creation is done by
`create_vendor_part` in `lib/vendor_part.py`.

Keep each script next to its `.dlx` dialog file(s); the scraper (`lib/scraper/`)
and `.venv` are found automatically at the repo root.

## Repository layout

The repo is organized by where code runs:

* `NX-Scripts/` — scripts the user runs **inside NX** (File → Execute → NX
  Open…). The main tool is
  `NX-Scripts/Create-McMaster-Part/CREATE_MCMASTER_PART.py` and its `.dlx`
  BlockStyler dialogs.
* `lib/` — shared helpers the NX scripts import (`mcmaster.py`, `teamcenter.py`,
  `nx_dialogs.py`). NX scripts keep only the user-facing flow; everything they
  call lives here. `lib/scraper/` is the McMaster-Carr Selenium scraper, run
  **outside NX** as a subprocess.
* `example_journals/` — journals **recorded in NX** (Tools → Journal →
  Record), kept as reference examples for reverse-engineering NX Open calls.
  Not executed directly.
* **Repo root** — `setup.bat` (one-click setup), `requirements.txt`, `.venv/`
  (Python env for the Tools; git-ignored), `README.md`, and `HANDOFF.md`.

| Path | Purpose |
|----|----|
| `setup.bat` | One-click setup: venv + dependencies + McMaster login. |
| `requirements.txt` | Python deps for the scraper (Selenium + the corporate-SSL helper). Installed by `setup.bat`. |
| `NX-Scripts/Create-McMaster-Part/CREATE_MCMASTER_PART.py` | Main tool: part number → scrape → create COTS part → import CAD. |
| `NX-Scripts/Create-McMaster-Part/*.dlx` | BlockStyler dialogs for the flow (part number, part name). |
| `lib/` | Shared helpers called by the NX scripts (scraper wrapper, Teamcenter create/check, dialogs). |
| `lib/scraper/` | Vendored McMaster-Carr scraper (Selenium). See `lib/scraper/VENDORED.md`. |
| `example_journals/` | Recorded NX journals used as reference (e.g. the working COTS-create). |
| `.venv/` | Python venv with Selenium (created by `setup.bat`; git-ignored). |
| `HANDOFF.md` | Deeper notes: key functions, gotchas, open items. |

An NX script locates the repo root by walking up the folder tree, so it finds
`lib/` and `.venv/` regardless of how deep it sits under `NX-Scripts/`.

## Notes

* Targets **Teamcenter managed mode** (not native/filesystem mode).
* If the part has **no downloadable CAD** (some raw stock and bulk items have no
  3-D Parasolid model, e.g. `5887K51`), the tool shows the reason and asks whether
  to create the part **without geometry**. **No** stops with nothing created in
  Teamcenter; **Yes** creates the part and skips the Parasolid import.
* If the part number **already exists** in Teamcenter, the tool doesn't scrape or
  create anything — it **opens the existing part** instead (latest working
  revision).
* The scraper needs a McMaster login (cached in a dedicated Edge profile). If the
  session expires, the tool opens a sign-in window automatically.
* See `HANDOFF.md` for the full list of NX Open / Teamcenter gotchas.


