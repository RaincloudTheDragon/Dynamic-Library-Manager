# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

"""Character migrator: migrate animation, constraints, relations from original to replacement armature."""

from contextlib import contextmanager
import re

import bpy

from ..utils import descendants, collection_containing_armature
from ..utils.remap_usages import remap_object_usages
from .fk_rotations import _iter_action_fcurves

# pose.bones["Name"].location / rotation_* / scale
_POSE_CHANNEL_RE = re.compile(r'^pose\.bones\["([^"]+)"\]\.(\w+)')


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
    props = getattr(context.scene, "dynamic_library_manager", None)
    if not props:
        return None, None
    orig = getattr(props, "original_character", None)
    rep = getattr(props, "replacement_character", None)
    if orig and orig.type == "ARMATURE" and rep and rep.type == "ARMATURE":
        return orig, rep
    return None, None


def get_prop_pair(context):
    """Return (orig_prop, rep_prop) non-armature objects from scene props, or (None, None)."""
    props = getattr(context.scene, "dynamic_library_manager", None)
    if not props:
        return None, None
    orig = getattr(props, "original_prop", None)
    rep = getattr(props, "replacement_prop", None)
    if (
        orig
        and orig.type != "ARMATURE"
        and rep
        and rep.type != "ARMATURE"
        and orig != rep
    ):
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
    if orig.type == "ARMATURE" and getattr(orig, "pose", None):
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
    # Every bone that has keys (armatures only)
    if orig.type == "ARMATURE" and getattr(orig, "pose", None):
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
    # Animation Layers addon: Object.als is RNA PropertyGroup.
    # Only write when the value changes — assigning False→False still runs ALS
    # handlers that stash strip actions as active and disable use_nla (#1).
    orig_als = getattr(orig, "als", None)
    rep_als = getattr(rep, "als", None)
    if orig_als is not None and rep_als is not None:
        try:
            if rep_als.turn_on != orig_als.turn_on:
                rep_als.turn_on = orig_als.turn_on
        except Exception:
            pass
    key = "als.turn_on"
    if key in orig:
        try:
            if key not in rep or rep[key] != orig[key]:
                rep[key] = orig[key]
        except Exception:
            pass
    try:
        als = orig.get("als")
        if als is not None and callable(getattr(als, "keys", None)) and "turn_on" in als.keys():
            if "als" not in rep:
                rep["als"] = {}
            if "turn_on" not in rep["als"] or rep["als"]["turn_on"] != als["turn_on"]:
                rep["als"]["turn_on"] = als["turn_on"]
    except Exception:
        pass
    if getattr(orig, "data", None) and hasattr(orig.data, "keys") and key in orig.data:
        try:
            if rep.data is not None and hasattr(rep.data, "keys"):
                if key not in rep.data or rep.data[key] != orig.data[key]:
                    rep.data[key] = orig.data[key]
        except Exception:
            pass
    if orig.type != "ARMATURE" or not getattr(orig, "pose", None) or not getattr(rep, "pose", None):
        return
    for pbone in orig.pose.bones:
        if pbone.name not in rep.pose.bones:
            continue
        rbone = rep.pose.bones[pbone.name]
        if key in pbone:
            try:
                if key not in rbone or rbone[key] != pbone[key]:
                    rbone[key] = pbone[key]
            except Exception:
                pass
        try:
            als = pbone.get("als")
            if als is not None and callable(getattr(als, "keys", None)) and "turn_on" in als.keys():
                if "als" not in rbone:
                    rbone["als"] = {}
                if "turn_on" not in rbone["als"] or rbone["als"]["turn_on"] != als["turn_on"]:
                    rbone["als"]["turn_on"] = als["turn_on"]
        except Exception:
            pass

def _activate_topmost_als(context, orig, rep):
    """Select the topmost Animation Layers track on orig and rep after MigNLA."""
    from ..utils.nla_bake import activate_topmost_nla
    if context is None:
        context = bpy.context
    activate_topmost_nla(context, orig, log_prefix="[DLM MigNLA]")
    activate_topmost_nla(context, rep, log_prefix="[DLM MigNLA]")


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


def _slot_identifier(slot):
    """Stable string id for an ActionSlot (Blender 4.4+)."""
    if slot is None:
        return None
    return (
        getattr(slot, "identifier", None)
        or getattr(slot, "name_display", None)
        or getattr(slot, "name", None)
    )


