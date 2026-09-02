# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

"""Remap object ID pointers (constraints, modifiers, DOF, drivers) from orig to rep."""

import re

import bpy


def _id_map(src, dst, orig_to_rep):
    """Merge orig_to_rep with src→dst. Later keys win for src."""
    mapping = {}
    if orig_to_rep:
        mapping.update(orig_to_rep)
    if src is not None and dst is not None:
        mapping[src] = dst
    return mapping


def _mapped(val, mapping):
    """Return mapping[val] if val is a mapped ID, else val."""
    if val is None:
        return None
    return mapping.get(val, val)


def _strip_dup_suffix(name):
    """GEO-GOCART.001 -> GEO-GOCART (Blender duplicate suffix)."""
    if not name:
        return name
    return re.sub(r"\.\d{3}$", "", name)


def _objects_in_collection_recursive(coll):
    """All objects in coll and nested child collections."""
    out = []
    if coll is None:
        return out

    def walk(c):
        for ob in c.objects:
            out.append(ob)
        for child in c.children:
            walk(child)

    walk(coll)
    return out


def _parent_collection(scene, coll):
    """Parent of coll in the scene tree, or None."""
    if coll is None or scene is None:
        return None
    master = scene.collection
    if coll.name in master.children:
        return master
    for p in bpy.data.collections:
        if coll.name in p.children:
            return p
    return None


def _deepest_users_collection(scene, ob):
    """Most nested users_collection of ob under the scene root."""
    colls = list(getattr(ob, "users_collection", []) or [])
    if not colls:
        return None

    def depth(c):
        d = 0
        cur = c
        while cur is not None and cur != scene.collection:
            d += 1
            cur = _parent_collection(scene, cur)
        return d

    return max(colls, key=depth)


def object_in_collection_tree(ob, coll):
    """True if ob is coll itself or any object under coll (recursive)."""
    if ob is None or coll is None:
        return False
    if ob == coll:
        return True
    return ob in _objects_in_collection_recursive(coll)


def _override_reference(idb):
    """Linked source ID for a library override, or None."""
    ol = getattr(idb, "override_library", None) if idb else None
    return getattr(ol, "reference", None) if ol else None


def _override_lib_filepath(idb):
    """Library filepath backing an override (via reference.library), or None."""
    ref = _override_reference(idb)
    if ref is None:
        return None
    lib = getattr(ref, "library", None)
    return getattr(lib, "filepath", None) if lib else None


def is_library_override_id(idb):
    """True if *idb* is a (local) library override."""
    return idb is not None and getattr(idb, "override_library", None) is not None


def collection_tree_has_overrides(coll):
    """True if *coll* or any object under it is a library override."""
    if coll is None:
        return False
    if is_library_override_id(coll):
        return True
    for ob in _objects_in_collection_recursive(coll):
        if is_library_override_id(ob):
            return True
        data = getattr(ob, "data", None)
        if is_library_override_id(data):
            return True
    return False


def live_override_template_ids(exclude=None):
    """
    Linked IDs currently used as override_library.reference by any local override.

    These are Blender's override templates — deleting them (or the last hierarchy
    that owns them) triggers: \"Library override templates have been removed\".
    """
    exclude = {e for e in (exclude or ()) if e is not None}
    out = set()
    for coll_data in (
        bpy.data.objects,
        bpy.data.armatures,
        bpy.data.meshes,
        bpy.data.collections,
    ):
        for idb in coll_data:
            if idb in exclude or getattr(idb, "library", None):
                continue
            if not is_library_override_id(idb):
                continue
            ref = _override_reference(idb)
            if ref is not None:
                out.add(ref)
    return out


