# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

"""FK rotations: copy visible rotations from original to replacement using constraints."""

import bpy

# Arm FK bone name patterns to check (Rigify and common alternatives)
ARM_FK_PATTERNS = (
    # Rigify style
    ("upper_arm_fk.L", "upper_arm_fk.R"),
    ("forearm_fk.L", "forearm_fk.R"),
    ("hand_fk.L", "hand_fk.R"),
    # Common alternatives
    ("upper_arm.L", "upper_arm.R"),
    ("forearm.L", "forearm.R"),
    ("hand.L", "hand.R"),
    ("arm_fk.L", "arm_fk.R"),
    ("lower_arm_fk.L", "lower_arm_fk.R"),
    # Short forms
    ("arm.L", "arm.R"),
    ("elbow.L", "elbow.R"),
)

# Finger bone name patterns (will match with .01, .02, .03, etc.)
FINGER_PREFIXES = (
    "thumb", "f_index", "f_middle", "f_ring", "f_pinky",
    "finger1", "finger2", "finger3", "finger4", "finger5",
)


def _get_matching_arm_fk_bones(armature):
    """Return list of arm FK bone names that exist on armature."""
    if not armature or armature.type != "ARMATURE" or not armature.pose:
        return []
    bones = armature.pose.bones
    found = []
    for pattern in ARM_FK_PATTERNS:
        for name in pattern:
            if name in bones:
                found.append(name)
    return found


def _get_finger_fk_bones(armature):
    """Return list of FK finger bone names that exist on armature. Only control bones (no ORG-/DEF-/MCH- prefix)."""
    if not armature or armature.type != "ARMATURE" or not armature.pose:
        return []
    bones = armature.pose.bones
    finger_bones = []
    for bone_name in bones.keys():
        if bone_name.startswith("ORG-") or bone_name.startswith("DEF-") or bone_name.startswith("MCH-"):
            continue
        lower_name = bone_name.lower()
        for prefix in FINGER_PREFIXES:
            if prefix in lower_name and ("_fk." in bone_name or bone_name.endswith(".L") or bone_name.endswith(".R")):
                if "." in bone_name and any(d in bone_name for d in "0123456789"):
                    finger_bones.append(bone_name)
                    break
    return finger_bones


def _get_fk_bones(armature):
    """Return list of all FK arm and finger bone names that exist on armature."""
    arm_bones = _get_matching_arm_fk_bones(armature)
    finger_bones = _get_finger_fk_bones(armature)
    return list(dict.fromkeys(arm_bones + finger_bones))


def copy_fk_rotations(context, orig, rep):
    """
    Copy visual rotations from orig to rep using temporary COPY_TRANSFORMS constraints.
    This properly handles all coordinate space conversions.
    Returns (True, message) or (False, error_message).
    """
    fk_names = _get_fk_bones(rep)

    print(f"[DLM MigFKRot] Found {len(fk_names)} FK bones on {rep.name}")

    if not fk_names:
        return False, "No FK arm or finger bones found on replacement armature"

    # Filter to bones that exist on both
    common_bones = [n for n in fk_names if n in orig.pose.bones and n in rep.pose.bones]
    if not common_bones:
        return False, "No matching FK bones found on both armatures"

    print(f"[DLM MigFKRot] Will copy {len(common_bones)} bones using constraints")

    original_active = context.view_layer.objects.active
    constraints_added = []

    try:
        # ALS evaluates from the active layer; MigNLA leaves the bottom track
        # selected. Activate topmost on orig and rep before visual copy.
        _activate_topmost_nla(context, orig)
        _activate_topmost_nla(context, rep)
        context.view_layer.update()

        # Ensure rep is active and in pose mode
        bpy.context.view_layer.objects.active = rep
        if rep.mode != 'POSE':
            bpy.ops.object.mode_set(mode='POSE')

        # Step 1: Add COPY_TRANSFORMS constraints to each rep bone
        for bone_name in common_bones:
            rep_bone = rep.pose.bones[bone_name]
            
            # Check if bone already has this constraint
            existing = [c for c in rep_bone.constraints if c.type == 'COPY_TRANSFORMS' and getattr(c, 'target', None) == orig]
            if existing:
                continue
            
            # Add constraint
            c = rep_bone.constraints.new(type='COPY_TRANSFORMS')
            c.name = "MigFKRot_Temp"
            c.target = orig
            c.subtarget = bone_name
            c.target_space = 'POSE'
            c.owner_space = 'POSE'
            constraints_added.append((rep_bone, c))

        # Step 2: Update scene to evaluate constraints
        context.view_layer.update()

        # Step 3: Apply visual transform (bake constraint result into pose)
        try:
            bpy.ops.pose.select_all(action='DESELECT')
            for rep_bone, _ in constraints_added:
                rep_bone.bone.select = True
            # Apply visual transform - this bakes the constraint result
            bpy.ops.pose.visual_transform_apply()
        except (RuntimeError, AttributeError):
            # visual_transform_apply requires bones to be selectable
            # AttributeError: 'bone.select' may not exist in Blender 5.0
            # If selection fails, the constraint result is still applied
            pass  # Silently ignore - constraints still drove the pose

        # Constraints remain active for bake step
        print(f"[DLM MigFKRot] Copied {len(constraints_added)} bones (constraints active)")
        return True, f"Copied FK rotations for {len(constraints_added)} bones (constraints active - run Bake to finalize)"

    except Exception as e:
        print(f"[DLM MigFKRot] Error: {e}")
        # Cleanup constraints on error
        for rep_bone, c in constraints_added:
            try:
                if c in rep_bone.constraints:
                    rep_bone.constraints.remove(c)
            except:
                pass
        return False, str(e)

    finally:
        # Only restore active object, don't remove constraints
        if original_active:
            context.view_layer.objects.active = original_active