def _find_action_slot(action, identifier):
    """Find a slot on action matching identifier; if only one slot exists, use it."""
    if not action or not hasattr(action, "slots"):
        return None
    slots = action.slots
    if not slots:
        return None
    if identifier:
        for slot in slots:
            for attr in ("identifier", "name_display", "name"):
                if getattr(slot, attr, None) == identifier:
                    return slot
    if len(slots) == 1:
        return slots[0]
    return None


def _copy_action_slot(src_owner, dst_owner, dst_action, log_prefix="[DLM MigNLA]"):
    """
    Assign dst_owner.action_slot to the slot on dst_action that matches src_owner.

    Slots are owned by their Action; copying ``src.action_slot`` directly onto a
    duplicated action fails or leaves None. Match by identifier instead (1:1).
    Works for AnimData and NlaStrip.
    """
    if dst_owner is None or dst_action is None or not hasattr(dst_owner, "action_slot"):
        return False

    src_slot = getattr(src_owner, "action_slot", None) if src_owner else None
    ident = _slot_identifier(src_slot)
    if not ident and src_owner is not None and hasattr(src_owner, "last_slot_identifier"):
        ident = src_owner.last_slot_identifier or None

    if ident and hasattr(dst_owner, "last_slot_identifier"):
        try:
            dst_owner.last_slot_identifier = ident
        except Exception as e:
            print(f"{log_prefix} last_slot_identifier assign failed: {e}")

    slot = _find_action_slot(dst_action, ident)
    if slot is None:
        print(
            f"{log_prefix} no matching slot for identifier={ident!r} "
            f"on action={dst_action.name!r} "
            f"(slots={[ _slot_identifier(s) for s in getattr(dst_action, 'slots', []) ]})"
        )
        return False

    try:
        dst_owner.action_slot = slot
        print(f"{log_prefix} set action_slot={_slot_identifier(slot)!r} on {type(dst_owner).__name__}")
        return True
    except Exception as e:
        print(f"{log_prefix} action_slot assign failed: {e}")
        return False


def _collect_orig_actions(orig):
    """Active action + all NLA strip actions on orig (unique, ordered)."""
    actions = []
    seen = set()
    ad = getattr(orig, "animation_data", None)
    if not ad:
        return actions
    for action in [getattr(ad, "action", None)] + [
        strip.action
        for track in (ad.nla_tracks or [])
        for strip in track.strips
        if getattr(strip, "action", None)
    ]:
        if action is None or id(action) in seen:
            continue
        seen.add(id(action))
        actions.append(action)
    return actions


def _keyed_channels_by_bone(orig):
    """Map bone_name -> {kind: set(array_index)} for location / rotation / scale.

    Partial keys matter: e.g. root.location X/Y keyed but Z static must still copy Z.
    """
    keyed = {}
    for action in _collect_orig_actions(orig):
        for fc in _iter_action_fcurves(action):
            path = getattr(fc, "data_path", "") or ""
            m = _POSE_CHANNEL_RE.match(path)
            if not m:
                continue
            bone, prop = m.group(1), m.group(2)
            if prop == "location":
                kind = "location"
            elif prop.startswith("rotation"):
                kind = "rotation"
            elif prop == "scale":
                kind = "scale"
            else:
                continue
            keyed.setdefault(bone, {}).setdefault(kind, set()).add(int(getattr(fc, "array_index", 0) or 0))
    return keyed


def _axis_count(kind, rotation_mode="QUATERNION"):
    if kind in ("location", "scale"):
        return 3
    if rotation_mode == "QUATERNION":
        return 4
    if rotation_mode == "AXIS_ANGLE":
        return 4
    return 3


def _copy_vector_unkeyed(src_vec, dst_vec, keyed_indices, n_axes):
    """Copy per-axis values that are not in keyed_indices. Returns count copied."""
    n = 0
    keyed_indices = keyed_indices or set()
    for i in range(n_axes):
        if i in keyed_indices:
            continue
        dst_vec[i] = src_vec[i]
        n += 1
    return n


