# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

"""Character migrator: migrate animation, constraints, relations from original to replacement armature."""

from contextlib import contextmanager

import bpy

from ..utils import descendants, collection_containing_armature


def _first_view3d_area(context):
    win = getattr(context, "window", None)
    if not win or not getattr(win, "screen", None):
        return None, None
    for area in win.screen.areas:
        if area.type == "VIEW_3D":
            return win, area
    return None, None


@contextmanager
def _rep_active_for_animlayers(context, rep):
    """Make rep the only selected active object in Object mode so Animation Layers (als.turn_on) applies to rep.

    Does not restore the previous selection: Anim Layers and the UI expect rep to stay active after MigNLA.
    """
    if context is None or rep is None:
        yield
        return
    vl = context.view_layer
    win, area = _first_view3d_area(context)
    # Ops need a VIEW_3D context; selection/active still use view_layer.
    if win and area:
        with context.temp_override(window=win, area=area):
            if context.mode != "OBJECT":
                try:
                    bpy.ops.object.mode_set(mode="OBJECT")
                except Exception:
                    pass
            try:
                bpy.ops.object.select_all(action="DESELECT")
            except Exception:
                pass
    else:
        if context.mode != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass
        try:
            bpy.ops.object.select_all(action="DESELECT")
        except Exception:
            pass
    for ob in vl.objects:
        try:
            ob.select_set(False)
        except Exception:
            pass
    try:
        rep.select_set(True)
    except Exception:
        pass
    vl.objects.active = rep
    if bpy.context.view_layer == vl:
        bpy.context.view_layer.objects.active = rep
    yield


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


def _has_als_anywhere(orig):
    """Return True if orig has Animation Layers (addon uses Object.als RNA PropertyGroup, obj.als.turn_on)."""
    # Animation Layers addon: bpy.types.Object.als (RNA), not id props
    if getattr(orig, "als", None) is not None:
        return True
    key = "als.turn_on"
    if key in orig:
        return True
    if getattr(orig, "data", None) and hasattr(orig.data, "keys") and key in orig.data:
        return True
    try:
        als = orig.get("als")
        if als is not None and callable(getattr(als, "keys", None)) and "turn_on" in als.keys():
            return True
    except Exception:
        pass
    for pb in orig.pose.bones:
        if key in pb:
            return True
        try:
            als = pb.get("als")
            if als is not None and callable(getattr(als, "keys", None)) and "turn_on" in als.keys():
                return True
        except Exception:
            pass
    return False


def _debug_als_lookup(orig):
    """Print full debug for AnimLayers: RNA obj.als and every id_prop on orig."""
    key = "als.turn_on"
    print("[DLM MigNLA] === AnimLayers debug ===")
    als_rna = getattr(orig, "als", None)
    print(f"[DLM MigNLA]   orig.als (RNA): {als_rna!r}, turn_on={getattr(als_rna, 'turn_on', 'N/A') if als_rna else 'N/A'}")
    print(f"[DLM MigNLA]   'als.turn_on' in orig (object): {key in orig}")
    if getattr(orig, "data", None):
        has_data_keys = hasattr(orig.data, "keys")
        print(f"[DLM MigNLA]   orig.data has keys(): {has_data_keys}")
        if has_data_keys:
            print(f"[DLM MigNLA]   'als.turn_on' in orig.data: {key in orig.data}")
            print(f"[DLM MigNLA]   orig.data keys: {list(orig.data.keys())}")
    try:
        als = orig.get("als")
        has_als = als is not None and callable(getattr(als, "keys", None))
        print(f"[DLM MigNLA]   orig.get('als') is group: {has_als}")
        if has_als:
            print(f"[DLM MigNLA]   orig['als'] keys: {list(als.keys())}")
            print(f"[DLM MigNLA]   'turn_on' in orig['als']: {'turn_on' in als.keys()}")
    except Exception as e:
        print(f"[DLM MigNLA]   orig.get('als') error: {e}")
    print(f"[DLM MigNLA]   orig (object) all keys: {list(orig.keys())}")
    for k in list(orig.keys()):
        try:
            v = orig[k]
            if callable(getattr(v, "keys", None)):
                print(f"[DLM MigNLA]   orig[{k!r}] (group) keys: {list(v.keys())}")
            else:
                print(f"[DLM MigNLA]   orig[{k!r}] = {v!r}")
        except Exception as e:
            print(f"[DLM MigNLA]   orig[{k!r}] error: {e}")
    # RNA props that might be animation-layer related
    try:
        rna_props = list(orig.bl_rna.properties.keys())
        layer_like = [p for p in rna_props if "layer" in p.lower() or "als" in p.lower() or "turn" in p.lower() or "anim" in p.lower()]
        print(f"[DLM MigNLA]   orig RNA props (layer/als/turn/anim): {layer_like}")
    except Exception as e:
        print(f"[DLM MigNLA]   orig bl_rna.properties error: {e}")
    # Every bone that has keys
    bones_with_keys = []
    for pb in orig.pose.bones:
        if pb.keys():
            bones_with_keys.append((pb.name, list(pb.keys())))
    print(f"[DLM MigNLA]   bones with id_props ({len(bones_with_keys)}): {bones_with_keys[:20]}{'...' if len(bones_with_keys) > 20 else ''}")
    for bname, bkeys in bones_with_keys[:10]:
        pb = orig.pose.bones[bname]
        print(f"[DLM MigNLA]   bone {bname!r}: keys={bkeys}")
        for k in bkeys:
            try:
                v = pb[k]
                if callable(getattr(v, "keys", None)):
                    print(f"[DLM MigNLA]     [{k!r}] (group) keys: {list(v.keys())}")
                else:
                    print(f"[DLM MigNLA]     [{k!r}] = {v!r}")
            except Exception as e:
                print(f"[DLM MigNLA]     [{k!r}] error: {e}")
    print("[DLM MigNLA] === end AnimLayers debug ===")