def sibling_override_instances(orig, rep, scene=None):
    """
    True when orig and rep are separate override instances of the same linked asset.

    Example: ``Regina`` and ``Regina.001`` both override the linked ``Regina``
    collection from ``Regina_v4.5.blend``. Removing the orig override root with
    ``collections.remove()`` destroys the shared override template and breaks the
    rep instance on save/reload.
    """
    if orig is None or rep is None or orig == rep:
        return False
    scene = scene or bpy.context.scene
    orig_root = override_root_collection(orig, scene)
    rep_root = override_root_collection(rep, scene)
    if orig_root is not None and rep_root is not None and orig_root == rep_root:
        return False

    orig_cref = _override_reference(orig_root)
    rep_cref = _override_reference(rep_root)
    if orig_cref is not None and orig_cref == rep_cref:
        return True

    # Armature-level: same linked reference, different hierarchy roots.
    oref = _override_reference(orig)
    rref = _override_reference(rep)
    if oref is not None and oref == rref:
        orig_ol = getattr(orig, "override_library", None)
        rep_ol = getattr(rep, "override_library", None)
        oh = getattr(orig_ol, "hierarchy_root", None) if orig_ol else None
        rh = getattr(rep_ol, "hierarchy_root", None) if rep_ol else None
        if oh and rh and oh != rh:
            return True
        # Same linked armature reference even when hierarchy_root is missing/equal.
        if oref == rref and orig != rep:
            return True

    # Same library file + matching base names (detection when refs already diverge).
    op = _override_lib_filepath(orig) or _override_lib_filepath(orig_root)
    rp = _override_lib_filepath(rep) or _override_lib_filepath(rep_root)
    if op and rp and op == rp:
        if _strip_dup_suffix(orig.name) == _strip_dup_suffix(rep.name):
            return True
        if orig_root and rep_root:
            if _strip_dup_suffix(orig_root.name) == _strip_dup_suffix(rep_root.name):
                return True

    return False


def needs_template_preserving_remove(orig, rep, coll, scene=None):
    """
    True when Remove Original must soft-unlink instead of deleting override IDs.

    Any library-override orig (or override collection tree) must be preserved:
    ``collections.remove()`` / deleting override datablocks destroys Blender's
    shared override templates and breaks remaining instances on save/reload.
    """
    if is_library_override_id(orig):
        return True
    if collection_tree_has_overrides(coll):
        return True
    if sibling_override_instances(orig, rep, scene):
        return True
    if coll is None or rep is None:
        return False
    scene = scene or bpy.context.scene
    rep_root = override_root_collection(rep, scene)
    if rep_root is None:
        return False
    rep_ref = _override_reference(rep_root)
    if rep_ref is None:
        return False
    ref_name = getattr(rep_ref, "name", None)
    if ref_name and coll.name == ref_name:
        return True
    if coll.name == _strip_dup_suffix(rep_root.name):
        return True
    return False


def _override_asset_root_for_armature(ob, scene=None):
    """Override asset root collection for an armature (hierarchy_root, users, or naming)."""
    if ob is None:
        return None
    scene = scene or bpy.context.scene
    ol = getattr(ob, "override_library", None)
    if ol is not None:
        hroot = getattr(ol, "hierarchy_root", None)
        if hroot is not None:
            coll = bpy.data.collections.get(hroot.name)
            if coll is not None:
                return coll
    root = override_root_collection(ob, scene)
    if root is not None:
        return root
    name = ob.name
    if name.endswith("_Rigify.001"):
        base = name[: -len("_Rigify.001")]
        coll = bpy.data.collections.get(f"{base}.001")
        if coll is not None:
            return coll
    if name.endswith("_Rigify"):
        base = name[: -len("_Rigify")]
        for suffix in (".001", ""):
            coll = bpy.data.collections.get(f"{base}{suffix}")
            if coll is not None and getattr(coll, "override_library", None) is not None:
                return coll
    return None


def resolve_migration_armature(ob, scene=None):
    """
    Return the armature inside ob's override asset root.

    Picked ``Name_Rigify.001`` is often a collectionless duplicate; the real
    override armature is ``Name_Rigify`` inside ``Name.001``.
    """
    if ob is None or ob.type != "ARMATURE":
        return ob
    scene = scene or bpy.context.scene
    root = _override_asset_root_for_armature(ob, scene)
    if root is None:
        return ob

    arms = [x for x in _objects_in_collection_recursive(root) if x.type == "ARMATURE"]
    if not arms:
        return ob
    if object_in_collection_tree(ob, root):
        return ob
    if len(arms) == 1:
        return arms[0]

    ob_ref = _override_reference(ob)
    ob_base = _strip_dup_suffix(ob.name)
    for arm in arms:
        if ob_ref is not None and _override_reference(arm) == ob_ref:
            return arm
    for arm in arms:
        if _strip_dup_suffix(arm.name) == ob_base:
            return arm
    return ob