def _copy_pose_bone_channels(src, dst, keyed_kinds=None):
    """Copy local loc/rot/scale from src→dst for axes without keys.

    keyed_kinds: {kind: set(array_index)} from ``_keyed_channels_by_bone``.
    """
    keyed_kinds = keyed_kinds or {}
    n = 0
    n += _copy_vector_unkeyed(
        src.location, dst.location, keyed_kinds.get("location"), 3
    )
    n += _copy_vector_unkeyed(src.scale, dst.scale, keyed_kinds.get("scale"), 3)
    rot_keyed = keyed_kinds.get("rotation")
    # Match dst rotation mode to src before writing components.
    if rot_keyed is None or len(rot_keyed) < _axis_count("rotation", src.rotation_mode):
        dst.rotation_mode = src.rotation_mode
    if src.rotation_mode == "QUATERNION":
        n += _copy_vector_unkeyed(
            src.rotation_quaternion, dst.rotation_quaternion, rot_keyed, 4
        )
    elif src.rotation_mode == "AXIS_ANGLE":
        n += _copy_vector_unkeyed(
            src.rotation_axis_angle, dst.rotation_axis_angle, rot_keyed, 4
        )
    else:
        n += _copy_vector_unkeyed(src.rotation_euler, dst.rotation_euler, rot_keyed, 3)
    return n


def _keyed_object_channels(obj):
    """Map kind -> set(array_index) for object location / rotation / scale."""
    keyed = {}
    for action in _collect_orig_actions(obj):
        for fc in _iter_action_fcurves(action):
            path = getattr(fc, "data_path", "") or ""
            if path.startswith("pose.bones"):
                continue
            base = path.split("[", 1)[0]
            if base == "location":
                kind = "location"
            elif base.startswith("rotation"):
                kind = "rotation"
            elif base == "scale":
                kind = "scale"
            else:
                continue
            keyed.setdefault(kind, set()).add(int(getattr(fc, "array_index", 0) or 0))
    return keyed


def _copy_unkeyed_object_transform(orig, rep):
    """Copy orig→rep object loc/rot/scale for axes without keys."""
    if not orig or not rep:
        return 0
    keyed = _keyed_object_channels(orig)
    n = 0
    n += _copy_vector_unkeyed(orig.location, rep.location, keyed.get("location"), 3)
    n += _copy_vector_unkeyed(orig.scale, rep.scale, keyed.get("scale"), 3)
    rot_keyed = keyed.get("rotation")
    if rot_keyed is None or len(rot_keyed) < _axis_count("rotation", orig.rotation_mode):
        rep.rotation_mode = orig.rotation_mode
    if orig.rotation_mode == "QUATERNION":
        n += _copy_vector_unkeyed(
            orig.rotation_quaternion, rep.rotation_quaternion, rot_keyed, 4
        )
    elif orig.rotation_mode == "AXIS_ANGLE":
        n += _copy_vector_unkeyed(
            orig.rotation_axis_angle, rep.rotation_axis_angle, rot_keyed, 4
        )
    else:
        n += _copy_vector_unkeyed(orig.rotation_euler, rep.rotation_euler, rot_keyed, 3)
    print(f"[DLM MigNLA] copied unkeyed object axes={n} (keyed={ {k: sorted(v) for k, v in keyed.items()} })")
    return n


def _copy_unkeyed_pose(orig, rep):
    """Copy orig→rep local pose for axes without keys (full pose if no action).

    Action'd bones keep their keyed axes; unkeyed axes (e.g. root.location.z when
    only X/Y are keyed) get the current pose from orig. No-op for non-armatures.
    """
    if not orig or not rep or not getattr(orig, "pose", None) or not getattr(rep, "pose", None):
        return 0
    keyed = _keyed_channels_by_bone(orig)
    n_bones = 0
    n_axes = 0
    for pb in orig.pose.bones:
        rb = rep.pose.bones.get(pb.name)
        if rb is None:
            continue
        bone_keyed = keyed.get(pb.name, {})
        # Skip bone only if every transform axis is keyed.
        fully = True
        for kind, mode_axes in (
            ("location", 3),
            ("scale", 3),
            ("rotation", _axis_count("rotation", pb.rotation_mode)),
        ):
            idxs = bone_keyed.get(kind)
            if idxs is None or len(idxs) < mode_axes:
                fully = False
                break
        if fully:
            continue
        copied = _copy_pose_bone_channels(pb, rb, bone_keyed)
        if copied:
            n_bones += 1
            n_axes += copied
    print(
        f"[DLM MigNLA] copied unkeyed pose on {n_bones} bone(s), {n_axes} axes "
        f"(keyed bones={len(keyed)})"
    )
    return n_bones


def _copy_unkeyed_transforms(orig, rep):
    """Copy unkeyed object transform + (if armature) unkeyed pose. Returns (obj_n, bone_n)."""
    return _copy_unkeyed_object_transform(orig, rep), _copy_unkeyed_pose(orig, rep)

