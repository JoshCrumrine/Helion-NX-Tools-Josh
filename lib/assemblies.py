"""Assembly tree helpers."""
import NXOpen


def walk_components(root=None, include_root=False):
    """Yield (component, depth) for every component below `root`, depth-first.

    `root` defaults to the root component of the displayed part. Depth is 1 for
    direct children of the root (0 for the root itself when include_root=True).
    Yields nothing for a piece part, or when the assembly is not fully loaded
    (RootComponent is None).
    """
    if root is None:
        part = NXOpen.Session.GetSession().Parts.Display
        root = part.ComponentAssembly.RootComponent if part is not None else None
    if root is None:
        return

    stack = [(root, 0)]
    while stack:
        comp, depth = stack.pop()
        if depth > 0 or include_root:
            yield comp, depth
        # Reversed so children come out in tree order from a LIFO stack.
        for child in reversed(comp.GetChildren()):
            stack.append((child, depth + 1))


def find_component(predicate, root=None):
    """Return the first component (depth-first) for which predicate(comp) is
    true, or None. E.g.:

        find_component(lambda c: c.DisplayName == "BRACKET")
        find_component(lambda c: c.Prototype.Leaf.startswith("1150201-500"))

    An exception raised by the predicate (e.g. Prototype on an unloaded
    component) counts as no match.
    """
    for comp, _depth in walk_components(root):
        try:
            if predicate(comp):
                return comp
        except Exception:
            continue
    return None


def get_bodies(component, solid_only=False, include_hidden=True):
    """Return the bodies of `component` as occurrences in the assembly context
    (so they can be used with the displayed part: blank, measure, move to layer).

    Walks the bodies of the component's prototype part and maps each through
    Component.FindOccurrence. Returns [] if the component is not loaded or is
    suppressed. Child components are NOT included; combine with
    walk_components to gather a whole subtree.

    solid_only:     keep only solid bodies (drop sheet bodies).
    include_hidden: when False, drop bodies that are blanked.
    """
    try:
        proto_part = component.Prototype
        if proto_part is None or component.IsSuppressed:
            return []
        proto_bodies = list(proto_part.Bodies)
    except Exception:
        return []

    bodies = []
    for proto in proto_bodies:
        if solid_only and not proto.IsSolidBody:
            continue
        try:
            occ = component.FindOccurrence(proto)
        except Exception:
            occ = None
        if occ is None:
            continue
        if not include_hidden and occ.IsBlanked:
            continue
        bodies.append(occ)
    return bodies


def get_body_material(body):
    """Return the name of the NX physical material assigned to `body`, or None.

    Materials are stored on the prototype body in its owning part, so an
    occurrence body (as returned by get_bodies) is mapped back to its prototype
    and the owning part's MaterialManager is asked. Returns None when no
    material is assigned or the lookup fails.
    """
    try:
        proto = body.Prototype if body.IsOccurrence else body
        material = proto.OwningPart.MaterialManager.PhysicalMaterials.AskMaterialOfObject(proto)
        return material.Name if material is not None else None
    except Exception:
        return None


def find_display_body(comp, proto_body):
    """The object in the displayed assembly that stands for `proto_body`.

    The bodies of a component's part are prototypes; what the assembly shows is the
    occurrence, found with Component.FindOccurrence (the same mapping get_bodies uses).
    `comp` None means the body belongs to the displayed (active) part itself, which is
    not an occurrence, so the body is returned as is. Use the result to highlight the
    body on screen. Returns None if it cannot be found; never raises.
    """
    try:
        if comp is None:
            return proto_body
        return comp.FindOccurrence(proto_body)
    except Exception:
        return None


def assign_material(part, body, name, libraries=()):
    """Assign the library material `name` to `body`, a body of `part`.

    `part` must be the current work part (NX assigns in the work part's context), and
    `body` a body of that part (not an occurrence). Follows the recorded
    example_journals/journal_assign_material.py (find the material in the part, then
    PhysicalMaterial.AssignObjects([body])), after getting the material into the part:

      1. already loaded in the part ("PhysicalMaterial[<name>]"), else
      2. loaded from each MatML file in `libraries` (full path or file name), in order
         with PhysicalMaterialCollection.LoadFromMatmlLibrary, else
      3. NX's built-in default library (LoadFromNxmatmllibrary). Many sites switch that
         library off (customer default "Default Material Library - Show"), in which case
         this step finds nothing; the site's own MatML file in step 2 is what works.

    Returns (True, "") on success, or (False, reason) where the reason lists every
    attempt and what NX said about it. Never raises. Success is only reported once
    get_body_material() reads the new material back.
    """
    attempts = []
    try:
        pm = part.MaterialManager.PhysicalMaterials
    except Exception as ex:
        return False, "no material manager on {0}: {1}".format(getattr(part, "Leaf", part), ex)

    material = None
    try:
        material = pm.FindObject("PhysicalMaterial[{0}]".format(name))
    except Exception as ex:
        attempts.append("not already in the part ({0})".format(ex))

    if material is None:
        for library in libraries:
            try:
                material = pm.LoadFromMatmlLibrary(library, name)
                break
            except Exception as ex:
                attempts.append("{0}: {1}".format(library.replace("\\", "/").split("/")[-1], ex))
    if material is None:
        try:
            material = pm.LoadFromNxmatmllibrary(name)
        except Exception as ex:
            attempts.append("NX default library: {0}".format(ex))
    if material is None:
        return False, "could not load '{0}': {1}".format(name, "; ".join(attempts))

    try:
        material.AssignObjects([body])
    except Exception as ex:
        return False, "loaded '{0}' but AssignObjects failed: {1}".format(name, ex)
    if get_body_material(body) is None:
        return False, "NX accepted the assignment but the body still shows no material"
    return True, ""


def update_mass_properties(part):
    """Update the mass properties (weight) of `part` so they use the materials its bodies have now.

    Same as Analysis > Mass Properties > Update Now: a MassPropertiesBuilder on the part, UpdateNow().
    There is nothing to commit, so no feature is created. For an assembly part it is the assembly's
    weight that is updated. Call it while `part` is the work part, as after assign_material.

    Returns (True, "") or (False, what NX said). Never raises.
    """
    builder = None
    try:
        builder = part.PropertiesManager.CreateMassPropertiesBuilder([part])
        builder.UpdateNow()
        return True, ""
    except Exception as ex:
        return False, str(ex)
    finally:
        if builder is not None:
            try:
                builder.Destroy()
            except Exception:
                pass