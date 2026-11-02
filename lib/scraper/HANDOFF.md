# Handoff — McMaster-Carr Scraper

Implementation notes and maintenance guide for whoever picks this up next.

## TL;DR

- One file: [mcmaster_scraper.py](mcmaster_scraper.py), four subcommands
  (`login`, `scrape`, `cad`, and `fetch` = scrape + cad in one browser session).
  Pure Selenium + headless Edge. No server, no DB.
- **Login wall (added 2026-07-09):** McMaster now shows a "To continue
  browsing, please log in" interstitial for anonymous visitors — **intermittently**
  (seen on a fresh profile in one run, absent in the next), so it is not a hard
  gate on every request. When it appears, none of the product/CAD DOM renders.
  The browser runs against a persistent Edge profile (`--user-data-dir`, default
  `~/.mcmaster-scraper/edge-profile`).
- **Auto-login:** `scrape`/`cad` detect the wall (`login_wall_present`) and
  automatically call `interactive_login` — a **headful** window the user signs
  into — then retry. Edge locks the profile to one process, so the headless
  working driver is quit before the login window opens and re-created after.
  `--no-auto-login` disables this (report error instead of blocking) for CI.
  The `login` subcommand is just `interactive_login` on its own.
- McMaster pages are a JS SPA → **must** use a real browser. A raw HTTP GET
  returns the app shell with `<title>McMaster-Carr</title>` and none of the
  product data.
- Selectors key off **class-name prefixes**, not full classes, because
  McMaster CSS-module hashes change per deploy.

## Environment as built

- Windows 11, Microsoft Edge (Chromium) `149.x`.
- Real Python at
  `C:\Users\br435t\AppData\Local\Programs\Python\Python312\python.exe`
  (the bare `python` on PATH was the Windows Store stub — avoid it).
- Selenium `4.45.0`. Selenium Manager auto-fetched `msedgedriver` — no manual
  driver install was needed.
- No Node, no real Python on PATH at the start; Edge was the only
  Chromium-class browser present (no Chrome), which is why the driver is Edge.

## Architecture

`make_driver(headful)` → headless Edge, desktop UA, 60s page-load timeout.

### `scrape` command (`cmd_scrape` → `scrape_part`)
1. `driver.get(url)`, then `WebDriverWait` for `[class*="_productDetailHeaders_"]`
   (proves the SPA has rendered the product).
2. `read_product_data`: one `execute_script(EXTRACT_JS)` returns the whole
   structured object. Doing it in a single in-browser call avoids
   `StaleElementReferenceException` — the SPA mutates the DOM after first paint,
   so holding Python-side element handles across calls fails. It re-reads until
   two reads 0.3 s apart agree (at most 2 s), because the SPA re-renders the
   page ~0.3 s after first paint (the spec rows briefly empty out).

### `cad` command (`cmd_cad`)
1. `get_cad_options` — waits for the `_buttonDropdown_` combobox, then polls
   `CAD_MENU_JS` every 0.1 s, **re-querying and clicking the combobox inside JS**
   (not via a held handle — it goes stale) whenever its `[role="listbox"]` is
   closed: the ~0.3 s re-render closes a dropdown opened before it. Returns as
   soon as the wanted option is listed (`matching_option`), otherwise once the
   list is unchanged for 0.8 s (it can populate incrementally), and `[]` if
   the combobox stays `aria-disabled="true"` for 2 s (no CAD for the part).
2. Each `<li role="option">` carries the download path in its **`value`**
   attribute, e.g.
   `/mvC/Library/CAD2/<date>/<hash>/91274A004_NO THREADS_<name>.X_T`.
3. `choose_option` matches by format keyword + threads preference. The
   no-threads variant has `NO THREADS` in the path and "no threads" in the
   label.
4. `download_cad` URL-encodes the path and fetches it with
   `execute_async_script(FETCH_JS)` — an in-page `fetch(url,
   {credentials:'include'})` → `arrayBuffer` → base64 → returned to Python →
   `base64.b64decode` → written to disk. Using the page's own fetch means
   McMaster's session cookies and same-origin checks are satisfied
   automatically; a bare external GET may be rejected.