def run_mig_nla(orig, rep, report=None, context=None):
    """Migrate NLA: copy tracks and strips to replacement; or mirror action slot when no NLA (MigNLA).
    Actions are duplicated so repchar has independent copies.
    Always copies unkeyed pose (loc/rot/scale) from orig→rep, with or without an action.
    Pass context so Animation Layers mirroring runs with rep as active object."""
    if not orig.animation_data:
        obj_n, bone_n = _copy_unkeyed_transforms(orig, rep)
        if report:
            report(
                {"INFO"},
                f"No animation_data; unkeyed object channels={obj_n}, bones={bone_n}.",
            )
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
            if a is not None and hasattr(a, "slots"):
                print(f"[DLM MigNLA]   action.slots={[ _slot_identifier(s) for s in a.slots ]}")
        _slot_debug("Orig (before)", ad)
        _slot_debug("Rep (before)", rad)
        # Duplicate the active action for repchar
        dup_action = _duplicate_action(active_action, suffix=".rep")
        # Prefer last_slot_identifier before action so Blender can resolve the slot.
        if hasattr(ad, "last_slot_identifier") and hasattr(rad, "last_slot_identifier") and ad.last_slot_identifier:
            try:
                rad.last_slot_identifier = ad.last_slot_identifier
                print(f"[DLM MigNLA] set rep last_slot_identifier={ad.last_slot_identifier!r}")
            except Exception as e:
                print(f"[DLM MigNLA] last_slot_identifier assign failed: {e}")
        rad.action = dup_action
        # Bind the duplicated action's own matching slot (not orig's slot pointer).
        _copy_action_slot(ad, rad, dup_action)
        for prop in ("action_blend_type", "action_extrapolation", "action_influence"):
            if hasattr(ad, prop) and hasattr(rad, prop):
                setattr(rad, prop, getattr(ad, prop))
                print(f"[DLM MigNLA] set rep {prop}={getattr(ad, prop)!r}")
        _slot_debug("Rep (after)", rad)
        with _rep_active_for_animlayers(context, rep):
            _mirror_als_turn_on(orig, rep)
            _activate_topmost_als(context, orig, rep)
        obj_n, bone_n = _copy_unkeyed_transforms(orig, rep)
        if report:
            if active_action:
                report(
                    {"INFO"},
                    f"No NLA; action+slot copied; unkeyed obj={obj_n} bones={bone_n}.",
                )
            else:
                report(
                    {"INFO"},
                    f"No NLA/action; unkeyed obj={obj_n} bones={bone_n}.",
                )
        return
    if rep.animation_data is None:
        rep.animation_data_create()
    rep_tracks = rep.animation_data.nla_tracks
    existing_names = {t.name for t in rep_tracks}
    prev_track = rep_tracks[-1] if rep_tracks else None
    action_map = {}  # orig action -> duplicated .rep action (1:1 reuse)
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
            dup_action = action_map.get(strip.action)
            if dup_action is None:
                dup_action = _duplicate_action(strip.action, suffix=".rep")
                action_map[strip.action] = dup_action
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
            # Strip action_slot must point at a slot on the duplicated action.
            _copy_action_slot(strip, new_strip, dup_action)
        prev_track = new_track

    # Active action vs NLA: tweak mode exposes the strip action as ad.action.
    # Promoting that to a permanent rep.action evaluates without strip offset (#1).
    # Only mirror a true upper Action when it is not already an NLA strip action.
    rad = rep.animation_data
    in_tweak = bool(getattr(ad, "use_tweak_mode", False))
    if in_tweak:
        true_active = getattr(ad, "action_tweak_storage", None)
    else:
        true_active = active_action
    # Strip actions already live in action_map; a separate active action does not.
    mirror_active = true_active is not None and true_active not in action_map

    if hasattr(ad, "use_nla") and hasattr(rad, "use_nla"):
        # Outside tweak, trust orig; in tweak the stack is still the real driver.
        rad.use_nla = True if in_tweak else bool(ad.use_nla)

    if mirror_active:
        dup_active = action_map.get(true_active)
        created_dup = False
        if dup_active is None:
            dup_active = _duplicate_action(true_active, suffix=".rep")
            created_dup = True
        if hasattr(ad, "last_slot_identifier") and hasattr(rad, "last_slot_identifier") and ad.last_slot_identifier:
            try:
                rad.last_slot_identifier = ad.last_slot_identifier
            except Exception:
                pass
        try:
            if not rad.is_property_readonly("action"):
                rad.action = dup_active
                _copy_action_slot(ad, rad, dup_active)
                for prop in ("action_blend_type", "action_extrapolation", "action_influence"):
                    if hasattr(ad, prop) and hasattr(rad, prop):
                        setattr(rad, prop, getattr(ad, prop))
                print(f"[DLM MigNLA] mirrored non-strip active action -> {dup_active.name if dup_active else None}")
            else:
                print("[DLM MigNLA] rep.action is read-only (ALS); strip slots already copied")
                if created_dup and dup_active and dup_active.users == 0:
                    try:
                        bpy.data.actions.remove(dup_active)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[DLM MigNLA] active action mirror skipped: {e}")
    else:
        # Match manual fix for #1: no stale active action; evaluate offset strips via NLA.
        try:
            if getattr(rad, "use_tweak_mode", False):
                try:
                    rad.use_tweak_mode = False
                except Exception:
                    pass
            if not rad.is_property_readonly("action"):
                rad.action = None
                print("[DLM MigNLA] cleared rep.action so offset NLA strips evaluate")
            else:
                print("[DLM MigNLA] rep.action read-only; left NLA strips as evaluation source")
        except Exception as e:
            print(f"[DLM MigNLA] clear rep.action skipped: {e}")
        if hasattr(rad, "use_nla"):
            rad.use_nla = True

    with _rep_active_for_animlayers(context, rep):
        _mirror_als_turn_on(orig, rep)
        _activate_topmost_als(context, orig, rep)
        # AnimLayers handlers run on als.turn_on assign even when False: they
        # stash the strip action as active and set use_nla=False. Undo that when
        # ALS is not actually on so offset strips evaluate (#1). When ALS is on,
        # tweak-mode evaluation already applies strip offset — leave it.
        from ..utils.nla_bake import als_on
        if not als_on(rep) and not mirror_active:
            try:
                if getattr(rad, "use_tweak_mode", False):
                    try:
                        rad.use_tweak_mode = False
                    except Exception:
                        pass
                if not rad.is_property_readonly("action") and rad.action is not None:
                    rad.action = None
                    print("[DLM MigNLA] re-cleared rep.action after ALS mirror (ALS off)")
                if hasattr(rad, "use_nla"):
                    rad.use_nla = True
            except Exception as e:
                print(f"[DLM MigNLA] post-ALS NLA restore skipped: {e}")
    obj_n, bone_n = _copy_unkeyed_transforms(orig, rep)
    if report:
        _debug_als_lookup(orig)
        has_als = _has_als_anywhere(orig)
        print(f"[DLM MigNLA] AnimLayers check: has_als={has_als}")
        if has_als:
            report(
                {"INFO"},
                f"NLA + Animation Layers migrated; unkeyed obj={obj_n} bones={bone_n}.",
            )
        else:
            report(
                {"INFO"},
                f"NLA migrated; unkeyed obj={obj_n} bones={bone_n}.",
            )

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
    o_keys = list(orig.keys())
    print(f"[DLM MigCustProps] object orig keys (all): {o_keys}")
    _copy_custom_props_from(orig, rep, f"obj:{orig.name}", debug)
    # Bones with any id props (armatures only)
    if orig.type == "ARMATURE" and getattr(orig, "pose", None) and getattr(rep, "pose", None):
        bones_with_keys = [(pb.name, list(pb.keys())) for pb in orig.pose.bones if pb.keys()]
        print(f"[DLM MigCustProps] bones with id_props: {bones_with_keys}")
        for pbone in orig.pose.bones:
            if pbone.name not in rep.pose.bones:
                continue
            rbone = rep.pose.bones[pbone.name]
            _copy_custom_props_from(pbone, rbone, f"bone:{pbone.name}", debug)
        print(f"[DLM MigCustProps] rep object keys after: {list(rep.keys())}")
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
    else:
        print(f"[DLM MigCustProps] rep object keys after: {list(rep.keys())}")


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