def _iter_action_fcurves(action):
    """Yield fcurves from legacy and slotted (Blender 4.4+/5) actions."""
    seen = set()

    def _from_bags(bags):
        for cb in bags or []:
            for fc in getattr(cb, "fcurves", []) or []:
                fid = id(fc)
                if fid not in seen:
                    seen.add(fid)
                    yield fc

    if hasattr(action, "layers"):
        try:
            for layer in action.layers:
                for strip in getattr(layer, "strips", []) or []:
                    yield from _from_bags(getattr(strip, "channelbags", None))
        except Exception:
            pass
    if hasattr(action, "channelbags"):
        try:
            yield from _from_bags(action.channelbags)
        except Exception:
            pass
    if hasattr(action, "fcurves"):
        try:
            for fc in action.fcurves:
                fid = id(fc)
                if fid not in seen:
                    seen.add(fid)
                    yield fc
        except Exception:
            pass


def _get_action_frame_range(action):
    """Get the full frame range from action keyframes (not just strip in/out)."""
    if not action:
        return None

    frames = set()
    for fc in _iter_action_fcurves(action):
        for kp in getattr(fc, "keyframe_points", []) or []:
            frames.add(int(kp.co.x))

    if frames:
        return (min(frames), max(frames))
    fr = getattr(action, "frame_range", None)
    if fr is not None:
        try:
            return (int(fr[0]), int(fr[1]))
        except Exception:
            pass
    return None


def _extract_bone_name_from_data_path(data_path):
    """Extract bone name from fcurve data_path like 'pose.bones["bone.name"].rotation_euler'."""
    if not data_path:
        return None
    if 'pose.bones["' in data_path:
        start = data_path.find('["') + 2
        end = data_path.find('"]', start)
        if start > 1 and end > start:
            return data_path[start:end]
    elif "pose.bones['" in data_path:
        start = data_path.find("['") + 2
        end = data_path.find("']", start)
        if start > 1 and end > start:
            return data_path[start:end]
    return None


def _unique_datablock_name(base, existing_names):
    """Return base, or base.001 / base.002 / ... if taken."""
    name = base
    n = 1
    while name in existing_names:
        name = f"{base}.{n:03d}"
        n += 1
    return name


def _new_object_action(name, ob):
    """Create an empty action (with an object slot on Blender 4.4+)."""
    action = bpy.data.actions.new(name=name)
    if hasattr(action, "slots"):
        try:
            if len(action.slots) == 0:
                try:
                    action.slots.new(id_type="OBJECT", name=ob.name)
                except TypeError:
                    action.slots.new(name=ob.name, id_type="OBJECT")
        except Exception:
            pass
    return action