def consolidate_migration_armature(ghost, canonical, scene=None):
    """
    Move migrated data from a collectionless duplicate onto the canonical override
    armature, remap scene refs, and delete the ghost.
    """
    if ghost is None or canonical is None or ghost == canonical:
        return canonical

    g_ad = getattr(ghost, "animation_data", None)
    if g_ad and g_ad.action:
        if canonical.animation_data is None:
            canonical.animation_data_create()
        if canonical.animation_data.action is None:
            canonical.animation_data.action = g_ad.action

    for c in list(ghost.constraints):
        dup = any(
            x.type == c.type and getattr(x, "target", None) == getattr(c, "target", None)
            for x in canonical.constraints
        )
        if dup:
            continue
        nc = canonical.constraints.new(type=c.type)
        nc.name = c.name
        for prop in c.bl_rna.properties:
            if prop.is_readonly or prop.identifier in ("name", "type"):
                continue
            if not hasattr(nc, prop.identifier):
                continue
            try:
                setattr(nc, prop.identifier, getattr(c, prop.identifier))
            except Exception:
                pass

    if ghost.parent and not canonical.parent and not any(
        x.type == "CHILD_OF" for x in canonical.constraints
    ):
        canonical.parent = ghost.parent
        canonical.parent_type = ghost.parent_type
        canonical.parent_bone = ghost.parent_bone
        try:
            canonical.matrix_world = ghost.matrix_world.copy()
        except Exception:
            pass

    remap_object_usages(ghost, canonical)
    try:
        bpy.data.objects.remove(ghost, do_unlink=True)
    except Exception:
        pass
    return canonical


def override_root_collection(ob, scene=None):
    """
    Outermost override (or scene-root) collection containing ob.

    For linked assets like GOCART (GEO + RIG under one override), this is the
    asset instance root — not just the armature's immediate collection.
    """
    if ob is None:
        return None
    scene = scene or bpy.context.scene
    inner = _deepest_users_collection(scene, ob)
    if inner is None:
        return None
    chain = []
    cur = inner
    while cur is not None and cur != scene.collection:
        chain.append(cur)
        cur = _parent_collection(scene, cur)
    if not chain:
        return None
    for c in reversed(chain):
        if getattr(c, "override_library", None) is not None:
            return c
    return chain[-1]


def _override_reference(ob):
    """Linked ID this local override remaps, or None."""
    ol = getattr(ob, "override_library", None)
    if ol is None:
        return None
    return getattr(ol, "reference", None)


def build_override_collection_object_map(orig, rep, scene=None):
    """
    Map objects in orig's override/asset collection to matching objects in rep's.

    Primary match: shared ``override_library.reference`` (correct for GEO-GOCART /
    Jiffy.### pairs across two instances of the same linked asset).

    Fallback: exact name, then unique base name after stripping a single ``.###``
    suffix (only when that base is unique on both sides — avoids collapsing
    intentional Jiffy / Jiffy.001 siblings).

    Returns {orig_ob: rep_ob}.
    """
    scene = scene or bpy.context.scene
    mapping = {}
    if orig is None or rep is None or orig == rep:
        return mapping

    orig_root = override_root_collection(orig, scene)
    rep_root = override_root_collection(rep, scene)
    if orig_root is None or rep_root is None or orig_root == rep_root:
        mapping[orig] = rep
        return mapping

    orig_objs = _objects_in_collection_recursive(orig_root)
    rep_objs = _objects_in_collection_recursive(rep_root)
    rep_set = set(rep_objs)

    # 1) Library-override reference (best 1:1 across instances).
    rep_by_ref = {}
    for o in rep_objs:
        ref = _override_reference(o)
        if ref is not None:
            rep_by_ref[ref] = o

    matched_orig = set()
    matched_rep = set()
    for o in orig_objs:
        ref = _override_reference(o)
        if ref is None:
            continue
        hit = rep_by_ref.get(ref)
        if hit is not None and hit != o and hit in rep_set:
            mapping[o] = hit
            matched_orig.add(o)
            matched_rep.add(hit)

    # 2) Exact name for leftovers (non-override / widgets).
    rep_by_exact = {}
    for o in rep_objs:
        if o in matched_rep:
            continue
        rep_by_exact.setdefault(o.name, []).append(o)

    for o in orig_objs:
        if o in matched_orig:
            continue
        cands = [c for c in rep_by_exact.get(o.name, []) if c != o]
        if len(cands) == 1:
            mapping[o] = cands[0]
            matched_orig.add(o)
            matched_rep.add(cands[0])

    # 3) Unique base-name match (strip one .###) — only if base is unique on both sides.
    orig_by_base = {}
    rep_by_base = {}
    for o in orig_objs:
        if o in matched_orig:
            continue
        orig_by_base.setdefault(_strip_dup_suffix(o.name), []).append(o)
    for o in rep_objs:
        if o in matched_rep:
            continue
        rep_by_base.setdefault(_strip_dup_suffix(o.name), []).append(o)

    for base, olist in orig_by_base.items():
        if len(olist) != 1:
            continue
        rlist = [c for c in rep_by_base.get(base, []) if c != olist[0]]
        if len(rlist) != 1:
            continue
        mapping[olist[0]] = rlist[0]

    mapping[orig] = rep
    preview = ", ".join(f"{a.name}->{b.name}" for a, b in list(mapping.items())[:8])
    print(
        f"[DLM remap] collection map {orig_root.name!r}->{rep_root.name!r}: "
        f"{len(mapping)} object(s) ({preview}{'...' if len(mapping) > 8 else ''})"
    )
    return mapping