def run_mig_obj_const(orig, rep, orig_to_rep):
    """Object constraints only: copy Follow Path / Copy Location / etc. on the armature.

    Constraint names are preserved so MigNLA fcurves (offset_factor, influence) keep binding.
    Parent / path-empty relations are MigObjRelatives.
    """
    other_originals = [o for o in orig_to_rep if o != orig]
    to_remove = [c for c in rep.constraints if getattr(c, "target", None) in other_originals]
    for c in to_remove:
        rep.constraints.remove(c)

    for c in orig.constraints:
        nc = rep.constraints.new(type=c.type)
        nc.name = c.name
        _copy_constraint_props(c, nc, orig, rep, orig_to_rep)

    while len(rep.constraints) > len(orig.constraints):
        rep.constraints.remove(rep.constraints[-1])

    print(
        f"[DLM MigObjConst] {orig.name!r}->{rep.name!r}: "
        f"{len(orig.constraints)} object constraint(s)"
    )


def resolve_migration_pair(orig, rep, scene=None):
    """Resolve orig/rep armatures; consolidate ghost duplicates onto canonical override."""
    from ..utils.remap_usages import consolidate_migration_armature, resolve_migration_armature

    scene = scene or bpy.context.scene
    if rep is not None:
        ghost = rep
        rep = resolve_migration_armature(rep, scene)
        if ghost != rep:
            rep = consolidate_migration_armature(ghost, rep, scene)
    return orig, rep


