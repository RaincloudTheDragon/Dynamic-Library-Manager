# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

"""Character migrator: migrate animation, constraints, relations from original to replacement armature."""

import bpy

from ..utils import descendants, collection_containing_armature


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


def run_copy_attr(orig, rep):
    """Copy armature object attributes: location, rotation, scale (CopyAttr)."""
    rep.location = orig.location.copy()
    if orig.rotation_mode == "QUATERNION":
        rep.rotation_quaternion = orig.rotation_quaternion.copy()
    else:
        rep.rotation_euler = orig.rotation_euler.copy()
    rep.scale = orig.scale.copy()


def _mirror_als_turn_on(orig, rep):
    """Mirror als.turn_on (animation layers) from original to replacement armature."""
    key = "als.turn_on"
    if key in orig:
        try:
            rep[key] = orig[key]
        except Exception:
            pass
    for pbone in orig.pose.bones:
        if pbone.name not in rep.pose.bones or key not in pbone:
            continue
        try:
            rep.pose.bones[pbone.name][key] = pbone[key]
        except Exception:
            pass


def run_mig_nla(orig, rep):
    """Migrate NLA: copy tracks and strips to replacement; or apply active action only (MigNLA)."""
    if not orig.animation_data:
        return
    ad = orig.animation_data
    has_nla = ad.nla_tracks and len(ad.nla_tracks) > 0
    active_action = getattr(ad, "action", None)
    if not has_nla and active_action:
        if rep.animation_data is None:
            rep.animation_data_create()
        rep.animation_data.action = active_action
        _mirror_als_turn_on(orig, rep)
        return
    if not has_nla:
        return
    if rep.animation_data is None:
        rep.animation_data_create()
    rep_tracks = rep.animation_data.nla_tracks
    existing_names = {t.name for t in rep_tracks}
    prev_track = rep_tracks[-1] if rep_tracks else None
    for track in ad.nla_tracks:
        new_track = rep_tracks.new(prev=prev_track)
        name = track.name
        if name in existing_names:
            base, n = name, 1
            while f"{base}.{n:03d}" in existing_names:
                n += 1
            name = f"{base}.{n:03d}"
        new_track.name = name
        existing_names.add(name)
        new_track.mute = track.mute
        new_track.is_solo = track.is_solo
        new_track.lock = track.lock
        for strip in track.strips:
            if strip.type != "CLIP" or not strip.action:
                continue
            new_strip = new_track.strips.new(
                strip.name, int(strip.frame_start), strip.action
            )
            new_strip.blend_type = strip.blend_type
            new_strip.extrapolation = strip.extrapolation
            new_strip.frame_end = strip.frame_end
            new_strip.blend_in = strip.blend_in
            new_strip.blend_out = strip.blend_out
            new_strip.repeat = strip.repeat
            new_strip.action_frame_start = strip.action_frame_start
            new_strip.action_frame_end = strip.action_frame_end
            new_strip.influence = strip.influence
            new_strip.mute = strip.mute
            new_strip.scale = strip.scale
            new_strip.use_auto_blend = strip.use_auto_blend
            new_strip.use_reverse = strip.use_reverse
            new_strip.use_animated_influence = strip.use_animated_influence
            new_strip.use_animated_time = strip.use_animated_time
            new_strip.use_animated_time_cyclic = strip.use_animated_time_cyclic
            new_strip.use_sync_length = strip.use_sync_length
        prev_track = new_track
    _mirror_als_turn_on(orig, rep)


EXCLUDE_PROPS = {"_RNA_UI", "rigify_type", "rigify_parameters"}


def run_mig_cust_props(orig, rep):
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


def run_mig_bone_const(orig, rep, orig_to_rep):
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


def run_retarg_relatives(orig, rep, rep_descendants, orig_to_rep):
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


def _base_body_name_match(ob):
    """True if object looks like the base body mesh (MESH, name has body+base)."""
    if ob.type != "MESH":
        return False
    name_lower = (ob.name + " " + (ob.data.name if ob.data else "")).lower()
    return "body" in name_lower and "base" in name_lower


def _objects_in_collection_recursive(coll):
    """Yield all objects in collection and nested collections."""
    for ob in coll.objects:
        yield ob
    for child in coll.children:
        yield from _objects_in_collection_recursive(child)