def _assign_action(ad, action, slot=None):
    """Assign action (and optional slot) when AnimData.action is writable.

    Animation Layers puts the object in NLA tweak mode, which makes
    ``ad.action`` read-only. Callers must not rely on this for ALS objects.
    """
    try:
        ad.action = action
    except Exception as e:
        print(f"[DLM MigFKRot Bake] action assign failed: {e}")
        return False
    if action is None or not hasattr(ad, "action_slot"):
        return True
    use_slot = slot
    if use_slot is None and hasattr(action, "slots") and action.slots:
        use_slot = action.slots[0]
    if use_slot is None:
        return True
    try:
        ad.action_slot = use_slot
    except Exception as e:
        print(f"[DLM MigFKRot Bake] action_slot assign failed: {e}")
    return True


def _als_on(ob):
    """True when Animation Layers is enabled on this object."""
    als = getattr(ob, "als", None)
    return bool(als and getattr(als, "turn_on", False))


def _als_active_layer_name(ob):
    """Name of the selected Animation Layers row, or None."""
    als = getattr(ob, "als", None)
    layers = getattr(ob, "Anim_Layers", None)
    if als is None or not layers:
        return None
    i = als.layer_index
    if 0 <= i < len(layers):
        return layers[i].name
    return None


def _als_set_active_layer(ob, name):
    """Select an Animation Layers row by NLA/layer name."""
    layers = getattr(ob, "Anim_Layers", None)
    if not layers or not name:
        return
    idx = layers.find(name)
    if idx != -1:
        ob.als.layer_index = idx


def _topmost_usable_layer_name(ob):
    """Last usable ALS row (NLA top). Skip not_usable / GROUP rows."""
    layers = getattr(ob, "Anim_Layers", None)
    ad = getattr(ob, "animation_data", None)
    if not ob or not layers:
        if ad and ad.nla_tracks:
            return ad.nla_tracks[-1].name
        return None
    for i in range(len(layers) - 1, -1, -1):
        item = layers[i]
        if getattr(item, "not_usable", False):
            continue
        if getattr(item, "type", "LAYER") == "GROUP":
            continue
        if ad:
            track = _nla_track_by_name(ad, item.name)
            if track is None or not track.strips:
                continue
        return item.name
    if ad and ad.nla_tracks:
        return ad.nla_tracks[-1].name
    return None


def _activate_topmost_nla(context, ob, log_prefix="[DLM]"):
    """Make the topmost NLA/ALS track the active tweak layer.

    ALS tweak mode evaluates from the active layer; a bottom selection can skip
    or mis-evaluate the stack.
    """
    if not ob:
        return None
    prev_active = None
    if context and getattr(context, "view_layer", None):
        prev_active = context.view_layer.objects.active
    try:
        if context and getattr(context, "view_layer", None):
            try:
                context.view_layer.objects.active = ob
            except Exception:
                pass
        if _als_on(ob):
            name = _topmost_usable_layer_name(ob)
            if name:
                _als_set_active_layer(ob, name)
            print(f"{log_prefix} {ob.name} ALS topmost -> {name}")
            return name
        ad = ob.animation_data
        if not ad or not ad.nla_tracks:
            return None
        track = ad.nla_tracks[-1]
        try:
            for t in ad.nla_tracks:
                t.select = False
                for s in t.strips:
                    s.select = False
            track.select = True
            ad.nla_tracks.active = track
            if track.strips:
                track.strips[0].select = True
        except Exception:
            pass
        print(f"{log_prefix} {ob.name} NLA topmost -> {track.name}")
        return track.name
    finally:
        if context and prev_active:
            try:
                context.view_layer.objects.active = prev_active
            except Exception:
                pass


def _nla_track_by_name(ad, name):
    if not ad or not name:
        return None
    for track in ad.nla_tracks:
        if track.name == name:
            return track
    return None


def _select_fk_bones(rep, bone_names):
    """Select only the given pose bones (Blender 5-safe)."""
    bpy.ops.pose.select_all(action="DESELECT")
    for bone_name in bone_names:
        rep_bone = rep.pose.bones.get(bone_name)
        if not rep_bone:
            continue
        try:
            rep_bone.select = True
        except (AttributeError, TypeError):
            try:
                if hasattr(rep_bone, "bone"):
                    rep_bone.bone.select = True
            except (AttributeError, TypeError):
                pass