def run_mig_obj_relatives(orig, rep, orig_to_rep, scene=None):
    """Object relatives: copy armature object parenting (e.g. ride cart/path empty).

    Preserves orig's world transform. Override armatures parented outside their
    asset hierarchy (path cart, scene empty) use a Child Of constraint instead
    of object parenting so override data survives save/reload.
    """
    from ..utils.remap_usages import object_in_collection_tree, override_root_collection

    scene = scene or bpy.context.scene
    _, rep = resolve_migration_pair(orig, rep, scene)

    if orig.parent is None:
        print(f"[DLM MigObjRelatives] {orig.name!r}->{rep.name!r}: no parent")
        return rep

    world_matrix = orig.matrix_world.copy()
    new_parent = _retarget_id(orig.parent, orig, rep, orig_to_rep)
    rep_root = override_root_collection(rep, scene)
    use_child_of = (
        rep_root is not None
        and getattr(rep, "override_library", None) is not None
        and not object_in_collection_tree(new_parent, rep_root)
    )

    # Blender parenting: world = parent @ matrix_parent_inverse @ matrix_basis.
    # Child Of uses the same product when inverse_matrix == matrix_parent_inverse.
    # Using parent^-1 + matrix_world snap looks right for one depsgraph update, then
    # keyed location channels restore parent-local basis and the character flips back.
    try:
        parent_inverse = orig.matrix_parent_inverse.copy()
        basis = orig.matrix_basis.copy()
    except Exception:
        parent_inverse = None
        basis = None

    if use_child_of:
        if rep.parent is not None:
            rep.parent = None
        for c in list(rep.constraints):
            if c.type == "CHILD_OF" and getattr(c, "target", None) == new_parent:
                rep.constraints.remove(c)
        nc = rep.constraints.new(type="CHILD_OF")
        nc.target = new_parent
        nc.name = orig.parent.name if orig.parent else "Child Of"
        if orig.parent_type == "BONE" and orig.parent_bone:
            nc.subtarget = orig.parent_bone
        nc.influence = 1.0
        if parent_inverse is not None and new_parent == orig.parent:
            nc.inverse_matrix = parent_inverse
        elif basis is not None:
            # Retargeted parent: keep orig world with the same keyed basis.
            nc.inverse_matrix = (
                new_parent.matrix_world.inverted() @ world_matrix @ basis.inverted()
            )
        else:
            nc.inverse_matrix = new_parent.matrix_world.inverted()
        if basis is not None:
            rep.matrix_basis = basis
        else:
            rep.matrix_world = world_matrix
        print(
            f"[DLM MigObjRelatives] {orig.name!r}->{rep.name!r}: "
            f"Child Of {new_parent.name!r} (override-safe)"
        )
        return rep

    rep.parent = new_parent
    rep.parent_type = orig.parent_type
    rep.parent_bone = orig.parent_bone
    try:
        if parent_inverse is not None:
            rep.matrix_parent_inverse = parent_inverse
        if basis is not None:
            rep.matrix_basis = basis
        else:
            rep.matrix_world = world_matrix
    except Exception:
        try:
            rep.matrix_parent_inverse = orig.matrix_parent_inverse.copy()
            rep.matrix_basis = orig.matrix_basis.copy()
        except Exception:
            rep.location = orig.location.copy()
            rep.rotation_euler = orig.rotation_euler.copy()
            rep.scale = orig.scale.copy()

    print(
        f"[DLM MigObjRelatives] {orig.name!r}->{rep.name!r}: "
        f"parent={new_parent.name!r}"
    )
    return rep


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
    """Retarget relations: parents, constraint/driver/DOF targets, modifiers to rep.

    Builds a name map across orig/rep override collections (GEO meshes, etc.), not
    only the armature, so scene refs to GEO-GOCART remap to the replacement GEO.

    External children parented to orig (e.g. RIG-Pallet-Jack) are reparented to rep.
    Objects inside orig's own override collection are left alone — they die with
    Remove Original.

    Skips orig's own Rigify bone constraints and orig's self-drivers so orig
    does not snap to rep. Object constraints on orig's children (eyes) still remap.
    """
    from ..utils.remap_usages import (
        build_override_collection_object_map,
        override_root_collection,
        reparent_preserve_world_path,
        sync_prop_rep_from_orig,
    )

    # Full asset-instance map: RIG + GEO + Jiffy/helpers under the override root.
    collection_map = build_override_collection_object_map(orig, rep)
    mapping = {}
    if orig_to_rep:
        mapping.update(orig_to_rep)
    mapping.update(collection_map)
    mapping[orig] = rep

    sync_prop_rep_from_orig(orig, rep)

    # Armature's own parent (cart/path empty) is MigObjRelatives — not duplicated here.

    mapped_srcs = set(mapping.keys())
    candidates = set(rep_descendants)
    for ob in bpy.data.objects:
        if ob.parent in mapped_srcs:
            candidates.add(ob)
        for c in getattr(ob, "constraints", []):
            if getattr(c, "target", None) in mapped_srcs:
                candidates.add(ob)
        if ob.modifiers:
            for m in ob.modifiers:
                for attr in ("object", "target", "mirror_object"):
                    if getattr(m, attr, None) in mapped_srcs:
                        candidates.add(ob)
                        break
    # Exclude orig-side asset objects only (GEO/body/etc.) — NOT external children
    # like a pallet jack parented to the character (those must remapped to rep).
    candidates -= mapped_srcs

    reparented = 0
    for ob in candidates:
        if ob.parent in mapping:
            old_parent = ob.parent
            new_parent = mapping[ob.parent]
            if reparent_preserve_world_path(ob, new_parent, old_parent=old_parent):
                reparented += 1
    if reparented:
        print(f"[DLM RetargRelatives] reparented {reparented} object(s) with world-path preserve")
        if ob.modifiers:
            for m in ob.modifiers:
                for attr in ("object", "target", "mirror_object"):
                    val = getattr(m, attr, None)
                    if val in mapping:
                        try:
                            setattr(m, attr, mapping[val])
                        except Exception:
                            pass

    # Collection instances pointing at orig's asset root → rep's root.
    orig_root = override_root_collection(orig)
    rep_root = override_root_collection(rep)
    if orig_root is not None and rep_root is not None and orig_root != rep_root:
        for ob in bpy.data.objects:
            if getattr(ob, "instance_collection", None) is orig_root:
                try:
                    ob.instance_collection = rep_root
                except Exception:
                    pass

    # Object constraints (incl. eyes/GEO targets), bone constraints, all modifier
    # Object pointers, camera DOF, drivers — using the full collection map.
    # Do not rewrite pointers owned by orig-side asset objects (GEO→RIG, etc.).
    skip_arms = {o for o in mapped_srcs if getattr(o, "type", None) == "ARMATURE"}
    remap_object_usages(
        orig,
        rep,
        orig_to_rep=mapping,
        skip_bone_constraints_on=skip_arms or {orig},
        skip_self_drivers_on=mapped_srcs or {orig},
        skip_owners=mapped_srcs or {orig},
    )


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


