"""McMaster-Carr scraper.

Product pages are rendered client-side (the data is JS-injected and is NOT in
the raw HTML), so everything here drives a headless Edge browser via Selenium.

McMaster now gates product pages behind a LOGIN WALL ("To continue browsing,
please log in"). The browser therefore runs against a persistent Edge profile
(`--user-data-dir`): you authenticate once with the `login` subcommand and the
session cookie is reused by later `scrape`/`cad` runs.

Selectors match on the STABLE class-name PREFIX (e.g. `_price_`) because
McMaster appends a per-build CSS-module hash (`_price_1y02s_5`) that changes
between site deployments.

Subcommands:
    login    Open a browser to log in once; the session persists on disk.
    scrape   Extract structured product fields as JSON.
    cad      Download a CAD model (default: 3-D Parasolid, no threads).
    fetch    scrape + cad for one part in a single browser session.

Usage:
    python mcmaster_scraper.py login [--profile DIR]
    python mcmaster_scraper.py scrape 91274A004 [MORE ...] [--out file.json] [--headful]
    python mcmaster_scraper.py cad 91274A004 [--out DIR] [--format parasolid] [--threads]
    python mcmaster_scraper.py cad 91274A004 --list
    python mcmaster_scraper.py fetch 91274A004 [--out DIR] [--result FILE]
"""
import argparse
import base64
import json
import os
import sys
import time
import traceback
import urllib.parse

from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

BASE = "https://www.mcmaster.com"
URL = BASE + "/{part}/"

# A known-good part used to probe whether the session is authenticated.
PROBE_PART = "91274A004"

# Persistent Edge profile so the login session survives between runs.
DEFAULT_PROFILE = os.path.join(
    os.path.expanduser("~"), ".mcmaster-scraper", "edge-profile"
)


def _edge_version():
    """Best-effort installed Edge version, e.g. "150.0.4078.65", or None.

    Tries the registry (BLBeacon), then the Edge install folder.
    """
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(
                        hive, r"Software\Microsoft\Edge\BLBeacon") as key:
                    version, _ = winreg.QueryValueEx(key, "version")
                    if version:
                        return version
            except OSError:
                continue
    except ImportError:
        pass
    for base in (os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.environ.get("ProgramFiles", r"C:\Program Files")):
        app = os.path.join(base, "Microsoft", "Edge", "Application")
        try:
            versions = [d for d in os.listdir(app)
                        if d[:1].isdigit() and "." in d]
        except OSError:
            continue
        if versions:
            return sorted(versions, key=lambda v: [int(p) for p in v.split(".")
                          if p.isdigit()])[-1]
    return None


def edge_user_agent():
    """Genuine current Microsoft Edge desktop UA, or None if undetectable.

    Corporate browser-control policies block unapproved/outdated browsers by
    inspecting the UA, so we advertise the REAL installed Edge rather than a
    spoofed (and quickly stale) Chrome string. If the version can't be found we
    return None and the caller leaves Edge's own default UA in place.
    """
    version = _edge_version()
    if not version:
        return None
    major = version.split(".", 1)[0]
    return ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/{0}.0.0.0 Safari/537.36 Edg/{0}.0.0.0".format(major))


def make_driver(headful=False, profile_dir=DEFAULT_PROFILE):
    opts = Options()
    if not headful:
        opts.add_argument("--headless=new")
    if profile_dir:
        os.makedirs(profile_dir, exist_ok=True)
        opts.add_argument(f"--user-data-dir={os.path.abspath(profile_dir)}")
    opts.add_argument("--window-size=1280,2200")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--log-level=3")
    # Advertise the real, current Edge (not a spoofed Chrome UA) so corporate
    # browser-control policies don't block us. Falls back to Edge's own default
    # UA if the version can't be detected.
    user_agent = edge_user_agent()
    if user_agent:
        opts.add_argument("user-agent=" + user_agent)
    driver = webdriver.Edge(options=opts)
    driver.set_page_load_timeout(60)
    return driver


