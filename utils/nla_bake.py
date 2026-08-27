# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

"""Shared NLA / Animation Layers bake: dedicated top REPLACE layer, ALS-safe."""

import bpy


def unique_datablock_name(base, existing_names):
    """Return base, or base.001 / base.002 / ... if taken."""
    name = base
    n = 1
    while name in existing_names:
        name = f"{base}.{n:03d}"
        n += 1
    return name


def new_object_action(name, ob):
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


def assign_action(ad, action, slot=None, log_prefix="[DLM Bake]"):
    """Assign action (and optional slot) when AnimData.action is writable.

    Animation Layers puts the object in NLA tweak mode, which makes
    ``ad.action`` read-only. Callers must not rely on this for ALS objects.
    """
    try:
        ad.action = action
    except Exception as e:
        print(f"{log_prefix} action assign failed: {e}")
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
        print(f"{log_prefix} action_slot assign failed: {e}")
    return True


def als_on(ob):
    """True when Animation Layers is enabled on this object."""
    als = getattr(ob, "als", None)
    return bool(als and getattr(als, "turn_on", False))


def als_active_layer_name(ob):
    """Name of the selected Animation Layers row, or None."""
    als = getattr(ob, "als", None)
    layers = getattr(ob, "Anim_Layers", None)
    if als is None or not layers:
        return None
    i = als.layer_index
    if 0 <= i < len(layers):
        return layers[i].name
    return None


def als_set_active_layer(ob, name):
    """Select an Animation Layers row by NLA/layer name."""
    layers = getattr(ob, "Anim_Layers", None)
    if not layers or not name:
        return
    idx = layers.find(name)
    if idx != -1:
        ob.als.layer_index = idx


def nla_track_by_name(ad, name):
    if not ad or not name:
        return None
    for track in ad.nla_tracks:
        if track.name == name:
            return track
    return None


def topmost_usable_layer_name(ob):
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
            track = nla_track_by_name(ad, item.name)
            if track is None or not track.strips:
                continue
        return item.name
    if ad and ad.nla_tracks:
        return ad.nla_tracks[-1].name
    return None


def activate_topmost_nla(context, ob, log_prefix="[DLM]"):
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
        if als_on(ob):
            name = topmost_usable_layer_name(ob)
            if name:
                als_set_active_layer(ob, name)
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


def select_pose_bones(rep, bone_names):
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


def setup_als_bake_layer(rep, layer_name):
    """Add an ALS layer with its own action; rename; REPLACE. Return (track, action)."""
    ad = rep.animation_data
    before = {t.name for t in ad.nla_tracks}
    bpy.ops.anim.add_anim_layer()
    ad = rep.animation_data
    new_name = als_active_layer_name(rep)
    track = nla_track_by_name(ad, new_name)
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
    name = unique_datablock_name(layer_name, existing)
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
    als_set_active_layer(rep, name)
    return track, strip.action


def als_move_active_layer_to_top(rep):
    """NLA last-track is evaluated on top; REPLACE must sit there."""
    ad = rep.animation_data
    if not ad or not ad.nla_tracks:
        return
    name = als_active_layer_name(rep)
    for _ in range(len(ad.nla_tracks) + 2):
        tracks = list(ad.nla_tracks)
        if not tracks or tracks[-1].name == name:
            break
        try:
            bpy.ops.anim.layer_move_up()
        except Exception:
            break
        name = als_active_layer_name(rep) or name


def snapshot_nla_strip_actions(ad):
    """List of (strip, action) so ALS cannot leave bake keys on the active layer strip."""
    out = []
    if not ad:
        return out
    for track in ad.nla_tracks:
        for strip in track.strips:
            out.append((strip, strip.action))
    return out


def restore_nla_strip_actions(snapshot):
    """Reassign strip.action if bake/ALS retargeted it."""
    for strip, action in snapshot:
        try:
            if strip.action != action:
                strip.action = action
        except Exception:
            pass


def ensure_replace_nla_track(ad, bake_action, name, frame_start, frame_end):
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

    track_name = unique_datablock_name(name, {t.name for t in ad.nla_tracks})
    prev = ad.nla_tracks[-1] if ad.nla_tracks else None
    nla_track = ad.nla_tracks.new(prev=prev)
    nla_track.name = track_name
    strip = nla_track.strips.new(name=track_name, start=int(frame_start), action=bake_action)
    strip.frame_end = frame_end
    strip.blend_type = "REPLACE"
    strip.use_auto_blend = False
    return nla_track


def _post_clean_curves(context):
    """Optional clean + decimate on the baked action."""
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