def _process_mig_bbody_mesh(orig_base, ob, context):
    """Library overrides on rep mesh ob; copy shape key values and action from orig_base mesh."""
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
                print(f"[DLM step6] {ob.name} no orig base body found")
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


def run_mig_bbody_shapekeys(orig, rep, rep_descendants, context=None):
    """Replacement base body: library override (fully editable when context given), copy shapekey values, then shape-key action."""
    props = getattr(context.scene, "dynamic_library_manager", None) if context else None
    if props and getattr(props, "migbbody_manual_override", False):
        mo = getattr(props, "migbbody_orig_body", None)
        mr = getattr(props, "migbbody_rep_body", None)
        if mo and mr and mo.type == "MESH" and mr.type == "MESH":
            _process_mig_bbody_mesh(mo, mr, context)
            return

    orig_descendants = list(descendants(orig))
    any_auto = False
    for ob in list(rep_descendants):
        if not _base_body_name_match(ob):
            continue
        if ob.modifiers:
            for m in ob.modifiers:
                if m.type == "ARMATURE" and m.object == rep:
                    break
            else:
                continue
        any_auto = True
        orig_base = _find_base_body(orig, orig_descendants, rep_base_name=ob.name)
        _process_mig_bbody_mesh(orig_base, ob, context)
    if not any_auto and props is not None:
        props.migbbody_manual_override = True