def is_logged_in(driver):
    """True if the current page shows product content, not the login wall."""
    return bool(driver.execute_script(
        "return !!document.querySelector('[class*=\"_productDetailHeaders_\"]');"
    ))


def login_wall_present(driver):
    """True if McMaster's 'please log in' interstitial is on the page."""
    return bool(driver.execute_script(
        "return /to continue browsing, please log in/i"
        ".test(document.body ? document.body.innerText : '');"
    ))


def interactive_login(profile_dir, timeout=300):
    """Open a headful window and wait for the user to log in.

    Runs its own browser (McMaster locks the Edge profile to one process, so
    any headless working driver must be closed before calling this). Returns
    True once a product page renders, False on timeout.
    """
    driver = make_driver(headful=True, profile_dir=profile_dir)
    try:
        driver.get(URL.format(part=PROBE_PART))
        if is_logged_in(driver):
            return True
        print("Not logged in — opening a browser window to log in.",
              file=sys.stderr)
        print(f"Sign in to McMaster-Carr in that window (waiting up to "
              f"{timeout // 60} min); Ctrl-C to cancel.", file=sys.stderr)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if is_logged_in(driver):
                print(f"[ok] Login detected and saved to profile: "
                      f"{os.path.abspath(profile_dir)}", file=sys.stderr)
                return True
            time.sleep(2)
        print("ERROR: timed out waiting for login.", file=sys.stderr)
        return False
    finally:
        driver.quit()


# --------------------------------------------------------------------------- #
# scrape
# --------------------------------------------------------------------------- #

# JS run inside the page; returns a structured dict for the rendered product.
EXTRACT_JS = r"""
const txt = el => el ? el.textContent.replace(/\s+/g, ' ').trim() : null;
const pick = sel => document.querySelector(sel);

const primary   = pick('[class*="_productDetailHeaderPrimary_"]');
const secondary = pick('[class*="_productDetailHeaderSecondary_"]');
const headers   = pick('[class*="_productDetailHeaders_"]');
const partNo    = pick('[class*="_productDetailPartNumber_"]:not([class*="Print"])')
                  || pick('[class*="_productDetailPartNumber_"]');
const price     = pick('[class*="_price_"]');
const delivery  = pick('[class*="_productDetailDeliveryMessage_"]');

// Specifications: rows carry a label div and (optionally) a value div.
// McMaster nests INDENTED rows under a heading row, but leaves many specs at
// top level. Use the row's indent class to assign groups correctly:
//   - non-indented + no value  => group heading (set context)
//   - indented                 => belongs to the current heading
//   - non-indented + value     => top-level spec (clear context)
const specs = [];
let group = null;
document.querySelectorAll('[class*="_product-detail-spec-table-row"]').forEach(row => {
  const indented = /-row-indented/.test(row.className);
  const labelEl = row.querySelector('[class*="-spec-row-label"]');
  const valueEl = row.querySelector('[class*="-spec-row-value"]');
  const label = txt(labelEl);
  const value = txt(valueEl);
  if (!label) return;
  if (!indented && !value) { group = label; return; }  // heading row
  if (!indented) group = null;                          // top-level spec
  specs.push({ group: indented ? group : null, label, value });
});

return {
  title: txt(headers),
  title_primary: txt(primary),
  title_secondary: txt(secondary),
  part_number: txt(partNo),
  price: txt(price),
  delivery: txt(delivery),
  page_title: document.title,
  specs,
  title_html_block: headers ? headers.outerHTML : null,
};
"""


def read_product_data(driver, settle=0.3, cap=2.0):
    """Run EXTRACT_JS until two reads `settle` s apart agree; return that read.

    The header, specs and price render together, but the SPA re-renders the
    page about 0.3 s later (the spec rows briefly empty out), so a single read
    can land mid-re-render. Gives up after `cap` s (the fixed wait this
    replaced) and returns the last read.
    """
    deadline = time.time() + cap
    data = driver.execute_script(EXTRACT_JS)
    while time.time() < deadline:
        time.sleep(settle)
        again = driver.execute_script(EXTRACT_JS)
        if again == data and again.get("specs"):
            return again
        data = again
    return data


