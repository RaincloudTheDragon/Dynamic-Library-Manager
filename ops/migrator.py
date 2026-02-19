# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

"""Character migrator: migrate animation, constraints, relations from original to replacement armature."""

import bpy

from ..utils import descendants


def get_pair_manual(context):
    """Return (orig_armature, rep_armature) from scene props, or (None, None)."""
    props = getattr(context.scene, "dynamic_link_manager", None)
    if not props:
        return None, None
    orig = getattr(props, "original_character", None)
    rep = getattr(props, "replacement_character", None)
    if orig and orig.type == "ARMATURE" and rep and rep.type == "ARMATURE":
        return orig, rep
    return None, None


def get_pair_automatic(context):
    """Discover one pair by convention: Name_Rigify and Name_Rigify.001. Returns (orig, rep) or (None, None)."""
    pairs = []
    for obj in bpy.data.objects:
        if obj.type != "ARMATURE":
            continue
        name = obj.name
        if name.endswith("_Rigify.001"):
            base = name[:-len("_Rigify.001")]
            orig = bpy.data.objects.get(f"{base}_Rigify")
            if orig and orig.type == "ARMATURE" and orig != obj:
                pairs.append((orig, obj))
    return pairs[0] if pairs else (None, None)


def run_step_1(orig, rep):
    """Copy armature object attributes: location, rotation, scale."""
    rep.location = orig.location.copy()
    if orig.rotation_mode == "QUATERNION":
        rep.rotation_quaternion = orig.rotation_quaternion.copy()
    else:
        rep.rotation_euler = orig.rotation_euler.copy()
    rep.scale = orig.scale.copy()


def run_step_2(orig, rep):
    """Migrate NLA: copy tracks and strips to replacement."""
    if not orig.animation_data or not orig.animation_data.nla_tracks:
        return
    if rep.animation_data is None:
        rep.animation_data_create()
    for track in list(rep.animation_data.nla_tracks):
        rep.animation_data.nla_tracks.remove(track)
    prev_track = None
    for track in orig.animation_data.nla_tracks:
        new_track = rep.animation_data.nla_tracks.new(prev=prev_track)
        new_track.name = track.name
        new_track.mute = track.mute
        new_track.is_solo = track.is_solo
        new_track.lock = track.lock
        for strip in track.strips:
            new_strip = new_track.strips.new(strip.name, int(strip.frame_start), strip.action)
            new_strip.blend_type = strip.blend_type
            new_strip.extrapolation = strip.extrapolation
            new_strip.frame_end = strip.frame_end
            new_strip.blend_in = strip.blend_in
            new_strip.blend_out = strip.blend_out
            new_strip.repeat = strip.repeat
        prev_track = new_track


EXCLUDE_PROPS = {"_RNA_UI", "rigify_type", "rigify_parameters"}


def run_step_3(orig, rep):
    """Custom properties: copy pose-bone custom props, exclude rigify internals."""
    for pbone in orig.pose.bones:
        if pbone.name not in rep.pose.bones:
            continue
        rbone = rep.pose.bones[pbone.name]
        for key in list(pbone.keys()):
            if key in EXCLUDE_PROPS:
                continue
            try:
                rbone[key] = pbone[key]
            except Exception:
                pass


def run_step_4(orig, rep, orig_to_rep):
    """Bone constraints: remove stale on rep, copy from orig with retarget, trim duplicates."""
    other_originals = [o for o in orig_to_rep if o != orig]
    for pb in rep.pose.bones:
        to_remove = [c for c in pb.constraints if getattr(c, "target", None) in other_originals]
        for c in to_remove:
            pb.constraints.remove(c)
    for pbone in orig.pose.bones:
        if pbone.name not in rep.pose.bones:
            continue
        rbone = rep.pose.bones[pbone.name]
        for c in pbone.constraints:
            if getattr(c, "target", None) == orig:
                continue
            nc = rbone.constraints.new(type=c.type)
            nc.name = c.name
            nc.mute = c.mute
            nc.influence = c.influence
            t = getattr(c, "target", None)
            if t is not None and t in orig_to_rep:
                nc.target = orig_to_rep[t]
            elif getattr(nc, "target", None) is not None and t:
                nc.target = t
            if hasattr(c, "subtarget") and c.subtarget:
                nc.subtarget = c.subtarget
            for prop in ("head_tail", "use_bone_object", "invert_x", "invert_y", "invert_z"):
                if hasattr(c, prop):
                    try:
                        setattr(nc, prop, getattr(c, prop))
                    except Exception:
                        pass
    for pb in orig.pose.bones:
        if pb.name not in rep.pose.bones:
            continue
        ro, rr = pb.constraints, rep.pose.bones[pb.name].constraints
        while len(rr) > len(ro):
            rr.remove(rr[-1])


def run_step_5(orig, rep, rep_descendants, orig_to_rep):
    """Retarget relations: parents, constraint targets, Armature modifiers to rep."""
    candidates = set(rep_descendants)
    for ob in bpy.data.objects:
        if getattr(ob.parent, "name", None) == orig.name:
            candidates.add(ob)
        for c in getattr(ob, "constraints", []):
            if getattr(c, "target", None) == orig:
                candidates.add(ob)
    for ob in candidates:
        if ob.parent == orig:
            ob.parent = rep
        for c in getattr(ob, "constraints", []):
            if getattr(c, "target", None) == orig:
                c.target = rep
        if ob.type == "MESH" and ob.modifiers:
            for m in ob.modifiers:
                if getattr(m, "object", None) == orig:
                    m.object = rep


def run_step_6(orig, rep, rep_descendants):
    """Replacement base body: library override only, then shape-key action."""
    for ob in rep_descendants:
        if ob.type != "MESH":
            continue
        name_lower = (ob.name + " " + (ob.data.name if ob.data else "")).lower()
        if "body" not in name_lower or "base" not in name_lower:
            continue
        if ob.modifiers:
            for m in ob.modifiers:
                if m.type == "ARMATURE" and m.object == rep:
                    break
            else:
                continue
        if getattr(ob.data, "library", None) or getattr(ob.data, "override_library", None):
            try:
                ob.data.override_create()
            except Exception:
                pass
        if ob.data.shape_keys:
            if not ob.data.shape_keys.animation_data:
                ob.data.shape_keys.animation_data_create()
            body_name = ob.name
            action = (
                bpy.data.actions.get(body_name + "Action")
                or bpy.data.actions.get(ob.data.name + "Action")
                or bpy.data.actions.get(body_name + "Action.001")
            )
            if action:
                ob.data.shape_keys.animation_data.action = action


def run_full_migration(context):
    """
    Run the full 7-step character migration for the single pair (manual or automatic).
    Returns (True, message) on success, (False, error_message) on failure.
    """
    props = getattr(context.scene, "dynamic_link_manager", None)
    use_auto = props and getattr(props, "migrator_mode", False)
    orig, rep = (get_pair_automatic(context) if use_auto else get_pair_manual(context))
    if not orig or not rep:
        return False, "No character pair (set Original/Replacement or enable Automatic)."
    if orig == rep:
        return False, "Original and replacement must be different armatures."

    orig_to_rep = {orig: rep}
    rep_descendants = descendants(rep)

    try:
        run_step_1(orig, rep)
        run_step_2(orig, rep)
        run_step_3(orig, rep)
        run_step_4(orig, rep, orig_to_rep)
        run_step_5(orig, rep, rep_descendants, orig_to_rep)
        run_step_6(orig, rep, rep_descendants)
    except Exception as e:
        return False, str(e)
    return True, f"Migrated {orig.name} → {rep.name}"