def _remap_constraint(c, mapping):
    """Remap constraint target and ArmatureConstraint.targets. Return True if anything changed."""
    changed = False
    tgt = getattr(c, "target", None)
    new = _mapped(tgt, mapping)
    if new is not tgt:
        try:
            c.target = new
            changed = True
        except Exception:
            pass
    targets = getattr(c, "targets", None)
    if targets is None:
        return changed
    for item in targets:
        it = getattr(item, "target", None)
        new_it = _mapped(it, mapping)
        if new_it is not it:
            try:
                item.target = new_it
                changed = True
            except Exception:
                pass
    return changed


def _remap_modifier_object_ptrs(m, mapping):
    """Remap Object POINTER props on a modifier (Armature, Boolean, GN, etc.)."""
    changed = False
    try:
        props = m.bl_rna.properties
    except Exception:
        return False
    for prop in props:
        if prop.type != "POINTER" or prop.identifier == "rna_type":
            continue
        try:
            val = getattr(m, prop.identifier, None)
        except Exception:
            continue
        if not isinstance(val, bpy.types.Object):
            continue
        new = _mapped(val, mapping)
        if new is not val:
            try:
                setattr(m, prop.identifier, new)
                changed = True
            except Exception:
                pass
    return changed


def _owner_is_self_driver_skip(owner, skip_self_drivers_on):
    """True if this animation_data owner is orig (object or its armature data)."""
    if not skip_self_drivers_on:
        return False
    if owner in skip_self_drivers_on:
        return True
    for ob in skip_self_drivers_on:
        if getattr(ob, "data", None) is owner:
            return True
    return False


def _remap_drivers_on(owner, mapping, skip_self_drivers_on):
    """Remap DriverTarget.id on owner.animation_data. Return count remapped."""
    ad = getattr(owner, "animation_data", None)
    if not ad:
        return 0
    skip_self = _owner_is_self_driver_skip(owner, skip_self_drivers_on)
    n = 0
    for fcu in ad.drivers:
        drv = getattr(fcu, "driver", None)
        if drv is None:
            continue
        for var in drv.variables:
            for tgt in var.targets:
                tid = tgt.id
                if tid is None:
                    continue
                # Leave orig's own self-drivers (Rigify) pointing at orig during retarg.
                if skip_self and tid in skip_self_drivers_on:
                    continue
                new = _mapped(tid, mapping)
                if new is not tid:
                    try:
                        tgt.id = new
                        n += 1
                    except Exception:
                        pass
    return n


def _has_non_unit_scale(ob) -> bool:
    """True when object scale is not (1, 1, 1)."""
    from mathutils import Vector

    return (Vector(ob.scale) - Vector((1.0, 1.0, 1.0))).length > 1e-4


def _matrix_world_loc_rot_only(ob):
    """Return parent ``matrix_world`` with scale removed (loc/rot only)."""
    from mathutils import Matrix

    loc, rot, _scale = ob.matrix_world.decompose()
    return Matrix.LocRotScale(loc, rot, (1.0, 1.0, 1.0))


def _new_parent_matrix_for_reparent(new_parent, old_parent):
    """
    Parent matrix used when solving ``new_local`` during reparent.

    When *old_parent* is scaled, *new_parent* is normalized to unit scale and
    only loc/rot is used so rep props can stay at applied scale.
    """
    if _has_non_unit_scale(old_parent):
        if _has_non_unit_scale(new_parent):
            new_parent.scale = (1.0, 1.0, 1.0)
        return _matrix_world_loc_rot_only(new_parent)
    return new_parent.matrix_world.copy()