def scrape_part(driver, part):
    url = URL.format(part=part)
    driver.get(url)
    try:
        WebDriverWait(driver, 40).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, '[class*="_productDetailHeaders_"]')
            )
        )
    except TimeoutException:
        if login_wall_present(driver):
            return {
                "part_number": part,
                "url": url,
                "error": "not logged in — run: python mcmaster_scraper.py login",
            }
        return {
            "part_number": part,
            "url": url,
            "error": "product header did not render (invalid part #, "
                     "bot-blocked, or layout changed)",
        }
    data = read_product_data(driver)
    data["part_number"] = data.get("part_number") or part
    data["url"] = url
    return data


# --------------------------------------------------------------------------- #
# login
# --------------------------------------------------------------------------- #

def cmd_login(args):
    return 0 if interactive_login(args.profile) else 2


def _needs_login(data):
    err = data.get("error")
    return isinstance(err, str) and err.startswith("not logged in")


def cmd_scrape(args):
    driver = make_driver(headful=args.headful, profile_dir=args.profile)
    results = []
    tried_login = False
    try:
        for part in args.parts:
            print(f"[scraping] {part} ...", file=sys.stderr)
            data = scrape_part(driver, part)
            # If the session is missing, log in once (headful) and retry.
            if _needs_login(data) and not args.no_auto_login and not tried_login:
                tried_login = True
                driver.quit()  # release the profile lock for the login window
                ok = interactive_login(args.profile)
                driver = make_driver(headful=args.headful, profile_dir=args.profile)
                if ok:
                    data = scrape_part(driver, part)
            results.append((part, data))
    finally:
        driver.quit()

    if args.stdout:
        out = [d for _, d in results]
        out = out if len(out) > 1 else out[0]
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    # Default: write each part to <out_dir>/<part_number>.json
    os.makedirs(args.out, exist_ok=True)
    for part, data in results:
        dest = os.path.join(args.out, f"{part}.json")
        with open(dest, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"[wrote] {dest}", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- #
# cad
# --------------------------------------------------------------------------- #

# format keyword -> label substring McMaster uses in the dropdown
FORMAT_LABEL = {
    "parasolid": "Parasolid",
    "step": "STEP",
    "iges": "IGES",
    "sat": "SAT",
    "solidworks": "Solidworks",
    "pdf": "PDF",
}

# CAD dropdown state: disabled (McMaster greys it out when the part has no
# CAD), whether its listbox is open, and the options listed so far.
CAD_MENU_JS = """
const btn = document.querySelector('[class*="_buttonDropdown_"]');
const lb = document.querySelector('[role="listbox"]');
const options = lb ? [...lb.querySelectorAll('li[role="option"]')].map(li => ({
  label: li.textContent.trim(),
  path: li.getAttribute('value')
})).filter(o => o.path) : [];
return {
  disabled: !!btn && btn.getAttribute('aria-disabled') === 'true',
  open: !!lb,
  options,
};
"""

CLICK_CAD_MENU_JS = "document.querySelector('[class*=\"_buttonDropdown_\"]').click();"

# Fetch a same-origin URL inside the page and hand the bytes back as base64.
FETCH_JS = r"""
const url = arguments[0];
const done = arguments[arguments.length - 1];
fetch(url, { credentials: 'include' })
  .then(r => r.ok ? r.arrayBuffer().then(b => ({status: r.status, buf: b}))
                  : ({status: r.status, buf: null}))
  .then(({status, buf}) => {
    if (!buf) { done({ok: false, status}); return; }
    let bin = '';
    const bytes = new Uint8Array(buf);
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    done({ok: true, status, b64: btoa(bin), size: bytes.length});
  })
  .catch(e => done({ok: false, error: String(e)}));
"""


def get_cad_options(driver, fmt=None, want_threads=False):
    """Open the dropdown and return [{label, path}] for every CAD file.

    The SPA re-renders the page right after it first appears, which can close
    the dropdown again, so it is re-clicked whenever it is shut. With `fmt`,
    returns as soon as the option matching_option() wants is listed.
    Otherwise the list is only returned once it is STABLE (unchanged for
    0.8 s): it populates incrementally, and a partial list can miss the
    "no threads" variants, which makes choose_option fall back to the plain
    (threaded) file -> wrong CAD. Returns [] if the dropdown stays disabled
    (McMaster has no CAD for the part).
    """
    WebDriverWait(driver, 40).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, '[class*="_buttonDropdown_"]'))
    )
    deadline = time.time() + 15
    clicked = disabled_since = listed_since = None
    labels = None
    options = []
    while time.time() < deadline:
        menu = driver.execute_script(CAD_MENU_JS)
        now = time.time()
        if menu["disabled"]:
            # Give a slow render a moment to enable it before giving up.
            if disabled_since is None:
                disabled_since = now
            if now - disabled_since >= 2:
                return []
        else:
            disabled_since = None
            if not menu["open"] and (clicked is None or now - clicked >= 0.5):
                # Re-query and click inside JS to avoid stale element references.
                driver.execute_script(CLICK_CAD_MENU_JS)
                clicked = now
        if menu["options"]:
            options = menu["options"]
            if fmt and matching_option(options, fmt, want_threads):
                return options
            if [o["label"] for o in options] != labels:
                labels = [o["label"] for o in options]
                listed_since = now
            elif now - listed_since >= 0.8:
                return options
        time.sleep(0.1)
    return options