def bake_pose_to_replace_layer(
    context,
    orig,
    rep,
    bone_names,
    *,
    frame_start,
    frame_end,
    layer_name=None,
    channel_types=None,
    clear_constraints=False,
    clear_parents=False,
    post_clean=False,
    log_prefix="[DLM Bake]",
):
    """
    Bake selected pose bones into a dedicated top REPLACE NLA/ALS layer.

    Does not write into the active ALS action. Returns
    ``(ok, message, nla_track, bake_action)``.
    """
    if not bone_names:
        return False, "No bones to bake", None, None
    if channel_types is None:
        channel_types = {"LOCATION", "ROTATION"}

    if context.view_layer.objects.active != rep:
        try:
            context.view_layer.objects.active = rep
        except Exception:
            pass
    if rep.mode != "POSE":
        bpy.ops.object.mode_set(mode="POSE")

    # ALS evaluates from the active layer; MigNLA leaves the bottom track
    # selected. Topmost on orig+rep first so visual bake sees the full stack.
    activate_topmost_nla(context, orig, log_prefix=log_prefix)
    activate_topmost_nla(context, rep, log_prefix=log_prefix)
    try:
        context.view_layer.objects.active = rep
    except Exception:
        pass
    context.view_layer.update()

    if rep.animation_data is None:
        rep.animation_data_create()
    ad = rep.animation_data
    base_name = (layer_name or "").strip() or f"Bake_{frame_start}-{frame_end}"
    als = als_on(rep)
    print(f"{log_prefix} ALS turn_on={als} action_readonly={ad.is_property_readonly('action')}")

    bake_ok = False
    bake_err = None
    bake_action = None
    nla_track = None
    prev_layer_name = als_active_layer_name(rep) if als else None
    prev_action = ad.action if not als else None
    prev_slot = getattr(ad, "action_slot", None) if not als else None
    prev_slot_id = getattr(ad, "last_slot_identifier", None) if not als else None
    strip_snapshot = snapshot_nla_strip_actions(ad) if not als else None

    try:
        if als:
            nla_track, bake_action = setup_als_bake_layer(rep, base_name)
            als_move_active_layer_to_top(rep)
            context.view_layer.objects.active = rep
            if nla_track:
                als_set_active_layer(rep, nla_track.name)
            if ad.nla_tracks and nla_track and ad.nla_tracks[-1] != nla_track:
                print(
                    f"{log_prefix} WARNING: bake layer {nla_track.name!r} "
                    f"is not topmost (top={ad.nla_tracks[-1].name!r})"
                )
            print(
                f"{log_prefix} ALS layer '{nla_track.name}' "
                f"action={bake_action.name if bake_action else None} "
                f"(was {prev_layer_name})"
            )
        else:
            action_name = unique_datablock_name(base_name, {a.name for a in bpy.data.actions})
            bake_action = new_object_action(action_name, rep)
            assigned = assign_action(ad, bake_action, log_prefix=log_prefix)
            if not assigned:
                raise RuntimeError("Could not assign bake action (AnimData.action is read-only)")
            print(
                f"{log_prefix} Baking to new action: {bake_action.name} "
                f"(active was {prev_action.name if prev_action else None})"
            )

        print(f"{log_prefix} Selecting {len(bone_names)} bones...")
        select_pose_bones(rep, bone_names)
        print(f"{log_prefix} Running nla.bake with only_selected=True...")
        bpy.ops.nla.bake(
            frame_start=frame_start,
            frame_end=frame_end,
            step=1,
            only_selected=True,
            visual_keying=True,
            clear_constraints=clear_constraints,
            clear_parents=clear_parents,
            use_current_action=True,
            clean_curves=False,
            bake_types={"POSE"},
            channel_types=set(channel_types),
        )
        bake_ok = True
        print(f"{log_prefix} nla.bake completed successfully")

        if post_clean:
            _post_clean_curves(context)
    except Exception as e:
        bake_err = e
        print(f"{log_prefix} nla.bake failed: {e}")
    finally:
        if als:
            if not bake_ok:
                als_set_active_layer(rep, prev_layer_name)
        else:
            if strip_snapshot is not None:
                restore_nla_strip_actions(strip_snapshot)
            if prev_slot_id and hasattr(ad, "last_slot_identifier"):
                try:
                    ad.last_slot_identifier = prev_slot_id
                except Exception:
                    pass
            assign_action(ad, prev_action, prev_slot, log_prefix=log_prefix)

    if not bake_ok:
        if als and nla_track:
            try:
                als_set_active_layer(rep, nla_track.name)
                bpy.ops.anim.remove_anim_layer()
            except Exception as e:
                print(f"{log_prefix} Could not remove failed ALS layer: {e}")
            als_set_active_layer(rep, prev_layer_name)
        elif bake_action:
            try:
                bpy.data.actions.remove(bake_action)
            except Exception:
                pass
        return False, f"nla.bake failed: {bake_err}", None, None

    if not als:
        nla_track = ensure_replace_nla_track(
            ad, bake_action, bake_action.name, frame_start, frame_end
        )
        activate_topmost_nla(context, orig, log_prefix=log_prefix)
        activate_topmost_nla(context, rep, log_prefix=log_prefix)
        try:
            context.view_layer.objects.active = rep
        except Exception:
            pass
    else:
        if nla_track:
            als_set_active_layer(rep, nla_track.name)
        activate_topmost_nla(context, orig, log_prefix=log_prefix)
        try:
            context.view_layer.objects.active = rep
        except Exception:
            pass

    print(
        f"{log_prefix} NLA track '{nla_track.name if nla_track else '?'}' "
        f"(REPLACE, action={bake_action.name if bake_action else None})"
    )
    msg = (
        f"Baked and cleaned {len(bone_names)} bones to NLA track ({frame_start}-{frame_end})."
        if post_clean
        else f"Baked {len(bone_names)} bones to NLA track ({frame_start}-{frame_end})."
    )
    return True, msg, nla_track, bake_action