def _nla_bake_rotations(frame_start, frame_end):
    """Visual-rotation bake into whatever action is currently editable."""
    bpy.ops.nla.bake(
        frame_start=frame_start,
        frame_end=frame_end,
        step=1,
        only_selected=True,
        visual_keying=True,
        clear_constraints=False,
        clear_parents=False,
        use_current_action=True,
        clean_curves=False,
        bake_types={"POSE"},
        channel_types={"ROTATION"},
    )


def _setup_als_bake_layer(rep, layer_name):
    """Add an ALS layer with its own action; rename; REPLACE. Return (track, action)."""
    ad = rep.animation_data
    before = {t.name for t in ad.nla_tracks}
    bpy.ops.anim.add_anim_layer()
    ad = rep.animation_data
    new_name = _als_active_layer_name(rep)
    track = _nla_track_by_name(ad, new_name)
    if track is None:
        added = [t for t in ad.nla_tracks if t.name not in before]
        track = added[-1] if added else None
    if track is None or not track.strips:
        raise RuntimeError("Animation Layers did not create a new track")

    strip = track.strips[0]
    existing = {t.name for t in ad.nla_tracks if t != track}
    existing.update(a.name for a in bpy.data.actions)
    if strip.action:
        existing.discard(strip.action.name)
    name = _unique_datablock_name(layer_name, existing)
    track.name = name
    strip.name = name
    if strip.action:
        strip.action.name = name
    strip.blend_type = "REPLACE"
    strip.use_auto_blend = False

    layers = getattr(rep, "Anim_Layers", None)
    if layers:
        for item in layers:
            if item.name in (new_name, name) or item.name == track.name:
                if item.name != name:
                    try:
                        item.name = name
                    except Exception:
                        pass
                break
    _als_set_active_layer(rep, name)
    return track, strip.action


def _als_move_active_layer_to_top(rep):
    """NLA last-track is evaluated on top; REPLACE must sit there."""
    ad = rep.animation_data
    if not ad or not ad.nla_tracks:
        return
    name = _als_active_layer_name(rep)
    for _ in range(len(ad.nla_tracks) + 2):
        tracks = list(ad.nla_tracks)
        if not tracks or tracks[-1].name == name:
            break
        try:
            bpy.ops.anim.layer_move_up()
        except Exception:
            break
        name = _als_active_layer_name(rep) or name


def _snapshot_nla_strip_actions(ad):
    """List of (strip, action) so ALS cannot leave bake keys on the active layer strip."""
    out = []
    if not ad:
        return out
    for track in ad.nla_tracks:
        for strip in track.strips:
            out.append((strip, strip.action))
    return out


def _restore_nla_strip_actions(snapshot):
    """Reassign strip.action if bake/ALS retargeted it."""
    for strip, action in snapshot:
        try:
            if strip.action != action:
                strip.action = action
        except Exception:
            pass


def _remove_migfkrot_temp_constraints(rep, fk_names):
    """Remove COPY_TRANSFORMS named MigFKRot_Temp (RNA refs from bake are often stale)."""
    removed = 0
    for bone_name in fk_names:
        pb = rep.pose.bones.get(bone_name)
        if not pb:
            continue
        for c in [c for c in pb.constraints if c.name == "MigFKRot_Temp" or (
            c.type == "COPY_TRANSFORMS" and c.name.startswith("MigFKRot")
        )]:
            try:
                pb.constraints.remove(c)
                removed += 1
            except Exception:
                pass
    return removed


def _ensure_replace_nla_track(ad, bake_action, name, frame_start, frame_end):
    """One REPLACE track at the top of the stack; same name for track and strip."""
    for track in list(ad.nla_tracks):
        bake_strips = [s for s in track.strips if s.action == bake_action]
        if not bake_strips:
            continue
        for strip in bake_strips:
            try:
                track.strips.remove(strip)
            except Exception:
                pass
        if len(track.strips) == 0:
            try:
                ad.nla_tracks.remove(track)
            except Exception:
                pass

    track_name = _unique_datablock_name(name, {t.name for t in ad.nla_tracks})
    prev = ad.nla_tracks[-1] if ad.nla_tracks else None
    nla_track = ad.nla_tracks.new(prev=prev)
    nla_track.name = track_name
    strip = nla_track.strips.new(name=track_name, start=int(frame_start), action=bake_action)
    strip.frame_end = frame_end
    strip.blend_type = "REPLACE"
    strip.use_auto_blend = False
    return nla_track