def matching_option(options, fmt, want_threads):
    """The `fmt` option in exactly the requested threads variant, or None."""
    label_kw = FORMAT_LABEL[fmt]
    for o in options:
        text = o["label"]
        if "3-D " + label_kw not in text and label_kw not in text:
            continue
        has_no_threads = "no threads" in text.lower()
        if want_threads and not has_no_threads:
            return o
        if not want_threads and has_no_threads:
            return o
    return None


def choose_option(options, fmt, want_threads):
    chosen = matching_option(options, fmt, want_threads)
    if chosen:
        return chosen
    # Fallback: format requested has no separate threads variant (e.g. PDF).
    label_kw = FORMAT_LABEL[fmt]
    for o in options:
        if label_kw in o["label"]:
            return o
    return None


def download_cad(driver, path, out_dir):
    abs_url = BASE + urllib.parse.quote(path, safe="/")
    result = driver.execute_async_script(FETCH_JS, abs_url)
    if not result or not result.get("ok"):
        raise RuntimeError(f"download failed: {result}")
    data = base64.b64decode(result["b64"])
    fname = os.path.basename(urllib.parse.unquote(path))
    os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(out_dir, fname)
    with open(dest, "wb") as f:
        f.write(data)
    return dest, len(data)


def _cad_error(args, message):
    """Emit a CAD error as JSON or plain text and return exit code 2."""
    if getattr(args, "json", False):
        print(json.dumps({"part_number": args.part, "error": message},
                         indent=2, ensure_ascii=False))
    else:
        print(f"ERROR: {message}.", file=sys.stderr)
    return 2


def _load_cad_options(driver, part, fmt=None, want_threads=False):
    """Navigate to the part page and return CAD options, or None on timeout."""
    driver.get(URL.format(part=part))
    try:
        return get_cad_options(driver, fmt, want_threads)
    except TimeoutException:
        return None


