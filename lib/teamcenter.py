"""Teamcenter / NX Open helpers: existence check (and rule probe), PDM error dump, import."""
import NXOpen
import NXOpen.PDM

# Teamcenter destination folder for created COTS parts. The ":" prefix is TC
# folder syntax; using the real ":MCMASTER" folder (per the working recording
# journal_create_vendor_part.py) is what lets the manual-id Commit() succeed.
MCMASTER_TC_FOLDER = ":MCMASTER"

# Revision rules used to resolve an item id when checking for existence.
# An empty rule does NOT resolve existing parts here (verified via
# probe_revision_rules / Check-Part-Exists); "Latest Working" catches unreleased parts and
# "Any Status; Working" catches any status. If any rule resolves the id, the
# part exists. Extend this list if a part is known to exist but isn't detected.
_TC_EXISTENCE_REVISION_RULES = ("Latest Working", "Any Status; Working")


def import_parasolid(the_session, input_file, curves=True, surfaces=True, solids=True):
    """Import a Parasolid (*.x_t) file into the current work part.

    Mirrors the recorded File > Import > Parasolid flow (see import_Parasolid.py).
    """
    importer = the_session.DexManager.CreateParasolidImporter()
    try:
        importer.ObjectTypes.Curves = curves
        importer.ObjectTypes.Surfaces = surfaces
        importer.ObjectTypes.Solids = solids
        importer.SetMode(NXOpen.BaseImporter.Mode.NativeFileSystem)
        importer.InputFile = input_file
        importer.Commit()
    finally:
        importer.Destroy()


def find_item_revision_spec(the_session, item_id, log=None):
    """Return the Teamcenter spec of an existing item's revision, or None.

    Uses PdmSession.GetConfiguredRevisionOfItems across a few revision rules
    (see _TC_EXISTENCE_REVISION_RULES) and returns the first
    ItemRevisionCliSpec that resolves (a string openable with
    Parts.OpenActiveDisplay). None means the id was not found under any rule,
    or an API error occurred -- so creation proceeds; a genuine duplicate that
    slips through is then caught at Commit() (operation-failure code 940519)
    and reported via dump_pdm_errors(). Never raises.
    """
    _log = log or (lambda m: None)
    try:
        pdm = the_session.PdmSession
        for rule in _TC_EXISTENCE_REVISION_RULES:
            query = NXOpen.PDM.PdmSession.GetConfiguredRevisionInput()
            query.ItemId = item_id
            query.RevisionRuleName = rule
            _errors, results = pdm.GetConfiguredRevisionOfItems([query])
            for res in (results or []):
                spec = (res.ItemRevisionCliSpec or "").strip()
                if not res.HasFailed and spec:
                    _log("  Teamcenter already has {0} (revision {1}, "
                         "rule '{2}').".format(item_id, spec, rule))
                    return spec
        return None
    except Exception as ex:
        _log("  existence pre-check inconclusive ({0}); relying on "
             "commit-time validation.".format(ex))
        return None


def item_exists_in_teamcenter(the_session, item_id, log=None):
    """True if the item id already exists in Teamcenter (see
    find_item_revision_spec). Never raises."""
    return find_item_revision_spec(the_session, item_id, log) is not None


def open_teamcenter_part(the_session, spec):
    """Open a Teamcenter part by its revision spec and make it the displayed part.

    `spec` is an ItemRevisionCliSpec from find_item_revision_spec(). Returns the
    opened part. Raises if NX cannot open it (the caller reports the error).

    If the part is already loaded in the session, it is made the displayed part
    instead: opening it again fails with "File already exists" (seen 2026-11-05).
    """
    loaded = find_loaded_part(the_session, spec)
    if loaded is not None:
        _status, load_status = the_session.Parts.SetActiveDisplay(
            loaded, NXOpen.DisplayPartOption.AllowAdditional,
            NXOpen.PartDisplayPartWorkPartOption.UseLast)
        try:
            load_status.Dispose()
        except Exception:
            pass
        return loaded
    try:
        part, load_status = the_session.Parts.OpenActiveDisplay(
            spec, NXOpen.DisplayPartOption.AllowAdditional)
    except Exception:
        # For checking find_loaded_part's name matching in the syslog.
        names = []
        for p in the_session.Parts:
            try:
                names.append("{0} | {1}".format(p.Leaf, p.FullPath))
            except Exception:
                pass
        the_session.LogFile.WriteLine("open_teamcenter_part: {0} failed; loaded parts: {1}".format(
            spec, "; ".join(names)))
        raise
    try:
        load_status.Dispose()
    except Exception:
        pass
    return part


def find_loaded_part(the_session, spec):
    """The part in this session that `spec` ("@DB/<item>/<rev>") names, or None.

    A Teamcenter part's Leaf is "<item>/<rev>" (see lib/body_dxf.py::_input_file).
    """
    wanted = spec.strip().lower()
    for part in the_session.Parts:
        try:
            names = ("@db/" + str(part.Leaf).lower(), str(part.FullPath).lower())
        except Exception:
            continue
        if wanted in names:
            return part
    return None


