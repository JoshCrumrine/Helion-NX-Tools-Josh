"""McMaster-Carr data: run the vendored scraper and massage its output."""
import json
import os
import subprocess
import time

from lib.paths import ROOT

# Vendored McMaster scraper (under lib/scraper) + output dir.
SCRAPER_SCRIPT = os.path.join(ROOT, "lib", "scraper", "mcmaster_scraper.py")
MCMASTER_OUT = r"C:\TEMP\MCMASTER"

# Seconds to wait for the scraper: room for a McMaster sign-in (its login
# window waits up to 5 minutes) plus the scrape and download themselves.
FETCH_TIMEOUT = 420


def scraper_python():
    """External Python that has selenium installed (see lib/scraper/VENDORED.md).

    Preference order (so it works even when NX didn't inherit the env var):
      1. MCMASTER_SCRAPER_PYTHON environment variable
      2. the repo-root venv (<root>\\.venv\\Scripts\\python.exe)
      3. "python" on PATH

    The env var is skipped when it points at a full path that no longer
    exists (e.g. a stale value left over from a moved repo) so we fall through
    to the repo-root .venv instead of hard-aborting. A bare command name
    (no directory component, e.g. just "python") is trusted as-is since it is
    resolved on PATH, not on disk.
    """
    env = os.environ.get("MCMASTER_SCRAPER_PYTHON")
    if env:
        has_dir = bool(os.path.dirname(env))
        if not has_dir or os.path.exists(env):
            return env
        # else: stale/broken path -> ignore and fall through
    venv_py = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    if os.path.exists(venv_py):
        return venv_py
    return "python"


def start_fetch(part_no, out_dir=MCMASTER_OUT, log=None):
    """Start fetching `part_no` in the background; finish with wait_for_fetch().

    Runs the vendored scraper's `fetch` command in an external interpreter as a
    subprocess: one Edge session that writes <dir>/<pn>.json and downloads the
    default 3-D Parasolid, no-threads *.X_T into <dir>. It writes its result to
    <dir>/<pn>.result.json before closing Edge, and its output to <dir>/<pn>.log.
    NX is not blocked while it runs, so the caller can show a dialog meanwhile.
    Returns the job for wait_for_fetch(). Never raises.
    """
    _log = log or (lambda m: None)
    job = {"proc": None, "error": None, "started": time.time(),
           "result_file": os.path.join(out_dir, part_no + ".result.json"),
           "log_file": os.path.join(out_dir, part_no + ".log")}
    _log("  running lib/scraper/mcmaster_scraper.py ({0})".format(scraper_python()))
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as ex:
        job["error"] = "cannot create {0}: {1}".format(out_dir, ex)
        return job

    _log("  > fetch {0} --out {1}  (scrape + no-threads Parasolid, one Edge "
         "session)".format(part_no, out_dir))
    try:
        if os.path.exists(job["result_file"]):
            os.remove(job["result_file"])  # stale, from an earlier run
        with open(job["log_file"], "w", encoding="utf-8") as log_handle:
            job["proc"] = subprocess.Popen(
                [scraper_python(), SCRAPER_SCRIPT, "fetch", part_no,
                 "--out", out_dir, "--result", job["result_file"]],
                stdin=subprocess.DEVNULL, stdout=log_handle,
                stderr=subprocess.STDOUT,
                env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as ex:
        job["error"] = "failed to run scraper: {0}".format(ex)
    return job


def wait_for_fetch(job, log=None, timeout=FETCH_TIMEOUT):
    """Wait for a start_fetch() job and return what it fetched.

    Returns as soon as the scraper's result file appears, without waiting the
    ~2 s Edge takes to close afterwards. Returns a dict:
      {"data": <scraped dict or None>, "json_file": path or None,
       "cad_file": path or None, "error": <scrape error or None>,
       "cad_error": <CAD error or None>}
    `error` means the JSON (and thus the description) is unavailable;
    `cad_error` means no CAD model was downloaded. Both abort creation in
    main() — see step 2b. Never raises.
    """
    result = {"data": None, "json_file": None, "cad_file": None,
              "error": None, "cad_error": None}  # type: dict
    _log = log or (lambda m: None)
    if job["error"]:
        result["error"] = job["error"]
        return result

    proc, result_file = job["proc"], job["result_file"]
    while not os.path.exists(result_file):
        if proc.poll() is not None:
            if os.path.exists(result_file):
                break  # written just before it exited
            result["error"] = "scraper exited {0}: {1} (log: {2})".format(
                proc.returncode, _last_log_line(job["log_file"]), job["log_file"])
            return result
        if time.time() - job["started"] > timeout:
            proc.kill()
            result["error"] = "scraper timed out after {0} s (log: {1})".format(
                timeout, job["log_file"])
            return result
        time.sleep(0.1)
    _log("  scraper done in {0:.1f} s".format(time.time() - job["started"]))

    try:
        with open(result_file, encoding="utf-8") as handle:
            fetched = json.load(handle)
    except (OSError, ValueError) as ex:
        result["error"] = "cannot read scraper result: {0}".format(ex)
        return result

    json_file = fetched.get("json_file")
    if json_file:
        try:
            with open(json_file, encoding="utf-8") as handle:
                result["data"] = json.load(handle)
        except (OSError, ValueError) as ex:
            result["error"] = "cannot read scraped JSON: {0}".format(ex)
            return result
        result["json_file"] = json_file
    if fetched.get("error"):
        result["error"] = "scrape error: {0}".format(fetched["error"])
        return result
    if result["data"] is None:
        result["error"] = "scrape produced no JSON"
        return result

    result["cad_file"] = fetched.get("file")
    result["cad_error"] = fetched.get("cad_error")
    if not result["cad_file"] and not result["cad_error"]:
        result["cad_error"] = "CAD download reported no file"
    return result


def fetch_mcmaster(part_no, out_dir=MCMASTER_OUT, log=None):
    """Scrape property data (JSON) and download the no-threads Parasolid CAD.

    start_fetch() + wait_for_fetch() in one call; returns wait_for_fetch()'s
    dict. Never raises.
    """
    return wait_for_fetch(start_fetch(part_no, out_dir, log), log)


def _last_log_line(log_file):
    """Last non-empty line of the scraper's log (e.g. a traceback's error)."""
    try:
        with open(log_file, encoding="utf-8", errors="replace") as handle:
            lines = [line.strip() for line in handle if line.strip()]
    except OSError:
        return "(no log)"
    return lines[-1] if lines else "(empty log)"


def build_description(data):
    """part_desc = title_primary + title_secondary, concatenated and UPPERCASED."""
    primary = (data.get("title_primary") or "").strip()
    secondary = (data.get("title_secondary") or "").strip()
    return " ".join(p for p in (primary, secondary) if p).upper()


def make_filename_safe(name):
    """Sanitize a part name so NX can derive a valid part filename from it.

    In Teamcenter managed mode NX derives the new part's filename from the part
    name, and Windows filenames cannot contain  < > : " / \\ | ? *  -- but
    McMaster titles routinely use / and " (e.g. '1/4"-20'). Applied to the part
    NAME only ('"' -> 'IN', '/' -> '-') as a precaution; the full, unmodified
    text is not preserved on the part (DB_PART_DESC is no longer set).

    Note: the "The new filename is not a valid file specification" error chased
    during development turned out to be a duplicate item-id collision (operation
    failure 940519), not illegal characters -- see find_item_revision_spec().
    """
    name = name.replace('"', 'IN').replace('/', '-').replace('\\', '-')
    for bad in '<>:|?*':
        name = name.replace(bad, '')
    return " ".join(name.split())  # collapse whitespace, trim ends