def _mirror_als_turn_on(orig, rep):
    """Mirror Animation Layers state: obj.als.turn_on (RNA) and id-property fallbacks."""
    # Animation Layers addon: Object.als is RNA PropertyGroup
    orig_als = getattr(orig, "als", None)
    rep_als = getattr(rep, "als", None)
    if orig_als is not None and rep_als is not None:
        try:
            rep_als.turn_on = orig_als.turn_on
        except Exception:
            pass
    key = "als.turn_on"
    if key in orig:
        try:
            rep[key] = orig[key]
        except Exception:
            pass
    try:
        als = orig.get("als")
        if als is not None and callable(getattr(als, "keys", None)) and "turn_on" in als.keys():
            if "als" not in rep:
                rep["als"] = {}
            rep["als"]["turn_on"] = als["turn_on"]
    except Exception:
        pass
    if getattr(orig, "data", None) and hasattr(orig.data, "keys") and key in orig.data:
        try:
            if rep.data is not None and hasattr(rep.data, "keys"):
                rep.data[key] = orig.data[key]
        except Exception:
            pass
    for pbone in orig.pose.bones:
        if pbone.name not in rep.pose.bones:
            continue
        rbone = rep.pose.bones[pbone.name]
        if key in pbone:
            try:
                rbone[key] = pbone[key]
            except Exception:
                pass
        try:
            als = pbone.get("als")
            if als is not None and callable(getattr(als, "keys", None)) and "turn_on" in als.keys():
                if "als" not in rbone:
                    rbone["als"] = {}
                rbone["als"]["turn_on"] = als["turn_on"]
        except Exception:
            pass


def _duplicate_action(src_action, suffix=".rep"):
    """Duplicate an action, returning the new action with a unique name."""
    if src_action is None:
        return None
    new_name = src_action.name
    if not new_name.endswith(suffix):
        new_name = f"{new_name}{suffix}"
    # Ensure unique name
    base_name = new_name
    n = 1
    while new_name in bpy.data.actions:
        new_name = f"{base_name}.{n:03d}"
        n += 1
    new_action = src_action.copy()
    new_action.name = new_name
    return new_action


