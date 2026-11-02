# Vendored code

The files in this folder are a vendored copy of the **McMaster-Carr scraper**.

- **Source:** https://github.com/br435t/McMaster-scraper
- **Commit:** `442c62dd4b4db271f5db2bc811048cafaa27490e`
- **Vendored on:** 2026-07-14

Only the functional files were copied (`mcmaster_scraper.py`, `requirements.txt`)
plus its docs (`README.md`, `HANDOFF.md`). The `examples/` folder (including a
large binary `.X_T` CAD sample) was not vendored.

`lib/mcmaster.py` runs `mcmaster_scraper.py fetch` as a **subprocess** using an
external Python interpreter that has Selenium installed (see `start_fetch()` in
that module). It is not imported into NX's embedded interpreter.

## Local modifications (diverged from upstream)

- **`make_driver()` user-agent** (2026-07-14): upstream hard-codes a spoofed
  `Chrome/126.0` UA, which trips corporate browser-control policies that block
  unapproved/outdated browsers. Replaced with `edge_user_agent()` /
  `_edge_version()`, which detect the installed Edge version at runtime and
  advertise the genuine current Edge (falls back to Edge's default UA if
  detection fails). Worth upstreaming to the source repo.

- **`get_cad_options()` stability wait** (2026-07-14): upstream returns on the
  first non-empty read of the CAD dropdown, which can be a partially rendered
  list missing the "no threads" variants — causing `choose_option` to fall back
  to the plain (threaded) file (wrong CAD). Now polls until the option count is
  stable across consecutive reads before returning. Worth upstreaming.

- **Waits driven by the page, not fixed sleeps** (2026-11-01): `scrape_part`
  no longer sleeps 2 s after the header appears; `read_product_data` re-reads
  until two reads 0.3 s apart agree (at most 2 s). `get_cad_options` no longer
  sleeps 1.5 s before clicking the CAD dropdown; it re-clicks whenever the
  page's re-render (~0.3 s after first paint) closes it, returns as soon as the
  wanted option is listed (`matching_option`, split out of `choose_option`), and
  returns `[]` after 2 s if the dropdown is `aria-disabled` (no CAD for the
  part) instead of polling 15 s. The stable-list wait above still applies when
  the wanted option is not listed. Worth upstreaming.

- **`fetch` subcommand** (2026-11-01): `scrape` + `cad --json` for one part in
  one browser session (Edge starts and loads the page once, not twice). With
  `--result FILE` it writes its result JSON to FILE *before* closing Edge
  (~2 s), so `lib/mcmaster.py` carries on without waiting for the browser to
  exit. Together with the waits above, the NX tool's scrape + CAD went from
  ~15 s to ~3.5 s. Worth upstreaming.

To update this copy, re-pull from the source repo, re-apply the local
modifications above, and refresh the commit hash.
