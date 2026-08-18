# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

"""Remap object ID pointers (constraints, modifiers, DOF, drivers) from orig to rep."""

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


def remap_object_usages(src, dst, orig_to_rep=None, skip_bone_constraints_on=None, skip_self_drivers_on=None):
    """
    Remap object ID pointers from src (and orig_to_rep keys) to dst/mapped targets.

    Walks object constraints, pose-bone constraints (incl. ArmatureConstraint.targets),
    armature-modifier object pointers, camera DOF focus_object, and driver target IDs
    on objects and armature datablocks.

    skip_bone_constraints_on: armatures whose pose-bone constraints are left alone
        (orig's Rigify self-targets during RetargRelatives).
    skip_self_drivers_on: objects whose drivers targeting themselves are left alone
        (orig-owned Rigify drivers during RetargRelatives). Drivers on other owners
        that point at src are still remapped. Third-party IDs (e.g. leftover Steve)
        are not rewritten to dst.
    """
    mapping = _id_map(src, dst, orig_to_rep)
    if not mapping:
        return {"constraints": 0, "bone_constraints": 0, "modifiers": 0, "dof": 0, "drivers": 0}
    skip_bones = set(skip_bone_constraints_on or ())
    skip_drivers = set(skip_self_drivers_on or ())
    counts = {"constraints": 0, "bone_constraints": 0, "modifiers": 0, "dof": 0, "drivers": 0}

    for ob in bpy.data.objects:
        for c in getattr(ob, "constraints", []):
            if _remap_constraint(c, mapping):
                counts["constraints"] += 1
        if ob.type == "ARMATURE" and ob.pose and ob not in skip_bones:
            for pbone in ob.pose.bones:
                for c in pbone.constraints:
                    if _remap_constraint(c, mapping):
                        counts["bone_constraints"] += 1
        if ob.modifiers:
            for m in ob.modifiers:
                if m.type != "ARMATURE":
                    continue
                obj = getattr(m, "object", None)
                new = _mapped(obj, mapping)
                if new is not obj:
                    try:
                        m.object = new
                        counts["modifiers"] += 1
                    except Exception:
                        pass
        if ob.type == "CAMERA" and ob.data and getattr(ob.data, "dof", None):
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