### `fetch` command (`cmd_fetch`)
`scrape_part`, then the `cad` steps on the page that is already loaded: one Edge
launch and one page load instead of two. Writes `<pn>.json`, downloads the CAD,
and reports both in one result JSON (stdout, and `--result FILE`). FILE is
written *before* `driver.quit()`, which takes ~2.4 s (Edge closing with the
persistent profile, plus Selenium's `Service.stop()` sleeping a full 1 s while
the driver port is still open). Exceptions go into the result's `error` /
`cad_error` (traceback to stderr) rather than ending the run without a result.
`lib/mcmaster.py` watches for FILE and does not wait for the process to exit.
On Windows Selenium starts `msedgedriver` with `close_fds=False`, so the driver
inherits the scraper's stdout handle: a caller that reads stdout to EOF (as
`subprocess.run` does) waits for Edge to close anyway. That is why the result
goes through a file and not stdout.

### Timing (measured 2026-11-01, warm profile)
Python + Selenium import + Selenium Manager ≈ 0.35 s; Edge launch ≈ 1.1 s;
`driver.get` → product header ≈ 0.8-1.3 s; header, specs, price and the CAD
combobox render together and the data is already final; the CAD options are
listed ~0.07 s after the click; download < 0.1 s; `driver.quit()` ≈ 2.4 s.
`fetch` hands back its result in ~3.5 s (about 15 s with the old `scrape` +
`cad` pair and their fixed sleeps).

## Key DOM facts (verified 2026-06-21, part 91274A004)

| Field | Selector (prefix match) | Element |
|-------|-------------------------|---------|
| Title wrapper | `[class*="_productDetailHeaders_"]` | `div` |
| Title primary | `[class*="_productDetailHeaderPrimary_"]` | `h1` |
| Title secondary | `[class*="_productDetailHeaderSecondary_"]` | `h3` |
| Part number | `[class*="_productDetailPartNumber_"]` | `div` (also a `…Print` variant) |
| Price | `[class*="_price_"]` | `div` (e.g. "$13.93 per pack of 25") |
| Delivery | `[class*="_productDetailDeliveryMessage_"]` | `span` |
| Spec rows | `[class*="_product-detail-spec-table-row"]` | `tr` |
| Spec label / value | `[class*="-spec-row-label"]` / `[class*="-spec-row-value"]` | `div` |
| CAD dropdown button | `[class*="_buttonDropdown_"]` | `button[role=combobox]` |
| CAD options | `[role="listbox"] li[role="option"]` | path in `value` attr |
| No CAD for the part | same combobox with `aria-disabled="true"`, text "Select a CAD file type" | e.g. `5887K51` (verified 2026-11-01) |

**Spec grouping quirk:** the spec table mixes heading rows, *indented* rows
that belong under a heading, and top-level rows. The indent is signalled by
`-row-indented` in the row's class. Logic: non-indented + empty value = heading
(becomes current group); indented row = belongs to current group; non-indented
+ value = top-level spec (group cleared to `null`). Getting this wrong
mis-files top-level specs like "Material" under the previous heading.

**CAD formats seen in the dropdown:** 3-D Solidworks (.SLDPRT), 3-D STEP, 3-D
STEP no threads, 3-D Parasolid (.X_T), 3-D Parasolid no threads, 3-D SAT, 3-D
IGES, 3-D PDF; plus 2-D PDF/DWG/DXF/Solidworks/EDRW. Not every part offers a
"no threads" variant — `choose_option` falls back to the plain format if the
requested variant is absent.

## When it breaks: re-discovering selectors

Symptom: `scrape` returns mostly `null`s, or `cad --list` is empty → McMaster
changed the DOM or the class-prefix scheme.

Quick re-discovery (these were the throwaway explore scripts, now deleted —
recreate ad hoc):
```python
# dump class-name prefixes by frequency
driver.execute_script("""
  const f={}; document.querySelectorAll('[class]').forEach(e=>
    (e.className.split?e.className.split(/\\s+/):[]).forEach(c=>{
      const m=c.match(/^(_[A-Za-z-]+)_/); if(m) f[m[1]]=(f[m[1]]||0)+1;}));
  return f;
""")
```
Then update the prefix strings in `EXTRACT_JS` / the CAD selectors. Run
`--headful` to watch the page if a wait is timing out.

## Possible next steps (not done)

- `.gitignore` for `cad/` and output `*.json` (test artifacts left in tree:
  `product.json`, `cad/`).
- Rate limiting / polite delay + retry for large batch scrapes.
- Extra fields: product images, CAD thumbnail, price-break/quantity tiers.
- Cross-platform: swap Edge for Chrome via a `--browser` flag if run off
  Windows.
- Tests: the JS extractors are the fragile part; a saved-HTML fixture + jsdom
  or a recorded-session test would catch selector drift.