def run_mig_nla(orig, rep, report=None, context=None):
    """Migrate NLA: copy tracks and strips to replacement; or mirror action slot when no NLA (MigNLA).
    Actions are duplicated so repchar has independent copies.
    Pass context so Animation Layers mirroring runs with rep as active object."""
    if not orig.animation_data:
        return
    ad = orig.animation_data
    has_nla = ad.nla_tracks and len(ad.nla_tracks) > 0
    active_action = getattr(ad, "action", None)
    if not has_nla:
        if rep.animation_data is None:
            rep.animation_data_create()
        rad = rep.animation_data
        # Debug: Orig action slot state (Blender 4.4+ slotted actions).
        def _slot_debug(label, animdata):
            if animdata is None:
                print(f"[DLM MigNLA] {label}: no animation_data")
                return
            a = getattr(animdata, "action", None)
            print(f"[DLM MigNLA] {label} action={a.name if a else None}")
            for p in ("action_slot", "action_slot_handle", "last_slot_identifier",
                      "action_blend_type", "action_extrapolation", "action_influence"):
                if hasattr(animdata, p):
                    v = getattr(animdata, p, None)
                    if hasattr(v, "identifier"):
                        v = getattr(v, "identifier", v)
                    print(f"[DLM MigNLA]   {p}={v!r}")
        _slot_debug("Orig (before)", ad)
        _slot_debug("Rep (before)", rad)
        # Duplicate the active action for repchar
        dup_action = _duplicate_action(active_action, suffix=".rep")
        # Copy last_slot_identifier before action so slot is resolved when assigning (4.4+).
        if hasattr(ad, "last_slot_identifier") and hasattr(rad, "last_slot_identifier") and ad.last_slot_identifier:
            rad.last_slot_identifier = ad.last_slot_identifier
            print(f"[DLM MigNLA] set rep last_slot_identifier={ad.last_slot_identifier!r}")
        rad.action = dup_action
        # Copy Action Slot and related props (Blender 4.4+ slotted actions).
        if getattr(ad, "action_slot", None) and getattr(rad, "action_slot", None):
            try:
                rad.action_slot = ad.action_slot
                print(f"[DLM MigNLA] set rep action_slot={getattr(ad.action_slot, 'identifier', ad.action_slot)!r}")
            except Exception as e:
                print(f"[DLM MigNLA] rad.action_slot assign failed: {e}")
        for prop in ("action_blend_type", "action_extrapolation", "action_influence"):
            if hasattr(ad, prop) and hasattr(rad, prop):
                setattr(rad, prop, getattr(ad, prop))
                print(f"[DLM MigNLA] set rep {prop}={getattr(ad, prop)!r}")
        _slot_debug("Rep (after)", rad)
        with _rep_active_for_animlayers(context, rep):
            _mirror_als_turn_on(orig, rep)
        if report:
            report({"INFO"}, "No NLA detected, active action (duplicated) and slot copied to Replacement Armature.")
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
            dup_action = _duplicate_action(strip.action, suffix=".rep")
            new_strip = new_track.strips.new(
                strip.name, int(strip.frame_start), dup_action
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
    with _rep_active_for_animlayers(context, rep):
        _mirror_als_turn_on(orig, rep)
    if report:
        _debug_als_lookup(orig)
        has_als = _has_als_anywhere(orig)
        print(f"[DLM MigNLA] AnimLayers check: has_als={has_als}")
        if has_als:
            report({"INFO"}, "NLA layers detected, Animation Layer attributes migrated to Replacement Armature.")
        else:
            report({"INFO"}, "NLA layers detected and migrated. No Animation Layers found.")


EXCLUDE_PROPS = {"_RNA_UI", "rigify_type", "rigify_parameters"}


def _is_id_prop_group(val):
    """True if val is an ID property group (nested dict-like), not a leaf or string."""
    if val is None or isinstance(val, (str, bytes)):
        return False
    return callable(getattr(val, "keys", None))


def _copy_id_prop_recursive(orig_container, rep_container, key, debug_path="", debug=False):
    """Copy one id property from orig_container[key] into rep_container[key] (recursive for groups)."""
    if key not in orig_container:
        return
    orig_val = orig_container[key]
    try:
        if _is_id_prop_group(orig_val):
            if key not in rep_container:
                rep_container[key] = {}
            rep_group = rep_container[key]
            for k in list(orig_val.keys()):
                _copy_id_prop_recursive(orig_val, rep_group, k, f"{debug_path}.{key}", debug)
            if debug:
                print(f"[DLM MigCustProps] group {debug_path}.{key!r}: copied {len(orig_val.keys())} sub-keys")
        else:
            rep_container[key] = orig_val
            if debug:
                print(f"[DLM MigCustProps] leaf {debug_path}.{key!r} = {orig_val!r}")
    except Exception as e:
        print(f"[DLM MigCustProps] FAILED {debug_path}.{key!r}: {e}")


def _copy_custom_props_from(orig_obj, rep_obj, debug_label="", debug=False):
    """Copy all custom props from orig_obj to rep_obj (object or pose bone), including nested groups."""
    keys = [k for k in orig_obj.keys() if k not in EXCLUDE_PROPS]
    if debug and keys:
        print(f"[DLM MigCustProps] {debug_label} keys: {keys}")
    for key in keys:
        _copy_id_prop_recursive(orig_obj, rep_obj, key, debug_label, debug)


def run_mig_cust_props(orig, rep):
    """Custom properties: copy overridden settings (ID props only, incl. nested e.g. Settings/Devices) from orig to rep."""
    debug = True
    print(f"[DLM MigCustProps] orig={orig.name!r} rep={rep.name!r}")
    # Armature object
    o_keys = list(orig.keys())
    print(f"[DLM MigCustProps] armature orig keys (all): {o_keys}")
    _copy_custom_props_from(orig, rep, f"obj:{orig.name}", debug)
    # Bones with any id props
    bones_with_keys = [(pb.name, list(pb.keys())) for pb in orig.pose.bones if pb.keys()]
    print(f"[DLM MigCustProps] bones with id_props: {bones_with_keys}")
    for pbone in orig.pose.bones:
        if pbone.name not in rep.pose.bones:
            continue
        rbone = rep.pose.bones[pbone.name]
        _copy_custom_props_from(pbone, rbone, f"bone:{pbone.name}", debug)
    # After: rep armature and Settings bone if present
    print(f"[DLM MigCustProps] rep armature keys after: {list(rep.keys())}")
    if "Settings" in rep.pose.bones:
        sb = rep.pose.bones["Settings"]
        print(f"[DLM MigCustProps] rep bone Settings keys after: {list(sb.keys())}")
        if sb.keys():
            for k in sb.keys():
                v = sb[k]
                if _is_id_prop_group(v):
                    print(f"[DLM MigCustProps]   Settings[{k!r}] (group) keys: {list(v.keys())}")
                else:
                    print(f"[DLM MigCustProps]   Settings[{k!r}] = {v!r}")


def _retarget_id(ob, orig, rep, orig_to_rep):
    """Return rep, orig_to_rep[ob], or ob so constraint targets point to replacement when appropriate."""
    if ob is None:
        return None
    if ob == orig:
        return rep
    return orig_to_rep.get(ob, ob)


def _copy_constraint_props(c, nc, orig, rep, orig_to_rep):
    """Copy all copyable RNA properties from c to nc, retargeting object/armature pointers."""
    for rna_prop in c.bl_rna.properties:
        if rna_prop.is_readonly or rna_prop.identifier in ("name", "type"):
            continue
        if not hasattr(nc, rna_prop.identifier):
            continue
        try:
            val = getattr(c, rna_prop.identifier)
        except Exception:
            continue
        rna_type = getattr(rna_prop, "type", None)
        if rna_type == "POINTER":
            setattr(nc, rna_prop.identifier, _retarget_id(val, orig, rep, orig_to_rep))
        elif rna_type == "COLLECTION":
            # e.g. ArmatureConstraint.targets: ensure count then copy item props (target, subtarget, weight)
            try:
                dst_coll = getattr(nc, rna_prop.identifier)
                src_coll = getattr(c, rna_prop.identifier)
                add_fn = getattr(dst_coll, "add", None) or getattr(dst_coll, "new", None)
                for i in range(len(src_coll)):
                    if i >= len(dst_coll) and add_fn:
                        add_fn()
                for i, src_item in enumerate(src_coll):
                    if i >= len(dst_coll):
                        break
                    dst_item = dst_coll[i]
                    for p in dst_item.bl_rna.properties:
                        if p.is_readonly or p.identifier == "name":
                            continue
                        if not hasattr(dst_item, p.identifier):
                            continue
                        try:
                            v = getattr(src_item, p.identifier)
                            if getattr(p, "type", None) == "POINTER":
                                v = _retarget_id(v, orig, rep, orig_to_rep)
                            setattr(dst_item, p.identifier, v)
                        except Exception:
                            pass
            except Exception:
                pass
        else:
            try:
                setattr(nc, rna_prop.identifier, val)
            except Exception:
                pass


def run_mig_bone_const(orig, rep, orig_to_rep):
    """Bone constraints: remove stale on rep, copy from orig with full props (targets, etc.) and retarget, trim duplicates."""
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
            nc = rbone.constraints.new(type=c.type)
            nc.name = c.name
            _copy_constraint_props(c, nc, orig, rep, orig_to_rep)
    for pb in orig.pose.bones:
        if pb.name not in rep.pose.bones:
            continue
        ro, rr = pb.constraints, rep.pose.bones[pb.name].constraints
        while len(rr) > len(ro):
            rr.remove(rr[-1])


def run_retarg_relatives(orig, rep, rep_descendants, orig_to_rep):
    """Retarget relations: parents, constraint targets, Armature modifiers to rep. Skip objects in orig's hierarchy (linked collection)."""
    # Replicate orig's parent on rep if it exists (keep world transform)
    if orig.parent is not None:
        # Store world matrix before reparenting
        world_matrix = rep.matrix_world.copy()
        rep.parent = orig.parent
        rep.parent_type = orig.parent_type
        rep.parent_bone = orig.parent_bone
        # Restore world matrix
        rep.matrix_world = world_matrix

    orig_hierarchy = {orig} | descendants(orig)
    candidates = set(rep_descendants)
    for ob in bpy.data.objects:
        if getattr(ob.parent, "name", None) == orig.name:
            candidates.add(ob)
        for c in getattr(ob, "constraints", []):
            if getattr(c, "target", None) == orig:
                candidates.add(ob)
    candidates -= orig_hierarchy
    for ob in candidates:
        if ob.parent == orig:
            ob.parent = rep
        if ob.type == "MESH" and ob.modifiers:
            for m in ob.modifiers:
                if getattr(m, "object", None) == orig:
                    m.object = rep

    # Retarget constraints on ALL objects (including orig hierarchy like eyes)
    for ob in bpy.data.objects:
        for c in getattr(ob, "constraints", []):
            if getattr(c, "target", None) == orig:
                c.target = rep

    # Retarget bone constraints on ALL armatures (other characters, etc.)
    for ob in bpy.data.objects:
        if ob.type != "ARMATURE" or not ob.pose:
            continue
        for pbone in ob.pose.bones:
            for c in pbone.constraints:
                if getattr(c, "target", None) == orig:
                    c.target = rep

    # Camera DOF: retarget focus_object from orig to rep
    for ob in bpy.data.objects:
        if ob.type != 'CAMERA':
            continue
        camera = ob.data
        if not camera.dof:
            continue
        if camera.dof.focus_object == orig:
            camera.dof.focus_object = rep


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
            sk_ad = ob.data.shape_keys.animation_data
            # Prefer action (and slot) from original base body; fallback to name lookup.
            orig_sk_ad = None
            if orig_base and orig_base.data.shape_keys:
                orig_sk_ad = orig_base.data.shape_keys.animation_data
            action = None
            if orig_sk_ad and getattr(orig_sk_ad, "action", None):
                action = orig_sk_ad.action
            if action is None:
                body_name = ob.name
                action = (
                    bpy.data.actions.get(body_name + "Action")
                    or bpy.data.actions.get(ob.data.name + "Action")
                    or bpy.data.actions.get(body_name + "Action.001")
                )
            if action:
                # Duplicate action so repchar has independent copy
                dup_action = _duplicate_action(action, suffix=".rep")
                # Copy slot-related props before action so slot is applied (Blender 4.4+).
                if orig_sk_ad and hasattr(sk_ad, "last_slot_identifier") and hasattr(orig_sk_ad, "last_slot_identifier") and orig_sk_ad.last_slot_identifier:
                    sk_ad.last_slot_identifier = orig_sk_ad.last_slot_identifier
                sk_ad.action = dup_action
                if orig_sk_ad and getattr(orig_sk_ad, "action_slot", None) and getattr(sk_ad, "action_slot", None):
                    try:
                        sk_ad.action_slot = orig_sk_ad.action_slot
                    except Exception:
                        pass
                for prop in ("action_blend_type", "action_extrapolation", "action_influence"):
                    if orig_sk_ad and hasattr(orig_sk_ad, prop) and hasattr(sk_ad, prop):
                        try:
                            setattr(sk_ad, prop, getattr(orig_sk_ad, prop))
                        except Exception:
                            pass


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
        run_mig_nla(orig, rep, context=context)
        run_mig_cust_props(orig, rep)
        run_mig_bone_const(orig, rep, orig_to_rep)
        run_retarg_relatives(orig, rep, rep_descendants, orig_to_rep)
        run_mig_bbody_shapekeys(orig, rep, rep_descendants, context)
    except Exception as e:
        return False, str(e)
    return True, f"Migrated {orig.name} → {rep.name}"