def _find_base_body(armature, descendants_iter, rep_base_name=None):
    """Return the base body mesh: in descendants (armature mod), or in armature's collection(s), matched by name."""
    def gather_candidates(ob_iter):
        candidates = []
        for ob in ob_iter:
            if not _base_body_name_match(ob):
                continue
            if ob.modifiers:
                for m in ob.modifiers:
                    if m.type == "ARMATURE" and m.object == armature:
                        return ob, candidates
            candidates.append(ob)
        return None, candidates

    found, candidates = gather_candidates(descendants_iter)
    if found:
        return found
    # Fallback: base body may be in same collection as armature but not parented to it (e.g. linked).
    if not candidates:
        for coll in [collection_containing_armature(armature)] + list(getattr(armature, "users_collection", []) or []):
            if not coll:
                continue
            found, candidates = gather_candidates(_objects_in_collection_recursive(coll))
            if found:
                return found
            if candidates:
                break
    if not candidates:
        return None
    if rep_base_name:
        base = rep_base_name.rsplit(".", 1)[0] if "." in rep_base_name else rep_base_name
        for ob in candidates:
            if ob.name == base or ob.name.startswith(base + ".") or (ob.data and ob.data.name == base):
                return ob
    return candidates[0]


def run_mig_bbody_shapekeys(orig, rep, rep_descendants, context=None):
    """Replacement base body: library override (fully editable when context given), copy shapekey values, then shape-key action."""
    orig_descendants = list(descendants(orig))
    for ob in list(rep_descendants):
        if not _base_body_name_match(ob):
            continue
        if ob.modifiers:
            for m in ob.modifiers:
                if m.type == "ARMATURE" and m.object == rep:
                    break
            else:
                continue
        orig_base = _find_base_body(orig, orig_descendants, rep_base_name=ob.name)
        # Debug: base body mesh state before override handling.
        _lib = getattr(ob.data, "library", None)
        _ol = getattr(ob.data, "override_library", None)
        _sys = getattr(_ol, "is_system_override", None) if _ol else None
        print(f"[DLM step6] {ob.name} data: linked={_lib is not None}, override={_ol is not None}, is_system_override={_sys}")
        # Library override: use hierarchy create (fully editable) when context available, else single-id override.
        if getattr(ob, "library", None):
            if context:
                try:
                    ob = ob.override_hierarchy_create(
                        context.scene, context.view_layer, do_fully_editable=True
                    )
                except Exception:
                    try:
                        ob.override_create()
                    except Exception:
                        pass
            else:
                try:
                    ob.override_create()
                except Exception:
                    pass
        if getattr(ob.data, "library", None):
            try:
                ob.data.override_create(remap_local_usages=True)
                # Make override user-editable (same as shift-click in data tab).
                ol = getattr(ob.data, "override_library", None)
                if ol is not None and getattr(ol, "is_system_override", None) is not None:
                    try:
                        ol.is_system_override = False
                    except Exception as e:
                        print(f"[DLM step6] {ob.name} set is_system_override=False: {e}")
            except Exception as e:
                print(f"[DLM step6] {ob.name} ob.data.override_create: {e}")
        elif getattr(ob.data, "override_library", None):
            ol = ob.data.override_library
            if getattr(ol, "is_system_override", False):
                try:
                    ol.is_system_override = False
                except Exception as e:
                    print(f"[DLM step6] {ob.name} set is_system_override=False: {e}")
        # Debug: state after override handling.
        _ol2 = getattr(ob.data, "override_library", None)
        _sys2 = getattr(_ol2, "is_system_override", None) if _ol2 else None
        print(f"[DLM step6] {ob.name} after: override={_ol2 is not None}, is_system_override={_sys2} (False=editable)")
        if ob.data.shape_keys:
            # Ensure we can write shape key values: override the Key block if it is linked.
            sk = ob.data.shape_keys
            if getattr(sk, "library", None):
                try:
                    sk.override_create(remap_local_usages=True)
                except Exception as e:
                    print(f"[DLM step6] {ob.name} shape_keys.override_create: {e}")
            # Copy shape key values from original base body to replacement (by matching key name).
            if orig_base and orig_base.data.shape_keys:
                rep_blocks = ob.data.shape_keys.key_blocks
                orig_blocks = orig_base.data.shape_keys.key_blocks
                n_copied = 0
                for orig_key in orig_blocks:
                    rep_key = rep_blocks.get(orig_key.name)
                    if rep_key is not None:
                        rep_key.value = orig_key.value
                        n_copied += 1
                print(f"[DLM step6] {ob.name} shapekey values: copied {n_copied}/{len(orig_blocks)} from {orig_base.name}")
            else:
                if not orig_base:
                    print(f"[DLM step6] {ob.name} no orig base body found for armature {orig.name}")
                elif not orig_base.data.shape_keys:
                    print(f"[DLM step6] {ob.name} orig base body has no shape_keys")
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
        run_copy_attr(orig, rep)
        run_mig_nla(orig, rep)
        run_mig_cust_props(orig, rep)
        run_mig_bone_const(orig, rep, orig_to_rep)
        run_retarg_relatives(orig, rep, rep_descendants, orig_to_rep)
        run_mig_bbody_shapekeys(orig, rep, rep_descendants, context)
    except Exception as e:
        return False, str(e)
    return True, f"Migrated {orig.name} → {rep.name}"