def cmd_cad(args):
    # --list wants every option, so only stop at the wanted one for a download.
    fmt = None if args.list else args.format
    driver = make_driver(profile_dir=args.profile)
    try:
        options = _load_cad_options(driver, args.part, fmt, args.threads)
        # Missing session → log in once (headful) and retry.
        if (options is None and login_wall_present(driver)
                and not args.no_auto_login):
            driver.quit()
            driver = None  # profile lock released for the login window
            if not interactive_login(args.profile):
                return _cad_error(args, "login not completed — run: "
                                  "python mcmaster_scraper.py login")
            driver = make_driver(profile_dir=args.profile)
            options = _load_cad_options(driver, args.part, fmt, args.threads)

        if options is None:
            if driver is not None and login_wall_present(driver):
                return _cad_error(args, "not logged in — run: "
                                  "python mcmaster_scraper.py login")
            return _cad_error(args, "CAD control did not render (invalid part #, "
                              "blocked, or no CAD available for this part)")

        if not options:
            return _cad_error(args, "no CAD options found")

        if args.list:
            if args.json:
                print(json.dumps(
                    {"part_number": args.part, "options": options},
                    indent=2, ensure_ascii=False))
            else:
                for o in options:
                    print(f"  {o['label']:<28} {o['path']}")
            return 0

        chosen = choose_option(options, args.format, args.threads)
        if not chosen:
            variant = "with threads" if args.threads else "no threads"
            if args.json:
                print(json.dumps({
                    "part_number": args.part,
                    "error": f"no '{args.format}' ({variant}) option for this part",
                    "options": options,
                }, indent=2, ensure_ascii=False))
            else:
                print(f"ERROR: no '{args.format}' ({variant}) option for this part. "
                      f"Use --list to see what's available.", file=sys.stderr)
            return 2

        print(f"[selected] {chosen['label']}", file=sys.stderr)
        dest, size = download_cad(driver, chosen["path"], args.out)
        if args.json:
            print(json.dumps({
                "part_number": args.part,
                "label": chosen["label"],
                "path": chosen["path"],
                "file": dest,
                "bytes": size,
            }, indent=2, ensure_ascii=False))
        else:
            print(f"[downloaded] {dest}  ({size:,} bytes)")
        return 0
    finally:
        if driver is not None:
            driver.quit()


# --------------------------------------------------------------------------- #
# fetch
# --------------------------------------------------------------------------- #

def write_json(dest, obj):
    """Write obj to dest as JSON, atomically (no reader sees half a file)."""
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, indent=2, ensure_ascii=False))
    os.replace(tmp, dest)


def _fetch_cad(driver, args, result):
    """Download the CAD from the part page `driver` is on; fill in `result`."""
    try:
        options = get_cad_options(driver, args.format, args.threads)
    except TimeoutException:
        result["cad_error"] = ("CAD control did not render (invalid part #, "
                               "blocked, or no CAD available for this part)")
        return
    if not options:
        result["cad_error"] = "no CAD options found"
        return
    chosen = choose_option(options, args.format, args.threads)
    if not chosen:
        variant = "with threads" if args.threads else "no threads"
        result["cad_error"] = f"no '{args.format}' ({variant}) option for this part"
        return
    print(f"[selected] {chosen['label']}", file=sys.stderr)
    dest, size = download_cad(driver, chosen["path"], args.out)
    result.update(label=chosen["label"], path=chosen["path"], file=dest, bytes=size)


