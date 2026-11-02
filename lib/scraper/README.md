# McMaster-Carr Scraper

A small Selenium-based tool for extracting product data and downloading CAD
models from [mcmaster.com](https://www.mcmaster.com) by part number.

McMaster product pages render entirely client-side — the product title, price,
specs, and CAD links are injected by JavaScript and are **not** present in the
raw HTML. A plain HTTP request (`requests`, `curl`, etc.) only sees the empty
app shell. This tool therefore drives a real headless browser (Microsoft Edge)
so the page's JavaScript runs before data is read.

## Requirements

- **Windows** with **Microsoft Edge** installed (Chromium-based; pre-installed
  on Windows 10/11).
- **Python 3.10+**.
- Selenium (see [requirements.txt](requirements.txt)). Selenium 4.6+ bundles
  *Selenium Manager*, which automatically downloads the matching
  `msedgedriver` on first run — no manual driver setup.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> If `python` resolves to the Windows Store stub, use a real install
> explicitly, e.g. `C:\Users\<you>\AppData\Local\Programs\Python\Python312\python.exe`.

## Log in first (required)

McMaster now gates product pages behind a login wall ("To continue browsing,
please log in") that appears intermittently for anonymous visitors. The tool
uses a persistent Edge profile so a login is reused across runs.

**You usually don't need to log in manually.** When `scrape`, `cad` or `fetch`
hits the login wall, it automatically opens a browser window and waits for you to sign
in, then continues on its own. To log in ahead of time (or refresh the
session), use the `login` subcommand:

```powershell
# Opens a browser window — log in to McMaster in it. Exits once login succeeds.
python mcmaster_scraper.py login
```

The session is stored in a dedicated Edge profile at
`%USERPROFILE%\.mcmaster-scraper\edge-profile` (override with `--profile DIR`).

For unattended/CI runs where no one can complete a browser login, pass
`--no-auto-login` to `scrape`/`cad`/`fetch` so a missing session reports an
error instead of blocking on a login window.

## Usage

The CLI has four subcommands: `login`, `scrape`, `cad`, and `fetch`.

### Scrape structured product data → JSON

```powershell
# Single part → writes 91274A004.json in the current directory
python mcmaster_scraper.py scrape 91274A004

# Multiple parts → one file each: 91274A004.json, 90128A111.json
python mcmaster_scraper.py scrape 91274A004 90128A111

# Choose the output directory (files are still named <part>.json)
python mcmaster_scraper.py scrape 91274A004 --out C:\data

# Print JSON to stdout instead of writing files (for piping into jq, etc.)
python mcmaster_scraper.py scrape 91274A004 --stdout

# Watch the browser do it (debugging)
python mcmaster_scraper.py scrape 91274A004 --headful
```

By default each part is exported to its own `<part>.json` file (in `--out`,
which defaults to the current directory). Use `--stdout` to print instead.
See [examples/](examples/) for sample output of part `91274A004`.

Returned fields per part: `title`, `title_primary`, `title_secondary`,
`title_html_block`, `part_number`, `price`, `delivery`, `page_title`,
`specs` (list of `{group, label, value}`), and `url`. Invalid or
bot-blocked parts return an `error` field instead of crashing the batch.

### Download a CAD model

Defaults to **3-D Parasolid without threads** (`.X_T`).

```powershell
# Default: 3-D Parasolid, no threads → current directory
python mcmaster_scraper.py cad 91274A004

# Pick an output folder
python mcmaster_scraper.py cad 91274A004 --out C:\cad

# With-threads variant
python mcmaster_scraper.py cad 91274A004 --threads

# Other formats: parasolid | step | iges | sat | solidworks | pdf
python mcmaster_scraper.py cad 91274A004 --format step

# List every CAD option available for the part (and exit)
python mcmaster_scraper.py cad 91274A004 --list

# Machine-readable JSON output (works with --list, downloads, and errors)
python mcmaster_scraper.py cad 91274A004 --list --json
python mcmaster_scraper.py cad 91274A004 --json
```

With `--json`, `cad` prints structured output to stdout: `--list` gives
`{part_number, options:[{label, path}]}`; a download gives
`{part_number, label, path, file, bytes}`; any failure gives
`{part_number, error}`. Progress notes (`[selected] …`) go to stderr, so stdout
stays pure JSON.

The file is downloaded **through the browser's own session** (in-page
`fetch(..., {credentials:'include'})`) so McMaster's cookie/origin checks pass,
then written to disk under its original filename.

### Scrape and download the CAD in one go (`fetch`)

```powershell
# <part>.json + the no-threads Parasolid into C:\data, one browser session
python mcmaster_scraper.py fetch 91274A004 --out C:\data

# Also write the result JSON to a file, before the browser is closed
python mcmaster_scraper.py fetch 91274A004 --out C:\data --result C:\data\91274A004.result.json
```

`fetch` does `scrape` + `cad --json` for one part while starting the browser
and loading the page only once, so it takes about half as long. It takes the
same `--format`, `--threads`, `--profile` and `--no-auto-login` options as
`cad`, and prints one JSON object: `{part_number, json_file, error, label,
path, file, bytes, cad_error}`. `error` means the scrape failed; `cad_error`
means no CAD file was downloaded. Closing Edge takes about 2 seconds, so with
`--result FILE` the same JSON is also written to FILE *before* that. A caller
can watch for the file instead of waiting for the process to exit (the NX tool
does this).

## How it works

0. Product pages require authentication. `login` opens a headful Edge against a
   persistent `--user-data-dir`; after you sign in, the session cookie lives in
   that profile and `scrape`/`cad` reuse it via the same profile dir.
1. `make_driver()` launches headless Edge with a desktop user-agent.
2. The page loads and the script **waits** for the JS-rendered product header
   before reading anything.
3. Data is extracted in a single in-browser `execute_script` call to avoid
   `StaleElementReferenceException` from the SPA's re-renders.
4. CSS selectors match on the **stable class-name prefix** (e.g.
   `[class*="_price_"]`) rather than the full class, because McMaster appends a
   per-build hash (`_price_1y02s_5`) that changes between deployments.

See [HANDOFF.md](HANDOFF.md) for implementation details and maintenance notes.

## Notes & limitations

- For personal/internal use. Be respectful of McMaster's servers — add delays
  if scraping many parts; there is no built-in rate limiting.
- The CSS-module hashes change on McMaster redeploys. The prefix selectors are
  designed to survive that, but if extraction returns `null`s, the class
  prefixes (or DOM structure) likely changed — see HANDOFF.md for how to
  re-discover them.