def bake_fk_rotations(context, orig, rep, track_name=None, post_clean=False):
    """
    Bake FK arm/finger rotations to a new NLA track with replace mode.
    Returns (True, message) or (False, error_message).
    """
    print(f"[DLM MigFKRot Bake] START: orig={orig.name}, rep={rep.name}")
    
    fk_names = _get_fk_bones(rep)
    print(f"[DLM MigFKRot Bake] Found {len(fk_names)} FK bones: {fk_names[:5]}...")
    
    if not fk_names:
        return False, f"No FK bones found on {rep.name}"

    # Filter to bones that exist on both
    common_bones = [n for n in fk_names if n in orig.pose.bones and n in rep.pose.bones]
    print(f"[DLM MigFKRot Bake] {len(common_bones)} common bones between orig and rep")
    
    if not common_bones:
        return False, "No matching FK bones found on both armatures"

    # Get source action for frame range (from keyframes, not strip bounds)
    source_action = None
    if rep.animation_data:
        if rep.animation_data.action:
            source_action = rep.animation_data.action
        elif rep.animation_data.nla_tracks:
            for track in rep.animation_data.nla_tracks:
                if track.strips:
                    for strip in track.strips:
                        if strip.action:
                            source_action = strip.action
                            break
                if source_action:
                    break
    
    # Get frame range from source action keyframes
    frame_range = _get_action_frame_range(source_action) if source_action else None
    
    if not frame_range:
        # Fallback to scene range
        frame_range = (context.scene.frame_start, context.scene.frame_end)
    
    frame_start, frame_end = frame_range

    # Ensure rep is active and in pose mode
    if context.view_layer.objects.active != rep:
        context.view_layer.objects.active = rep
    if rep.mode != "POSE":
        bpy.ops.object.mode_set(mode="POSE")

    # ALS evaluates from the active layer; MigNLA leaves the bottom track
    # selected. Topmost on orig+rep first so visual bake sees the full stack.
    _activate_topmost_nla(context, orig)
    _activate_topmost_nla(context, rep)
    context.view_layer.objects.active = rep
    context.view_layer.update()

    # Step 1: Check for existing COPY_TRANSFORMS constraints
    constraints_added = []
    for bone_name in common_bones:
        rep_bone = rep.pose.bones[bone_name]
        existing = [c for c in rep_bone.constraints if c.type == 'COPY_TRANSFORMS' and getattr(c, 'target', None) == orig]
        if existing:
            constraints_added.append((rep_bone, existing[0]))

    print(f"[DLM MigFKRot Bake] Found {len(constraints_added)} constraints from {orig.name} to {rep.name}")
    print(f"[DLM MigFKRot Bake] Frame range: {frame_start}-{frame_end}")

    if rep.animation_data is None:
        rep.animation_data_create()
    ad = rep.animation_data
    base_name = (track_name or "").strip() or f"FK_Bake_{frame_start}-{frame_end}"
    als = _als_on(rep)
    print(f"[DLM MigFKRot Bake] ALS turn_on={als} action_readonly={ad.is_property_readonly('action')}")

    bake_ok = False
    bake_err = None
    bake_action = None
    nla_track = None
    prev_layer_name = _als_active_layer_name(rep) if als else None
    prev_action = ad.action if not als else None
    prev_slot = getattr(ad, "action_slot", None) if not als else None
    prev_slot_id = getattr(ad, "last_slot_identifier", None) if not als else None
    strip_snapshot = _snapshot_nla_strip_actions(ad) if not als else None

    try:
        if als:
            nla_track, bake_action = _setup_als_bake_layer(rep, base_name)
            _als_move_active_layer_to_top(rep)
            context.view_layer.objects.active = rep
            if nla_track:
                _als_set_active_layer(rep, nla_track.name)
            if ad.nla_tracks and nla_track and ad.nla_tracks[-1] != nla_track:
                print(
                    f"[DLM MigFKRot Bake] WARNING: bake layer {nla_track.name!r} "
                    f"is not topmost (top={ad.nla_tracks[-1].name!r})"
                )
            print(
                f"[DLM MigFKRot Bake] ALS layer '{nla_track.name}' "
                f"action={bake_action.name if bake_action else None} "
                f"(was {prev_layer_name})"
            )
        else:
            action_name = _unique_datablock_name(base_name, {a.name for a in bpy.data.actions})
            bake_action = _new_object_action(action_name, rep)
            assigned = _assign_action(ad, bake_action)
            if not assigned:
                raise RuntimeError("Could not assign bake action (AnimData.action is read-only)")
            print(
                f"[DLM MigFKRot Bake] Baking to new action: {bake_action.name} "
                f"(active was {prev_action.name if prev_action else None})"
            )

        print(f"[DLM MigFKRot Bake] Selecting {len(common_bones)} FK bones...")
        _select_fk_bones(rep, common_bones)
        print("[DLM MigFKRot Bake] Running nla.bake with only_selected=True...")
        _nla_bake_rotations(frame_start, frame_end)
        bake_ok = True
        print("[DLM MigFKRot Bake] nla.bake completed successfully")

        if post_clean:
            win = context.window
            for area in win.screen.areas:
                if area.type == "DOPESHEET_EDITOR":
                    with context.temp_override(window=win, area=area):
                        try:
                            bpy.ops.action.clean_keyframes()
                        except Exception:
                            pass
                    break
            for area in win.screen.areas:
                if area.type == "GRAPH_EDITOR":
                    with context.temp_override(window=win, area=area):
                        try:
                            bpy.ops.graph.decimate(mode="ERROR", error=0.001)
                        except Exception:
                            pass
                    break
    except Exception as e:
        bake_err = e
        print(f"[DLM MigFKRot Bake] nla.bake failed: {e}")
    finally:
        if als:
            if not bake_ok:
                _als_set_active_layer(rep, prev_layer_name)
        else:
            if strip_snapshot is not None:
                _restore_nla_strip_actions(strip_snapshot)
            if prev_slot_id and hasattr(ad, "last_slot_identifier"):
                try:
                    ad.last_slot_identifier = prev_slot_id
                except Exception:
                    pass
            _assign_action(ad, prev_action, prev_slot)

    if not bake_ok:
        if als and nla_track:
            try:
                _als_set_active_layer(rep, nla_track.name)
                bpy.ops.anim.remove_anim_layer()
            except Exception as e:
                print(f"[DLM MigFKRot Bake] Could not remove failed ALS layer: {e}")
            _als_set_active_layer(rep, prev_layer_name)
        elif bake_action:
            try:
                bpy.data.actions.remove(bake_action)
            except Exception:
                pass
        return False, f"nla.bake failed: {bake_err}"

    removed_count = _remove_migfkrot_temp_constraints(rep, common_bones)
    print(f"[DLM MigFKRot Bake] Removed {removed_count} constraints")

    if not als:
        nla_track = _ensure_replace_nla_track(ad, bake_action, bake_action.name, frame_start, frame_end)
        _activate_topmost_nla(context, orig)
        _activate_topmost_nla(context, rep)
        context.view_layer.objects.active = rep
    else:
        if nla_track:
            _als_set_active_layer(rep, nla_track.name)
        _activate_topmost_nla(context, orig)
        context.view_layer.objects.active = rep

    print(
        f"[DLM MigFKRot Bake] NLA track '{nla_track.name if nla_track else '?'}' "
        f"(REPLACE, action={bake_action.name if bake_action else None})"
    )

    if post_clean:
        return True, f"Baked and cleaned {len(common_bones)} FK bones to NLA track ({frame_start}-{frame_end})."
    return True, f"Baked {len(common_bones)} FK bones to NLA track ({frame_start}-{frame_end})."


def remove_fk_rotations(context, rep):
    """
    Remove COPY_TRANSFORMS constraints that were added by copy_fk_rotations.
    Similar to tweak_tools.remove_tweak_constraints.
    Returns (True, message) or (False, error_message).
    """
    fk_names = _get_fk_bones(rep)
    if not fk_names:
        return False, f"No FK bones found on {rep.name}"

    removed = 0
    for bone_name in fk_names:
        if bone_name not in rep.pose.bones:
            continue
        rep_bone = rep.pose.bones[bone_name]
        to_remove = [
            c for c in rep_bone.constraints
            if c.type == 'COPY_TRANSFORMS' and c.name == "MigFKRot_Temp"
        ]
        for c in to_remove:
            rep_bone.constraints.remove(c)
            removed += 1

    return True, f"Removed {removed} FK rotation constraints."
