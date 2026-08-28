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

    def _coll_ref(coll):
        ol = getattr(coll, "override_library", None) if coll else None
        return getattr(ol, "reference", None) if ol else None

    orig_cref = _coll_ref(orig_root)
    rep_cref = _coll_ref(rep_root)
    if orig_cref is not None and orig_cref == rep_cref:
        return True

    # Armature-level: same linked reference, different hierarchy roots.
    orig_ol = getattr(orig, "override_library", None)
    rep_ol = getattr(rep, "override_library", None)
    if orig_ol and rep_ol:
        oref = getattr(orig_ol, "reference", None)
        rref = getattr(rep_ol, "reference", None)
        if oref is not None and oref == rref:
            oh = getattr(orig_ol, "hierarchy_root", None)
            rh = getattr(rep_ol, "hierarchy_root", None)
            if oh and rh and oh != rh:
                return True

    return False


def needs_template_preserving_remove(orig, rep, coll, scene=None):
    """
    True when Remove Original must keep orig override datablocks for save/reload.

    Detects sibling override instances even when orig's collection has already
    lost ``override_library`` (e.g. after a prior broken save).
    """
    if sibling_override_instances(orig, rep, scene):
        return True
    if coll is None or rep is None:
        return False
    scene = scene or bpy.context.scene
    rep_root = override_root_collection(rep, scene)
    if rep_root is None:
        return False
    rep_ol = getattr(rep_root, "override_library", None)
    if rep_ol is None:
        return False
    rep_ref = getattr(rep_ol, "reference", None)
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


def remap_parents(mapping):
    """Reparent objects whose parent is a mapping key onto the mapped target (keep world matrix)."""
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
        world_matrix = ob.matrix_world.copy()
        try:
            ob.parent = new_parent
            ob.matrix_world = world_matrix
            n += 1
        except Exception:
            pass
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