# Every revision rule probe_revision_rules() tries by default. "" asks Teamcenter
# for its configured default (which, empirically, does NOT resolve existing parts
# here -- kept first so its behavior is visible in the log). The rest are common TC
# rule names; the site's actual rule set may differ.
DIAGNOSTIC_REVISION_RULES = (
    "",
    "Latest Working",
    "Any Status; Working",
    "Latest Released",
    "Precise",
    "Latest",
)


def probe_revision_rules(the_session, item_id, rules=DIAGNOSTIC_REVISION_RULES, log=None):
    """Diagnostic: try each revision rule on `item_id` and report which resolve it.

    Unlike item_exists_in_teamcenter() this does not stop at the first hit; it
    tries every rule and logs one line per rule (HasFailed and the revision spec),
    so you can see which rules work at your site. `log` is called with each line
    (e.g. lw.WriteLine); omit it to run silently.

    Returns (exists, resolved_rules): exists is True if any rule resolved the id,
    resolved_rules is the list of rule names ("" for the default) that did.
    Raises nothing for a failed rule; the error is logged and that rule counts
    as not resolved. Requires a Teamcenter (managed) session: the_session.PdmSession.
    """
    _log = log or (lambda m: None)
    pdm = the_session.PdmSession
    resolved = []
    for rule in rules:
        label = rule if rule else "(default/empty)"
        try:
            query = NXOpen.PDM.PdmSession.GetConfiguredRevisionInput()
            query.ItemId = item_id
            query.RevisionRuleName = rule
            _errors, results = pdm.GetConfiguredRevisionOfItems([query])
            found = False
            for res in (results or []):
                spec = (res.ItemRevisionCliSpec or "").strip()
                _log("  rule {0:<22} -> HasFailed={1}  spec='{2}'".format(
                    label, res.HasFailed, spec))
                if not res.HasFailed and spec:
                    found = True
            if not results:
                _log("  rule {0:<22} -> (no results)".format(label))
            if found:
                resolved.append(rule)
        except Exception as ex:
            _log("  rule {0:<22} -> error: {1}".format(label, ex))
    return bool(resolved), resolved


def dump_pdm_errors(builder, lw, label):
    """Print the PDM builder's error/warning messages to the Listing Window.

    The generic "not a valid file specification" NXException hides the real
    per-object failure; ErrorMessageHandler.GetErrorMessages() and
    GetOperationFailures() carry the specifics. Best-effort — never raises.
    """
    try:
        handler = builder.GetErrorMessageHandler(True)
        try:
            errs = list(handler.GetErrorMessages() or [])
            warns = list(handler.GetWarningMessages() or [])
        finally:
            handler.Dispose()
        for m in errs:
            lw.WriteLine("  [{0}] ERROR:   {1}".format(label, m))
        for m in warns:
            lw.WriteLine("  [{0}] warning: {1}".format(label, m))
        if not errs and not warns:
            lw.WriteLine("  [{0}] (no PDM messages)".format(label))
    except Exception as ex:
        lw.WriteLine("  [{0}] could not read PDM messages: {1}".format(label, ex))
    # Structured operation-failure list (NXOpen.ErrorInfo: ErrorCode +
    # Description + ErrorObjectDescription). This is the reliable channel --
    # GetErrorMessages() tends to return NULL for these PDM builders.
    try:
        failures = builder.GetOperationFailures()
        try:
            count = failures.Length
            for i in range(count):
                info = failures.GetErrorInfo(i)
                try:
                    try:
                        code = info.ErrorCode
                    except Exception:
                        code = "?"
                    try:
                        desc = info.Description
                    except Exception:
                        desc = "?"
                    try:
                        obj = info.ErrorObjectDescription
                    except Exception:
                        obj = ""
                    lw.WriteLine("  [{0}] failure[{1}]: code={2} | {3}{4}".format(
                        label, i, code, desc,
                        (" | object: " + obj) if obj else ""))
                finally:
                    info.Dispose()
        finally:
            failures.Dispose()
    except Exception as ex:
        lw.WriteLine("  [{0}] could not read operation failures: {1}".format(
            label, ex))


def configure_filenew(fn):
    """Apply the File > New > Item settings used by the COTS-create recording."""
    fn.TemplateFileName = "@DB/model-plain-1-inch-template/A"
    fn.UseBlankTemplate = False
    fn.ApplicationName = "ModelTemplate"
    fn.Units = NXOpen.Part.Units.Inches
    fn.RelationType = "master"
    fn.UsesMasterModel = "No"                  # NOTE: string, not bool
    fn.TemplateType = NXOpen.FileNewTemplateType.Item
    fn.TemplatePresentationName = "Model"
    fn.ItemType = "BE9_Design,BE9_Electrical,BE9_COTS,BE9_Tooling"
    fn.Specialization = ""
    fn.SetCanCreateAltrep(False)