def _child_parent_space_matrix(parent, child, *, old_parent=None):
    """
    Evaluated parenting space for *child* under *parent*.

    Bone-parented children use ``parent.mw @ pose_bone.matrix``; object parents use
    the usual object matrix (with scale normalization when *old_parent* is scaled).
    """
    if (
        getattr(child, "parent_type", "OBJECT") == "BONE"
        and getattr(child, "parent_bone", "")
        and getattr(parent, "type", None) == "ARMATURE"
        and getattr(parent, "pose", None) is not None
    ):
        pb = parent.pose.bones.get(child.parent_bone)
        if pb is not None:
            if old_parent is not None and _has_non_unit_scale(old_parent):
                if _has_non_unit_scale(parent):
                    parent.scale = (1.0, 1.0, 1.0)
                arm_mw = _matrix_world_loc_rot_only(parent)
            else:
                arm_mw = parent.matrix_world.copy()
            return arm_mw @ pb.matrix
    if old_parent is not None:
        return _new_parent_matrix_for_reparent(parent, old_parent)
    return parent.matrix_world.copy()


def _set_keyframe_value(kp, new_y: float) -> None:
    """Set key value and shift Bezier handles by the same delta (avoids mid-curve zoops)."""
    old_y = kp.co.y
    delta = new_y - old_y
    if abs(delta) < 1e-12:
        return
    kp.co.y = new_y
    try:
        kp.handle_left.y += delta
        kp.handle_right.y += delta
    except Exception:
        pass


def _iter_action_fcurves(action):
    """Yield f-curves from legacy actions and Blender 5 action layers."""
    if action is None:
        return
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        for fc in legacy:
            yield fc
    for layer in getattr(action, "layers", []) or []:
        for strip in getattr(layer, "strips", []) or []:
            if getattr(strip, "type", None) != "KEYFRAME":
                continue
            for cb in getattr(strip, "channelbags", []) or []:
                for fc in getattr(cb, "fcurves", []) or []:
                    yield fc


def transform_object_action_for_reparent(ob, old_parent, new_parent) -> bool:
    """
    Rewrite *ob* action keyframes from *old_parent* local space into *new_parent* space.

    Grabbers (and similar children) often have location/rotation actions authored under
    a scaled orig prop. RetargRelatives reparents them onto a unit-scale rep; without
    retargeting the curves, evaluated locals stay in the old parent space and hands
    follow grabbers meters off the mesh when scrubbing.

    Bone-parented children whose bone exists on both armatures keep their action as-is
    (keys are already bone-local). Bezier handles are shifted with any rewritten value
    so mid-range scrub does not zoop from stale handle positions.
    """
    ad = getattr(ob, "animation_data", None)
    if ad is None or ad.action is None or old_parent is None or new_parent is None:
        return False

    # Same bone on both armatures: location keys are already in that bone's space.
    if (
        getattr(ob, "parent_type", "OBJECT") == "BONE"
        and getattr(ob, "parent_bone", "")
        and getattr(old_parent, "type", None) == "ARMATURE"
        and getattr(new_parent, "type", None) == "ARMATURE"
        and ob.parent_bone in getattr(old_parent.pose, "bones", {})
        and ob.parent_bone in getattr(new_parent.pose, "bones", {})
        and not _has_non_unit_scale(old_parent)
        and not _has_non_unit_scale(new_parent)
    ):
        print(
            f"[DLM remap] skip action retarget on {ob.name!r} "
            f"(bone parent {ob.parent_bone!r} on both armatures)"
        )
        return False

    fcurves = list(_iter_action_fcurves(ad.action))
    if not fcurves:
        return False
    times = sorted({kp.co.x for fc in fcurves for kp in fc.keyframe_points})
    if not times:
        return False

    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    old_frame = scene.frame_current
    rot_mode = ob.rotation_mode
    local_by_time = {}

    try:
        for t in times:
            scene.frame_set(int(t))
            view_layer.update()
            old_mw = _child_parent_space_matrix(old_parent, ob)
            new_mw = _child_parent_space_matrix(new_parent, ob, old_parent=old_parent)
            local_by_time[t] = new_mw.inverted() @ old_mw @ ob.matrix_local.copy()

        for fc in fcurves:
            path = fc.data_path
            idx = fc.array_index
            for kp in fc.keyframe_points:
                local_new = local_by_time.get(kp.co.x)
                if local_new is None:
                    continue
                if path == "location":
                    _set_keyframe_value(kp, local_new.to_translation()[idx])
                elif path == "rotation_euler":
                    _set_keyframe_value(kp, local_new.to_euler(rot_mode)[idx])
                elif path == "rotation_quaternion":
                    _set_keyframe_value(kp, local_new.to_quaternion()[idx])
                elif path == "scale":
                    _set_keyframe_value(kp, local_new.to_scale()[idx])
            if hasattr(fc, "update"):
                fc.update()

        scene.frame_set(old_frame)
        view_layer.update()
        print(
            f"[DLM remap] retargeted action {ad.action.name!r} on {ob.name!r} "
            f"for reparent {old_parent.name!r} -> {new_parent.name!r}"
        )
        return True
    except Exception:
        scene.frame_set(old_frame)
        view_layer.update()
        return False