def run_full_migration(context):
    """
    Run the full character migration for the single pair (manual or automatic).

    Steps: CopyAttr, MigNLA, MigCustProps, MigObjConst, MigObjRelatives,
    MigBoneConst, RetargRelatives, MigBBodyShapeKeys.
    Returns (True, message) on success, (False, error_message) on failure.
    """
    props = getattr(context.scene, "dynamic_library_manager", None)
    use_auto = props and getattr(props, "migrator_mode", False)
    orig, rep = (get_pair_automatic(context) if use_auto else get_pair_manual(context))
    if not orig or not rep:
        return False, "No character pair (set Original/Replacement or enable Automatic)."
    if orig == rep:
        return False, "Original and replacement must be different armatures."

    orig, rep = resolve_migration_pair(orig, rep, context.scene)
    if props and props.replacement_character != rep:
        props.replacement_character = rep

    orig_to_rep = {orig: rep}
    rep_descendants = descendants(rep)

    try:
        run_copy_attr(orig, rep)
        run_mig_nla(orig, rep, context=context)
        run_mig_cust_props(orig, rep)
        run_mig_obj_const(orig, rep, orig_to_rep)
        run_mig_obj_relatives(orig, rep, orig_to_rep, scene=context.scene)
        run_mig_bone_const(orig, rep, orig_to_rep)
        run_retarg_relatives(orig, rep, rep_descendants, orig_to_rep)
        run_mig_bbody_shapekeys(orig, rep, rep_descendants, context)
    except Exception as e:
        return False, str(e)
    return True, f"Migrated {orig.name} → {rep.name}"


def run_full_prop_migration(context):
    """Migrate a non-armature object pair: CopyAttr, MigNLA, MigCustProps, MigObjConst,
    MigObjRelatives, RetargRelatives. Returns (True, message) or (False, error)."""
    orig, rep = get_prop_pair(context)
    if not orig or not rep:
        return False, "No prop pair (set Original/Replacement Prop)."
    if orig.type == "ARMATURE" or rep.type == "ARMATURE":
        return False, "Prop Migrator does not accept armatures (use Character Migrator)."

    orig_to_rep = {orig: rep}
    rep_descendants = descendants(rep)
    try:
        run_copy_attr(orig, rep)
        run_mig_nla(orig, rep, context=context)
        run_mig_cust_props(orig, rep)
        run_mig_obj_const(orig, rep, orig_to_rep)
        run_mig_obj_relatives(orig, rep, orig_to_rep, scene=context.scene)
        run_retarg_relatives(orig, rep, rep_descendants, orig_to_rep)
    except Exception as e:
        return False, str(e)
    return True, f"Prop migrated {orig.name} → {rep.name}"


def run_remove_original_prop(context, orig, rep, report=None):
    """Remap refs orig→rep, unlink/delete orig prop object, clear original_prop."""
    from ..utils.remap_usages import remap_object_usages, remap_parents
    from ..utils.remove_original import _rename_rep_actions

    if not orig or orig.name not in bpy.data.objects:
        if report:
            report({"WARNING"}, "No original prop to remove")
        return False
    if orig.type == "ARMATURE":
        if report:
            report({"ERROR"}, "Use Character Migrator Remove Original for armatures")
        return False
    if orig == rep:
        if report:
            report({"ERROR"}, "Original and replacement cannot be the same object")
        return False

    name = orig.name
    if rep is not None:
        mapping = {orig: rep}
        remap_parents(mapping)
        remap_object_usages(orig, rep, skip_owners={orig})

    # Soft-unlink override props; hard-remove local ones.
    is_override = getattr(orig, "override_library", None) is not None
    for coll in list(orig.users_collection):
        try:
            coll.objects.unlink(orig)
        except Exception:
            pass
    if not is_override:
        try:
            bpy.data.objects.remove(orig, do_unlink=True)
        except Exception as e:
            if report:
                report({"ERROR"}, f"Could not delete {name}: {e}")
            return False
    else:
        # Leave override datablock; hide so it is gone from the scene.
        try:
            orig.hide_viewport = True
            orig.hide_render = True
        except Exception:
            pass

    props = getattr(context.scene, "dynamic_library_manager", None)
    if props is not None:
        props.original_prop = None

    renamed = _rename_rep_actions(rep)
    if renamed and report:
        report({"INFO"}, f"Renamed {len(renamed)} replacement action(s)")

    if report:
        mode = "soft-unlinked" if is_override else "deleted"
        report({"INFO"}, f"Removed original prop {name} ({mode})")
    return True