def cmd_fetch(args):
    """`scrape` + `cad --json` for one part, in ONE browser session.

    Edge starts and loads the page once instead of twice. Writes
    <out>/<part>.json like `scrape`, downloads the CAD into <out> like `cad`,
    and prints one JSON result: {part_number, json_file, error, label, path,
    file, bytes, cad_error}. `error` = the scrape failed; `cad_error` = no CAD
    was downloaded. With --result FILE the result is also written to FILE
    BEFORE Edge is closed (closing it takes ~2 s), so a caller can watch for
    the file instead of waiting for this process to exit.
    """
    result = {"part_number": args.part, "json_file": None, "error": None,
              "label": None, "path": None, "file": None, "bytes": None,
              "cad_error": None}
    driver = None
    try:
        driver = make_driver(profile_dir=args.profile)
        print(f"[scraping] {args.part} ...", file=sys.stderr)
        data = scrape_part(driver, args.part)
        # Missing session -> log in once (headful) and retry.
        if _needs_login(data) and not args.no_auto_login:
            driver.quit()
            driver = None  # profile lock released for the login window
            if interactive_login(args.profile):
                driver = make_driver(profile_dir=args.profile)
                data = scrape_part(driver, args.part)
        os.makedirs(args.out, exist_ok=True)
        json_file = os.path.join(args.out, f"{args.part}.json")
        write_json(json_file, data)
        result["json_file"] = json_file
        print(f"[wrote] {json_file}", file=sys.stderr)
        if data.get("error"):
            result["error"] = data["error"]
        else:
            _fetch_cad(driver, args, result)
    except Exception as ex:  # report it in the result, not just a traceback
        traceback.print_exc()
        message = (str(ex).strip().splitlines() or [type(ex).__name__])[0]
        if result["json_file"] and not result["error"]:
            result["cad_error"] = message
        else:
            result["error"] = message
    finally:
        try:
            if args.result:
                write_json(args.result, result)
            print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
        finally:
            if driver is not None:
                driver.quit()
    return 2 if result["error"] or result["cad_error"] else 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser():
    ap = argparse.ArgumentParser(description="Scrape McMaster-Carr product pages.")
    sub = ap.add_subparsers(dest="command", required=True)

    l = sub.add_parser("login", help="log in once; the session persists on disk")
    l.add_argument("--profile", default=DEFAULT_PROFILE,
                   help=f"Edge profile dir (default: {DEFAULT_PROFILE})")
    l.set_defaults(func=cmd_login)

    s = sub.add_parser("scrape", help="extract structured product fields as JSON")
    s.add_argument("parts", nargs="+", help="part number(s), e.g. 91274A004")
    s.add_argument("--out", default=".",
                   help="directory for the <part>.json files (default: current)")
    s.add_argument("--stdout", action="store_true",
                   help="print JSON to stdout instead of writing <part>.json files")
    s.add_argument("--headful", action="store_true", help="show the browser window")
    s.add_argument("--no-auto-login", action="store_true",
                   help="don't open a login window if the session is missing; "
                        "just report the error")
    s.add_argument("--profile", default=DEFAULT_PROFILE,
                   help=f"Edge profile dir (default: {DEFAULT_PROFILE})")
    s.set_defaults(func=cmd_scrape)

    c = sub.add_parser("cad", help="download a CAD model (default: Parasolid, no threads)")
    c.add_argument("part", help="part number, e.g. 91274A004")
    c.add_argument("--out", default=".", help="output directory (default: current)")
    c.add_argument("--profile", default=DEFAULT_PROFILE,
                   help=f"Edge profile dir (default: {DEFAULT_PROFILE})")
    c.add_argument("--format", default="parasolid", choices=sorted(FORMAT_LABEL),
                   help="CAD format (default: parasolid)")
    c.add_argument("--threads", action="store_true",
                   help="get the WITH-threads variant (default: no threads)")
    c.add_argument("--list", action="store_true",
                   help="just list available CAD options and exit")
    c.add_argument("--json", action="store_true",
                   help="emit results as JSON (list, download result, or error)")
    c.add_argument("--no-auto-login", action="store_true",
                   help="don't open a login window if the session is missing; "
                        "just report the error")
    c.set_defaults(func=cmd_cad)

    f = sub.add_parser("fetch",
                       help="scrape + download the CAD for one part in one browser session")
    f.add_argument("part", help="part number, e.g. 91274A004")
    f.add_argument("--out", default=".",
                   help="directory for <part>.json and the CAD file (default: current)")
    f.add_argument("--result", metavar="FILE",
                   help="also write the result JSON to FILE, before Edge is closed")
    f.add_argument("--profile", default=DEFAULT_PROFILE,
                   help=f"Edge profile dir (default: {DEFAULT_PROFILE})")
    f.add_argument("--format", default="parasolid", choices=sorted(FORMAT_LABEL),
                   help="CAD format (default: parasolid)")
    f.add_argument("--threads", action="store_true",
                   help="get the WITH-threads variant (default: no threads)")
    f.add_argument("--no-auto-login", action="store_true",
                   help="don't open a login window if the session is missing; "
                        "just report the error")
    f.set_defaults(func=cmd_fetch)

    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