def sync_prop_rep_from_orig(orig, rep) -> bool:
    """
    Align rep prop transform to orig when MigNLA did not stick (common on overrides).

    Without this, rep can sit at the origin with no action while orig is animated;
    reparented grabbers then inherit rep's static origin and hands follow them off-set.
    """
    if orig is None or rep is None or orig.type == "ARMATURE" or rep.type == "ARMATURE":
        return False
    ad = getattr(rep, "animation_data", None)
    if ad and ad.action:
        return False
    try:
        rep.scale = (1.0, 1.0, 1.0)
        rep.location = orig.location.copy()
        rep.rotation_mode = orig.rotation_mode
        if orig.rotation_mode == "QUATERNION":
            rep.rotation_quaternion = orig.rotation_quaternion.copy()
        else:
            rep.rotation_euler = orig.rotation_euler.copy()
        print(
            f"[DLM remap] synced prop rep {rep.name!r} loc/rot from {orig.name!r} "
            "(rep had no action)"
        )
        return True
    except Exception:
        return False


def reparent_preserve_world_path(ob, new_parent, old_parent=None):
    """
    Reparent *ob* onto *new_parent* so its world motion matches the old parent chain.

    Blender uses ``matrix_world = parent.matrix_world @ matrix_local`` (object parent)
    or ``parent.mw @ pose_bone.matrix @ …`` (bone parent).

    Prop migration often copies orig scale onto rep (CopyAttr), then RetargRelatives
    reparents grabbers while scales still match. When rep scale is cleared to
    ``(1, 1, 1)`` afterward, a compensation computed against scaled rep matrices
    leaves children ~meters off (hands follow grabbers but both fly off the mesh).

    When *old_parent* has non-unit scale, target *new_parent* at unit scale and
    compensate with the full scaled orig matrix::

        new_local = new_parent.mw(unit) ^ -1 @ old_parent.mw @ old_local
    """
    old_parent = old_parent if old_parent is not None else ob.parent
    if old_parent is None or new_parent is None or ob == new_parent:
        return False
    parent_type = getattr(ob, "parent_type", "OBJECT")
    parent_bone = getattr(ob, "parent_bone", "") or ""
    try:
        # Preserve bone-local basis/inverse when staying on the same bone name —
        # object-space compensation fights keyed bone-local location.
        same_bone = (
            parent_type == "BONE"
            and parent_bone
            and getattr(old_parent, "type", None) == "ARMATURE"
            and getattr(new_parent, "type", None) == "ARMATURE"
            and parent_bone in old_parent.pose.bones
            and parent_bone in new_parent.pose.bones
        )
        if same_bone:
            mpi = ob.matrix_parent_inverse.copy()
            basis = ob.matrix_basis.copy()
            transform_object_action_for_reparent(ob, old_parent, new_parent)
            ob.parent = new_parent
            ob.parent_type = "BONE"
            ob.parent_bone = parent_bone
            ob.matrix_parent_inverse = mpi
            ob.matrix_basis = basis
            return True

        transform_object_action_for_reparent(ob, old_parent, new_parent)

        old_local = ob.matrix_local.copy()
        old_parent_mw = _child_parent_space_matrix(old_parent, ob)
        new_parent_mw = _child_parent_space_matrix(
            new_parent, ob, old_parent=old_parent
        )
        compensated_local = new_parent_mw.inverted() @ old_parent_mw @ old_local
        ob.parent = new_parent
        ob.parent_type = parent_type
        if parent_type == "BONE" and parent_bone:
            ob.parent_bone = parent_bone
        ob.matrix_local = compensated_local
        return True
    except Exception:
        try:
            world_matrix = ob.matrix_world.copy()
            ob.parent = new_parent
            ob.parent_type = parent_type
            if parent_type == "BONE" and parent_bone:
                ob.parent_bone = parent_bone
            ob.matrix_world = world_matrix
            return True
        except Exception:
            return False


def remap_parents(mapping):
    """Reparent objects whose parent is a mapping key onto the mapped target."""
    if not mapping:
        return 0
    n = 0
    # Snapshot first — reparenting mutates hierarchy while we iterate.
    to_fix = [(ob, mapping[ob.parent]) for ob in bpy.data.objects if ob.parent in mapping]
    for ob, new_parent in to_fix:
        if ob in mapping:
            # Orig-side asset objects die with Remove Original; leave their parents.
            continue
        if new_parent is None or ob == new_parent:
            continue
        old_parent = ob.parent
        if reparent_preserve_world_path(ob, new_parent, old_parent=old_parent):
            n += 1
    if n:
        print(f"[DLM remap] parents={n}")
    return n


def remap_object_usages(
    src,
    dst,
    orig_to_rep=None,
    skip_bone_constraints_on=None,
    skip_self_drivers_on=None,
    skip_owners=None,
):
    """
    Remap object ID pointers from src (and orig_to_rep keys) to dst/mapped targets.

    Walks object constraints, pose-bone constraints (incl. ArmatureConstraint.targets),
    modifier Object pointers, camera DOF focus_object, and driver target IDs
    on objects and armature datablocks.

    skip_bone_constraints_on: armatures whose pose-bone constraints are left alone
        (orig's Rigify self-targets during RetargRelatives).
    skip_self_drivers_on: objects whose drivers targeting themselves are left alone
        (orig-owned Rigify drivers during RetargRelatives). Drivers on other owners
        that point at src are still remapped. Third-party IDs (e.g. leftover Steve)
        are not rewritten to dst.
    skip_owners: objects whose object-constraints, modifiers, and DOF are not rewritten
        (orig-side GEO/RIG during RetargRelatives — avoid wiring orig GEO to rep RIG).
    """
    mapping = _id_map(src, dst, orig_to_rep)
    if not mapping:
        return {"constraints": 0, "bone_constraints": 0, "modifiers": 0, "dof": 0, "drivers": 0}
    skip_bones = set(skip_bone_constraints_on or ())
    skip_drivers = set(skip_self_drivers_on or ())
    skip_own = set(skip_owners or ())
    counts = {"constraints": 0, "bone_constraints": 0, "modifiers": 0, "dof": 0, "drivers": 0}

    for ob in bpy.data.objects:
        if ob not in skip_own:
            for c in getattr(ob, "constraints", []):
                if _remap_constraint(c, mapping):
                    counts["constraints"] += 1
        if ob.type == "ARMATURE" and ob.pose and ob not in skip_bones:
            for pbone in ob.pose.bones:
                for c in pbone.constraints:
                    if _remap_constraint(c, mapping):
                        counts["bone_constraints"] += 1
        if ob not in skip_own and ob.modifiers:
            for m in ob.modifiers:
                if _remap_modifier_object_ptrs(m, mapping):
                    counts["modifiers"] += 1
        if ob not in skip_own and ob.type == "CAMERA" and ob.data and getattr(ob.data, "dof", None):
            focus = ob.data.dof.focus_object
            new = _mapped(focus, mapping)
            if new is not focus:
                try:
                    ob.data.dof.focus_object = new
                    counts["dof"] += 1
                except Exception:
                    pass
        counts["drivers"] += _remap_drivers_on(ob, mapping, skip_drivers)
        data = getattr(ob, "data", None)
        if data is not None:
            counts["drivers"] += _remap_drivers_on(data, mapping, skip_drivers)

    seen_arm = {ob.data for ob in bpy.data.objects if ob.type == "ARMATURE" and ob.data}
    for arm in bpy.data.armatures:
        if arm in seen_arm:
            continue
        counts["drivers"] += _remap_drivers_on(arm, mapping, skip_drivers)

    print(
        f"[DLM remap] constraints={counts['constraints']} bone_const={counts['bone_constraints']} "
        f"mods={counts['modifiers']} dof={counts['dof']} drivers={counts['drivers']}"
    )
    return counts
