# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

"""Tweak tools: add/remove/bake COPY_TRANSFORMS on Rigify tweak bones (arm, leg, or all)."""

import bpy

# Rigify-style tweak bone names (only those present on armature are used)
ARM_TWEAK_BONES = (
    "upper_arm_tweak.L", "upper_arm_tweak.R",
    "forearm_tweak.L", "forearm_tweak.R",
    "hand_tweak.L", "hand_tweak.R",
)
LEG_TWEAK_BONES = (
    "thigh_tweak.L", "thigh_tweak.R",
    "shin_tweak.L", "shin_tweak.R",
    "foot_tweak.L", "foot_tweak.R",
)
TWEAK_CONSTRAINT_NAME = "Copy from Original"


def get_tweak_bones(armature, limb):
    """Return list of tweak bone names that exist on armature. limb in 'arm', 'leg', 'body', 'both'."""
    if not armature or armature.type != "ARMATURE" or not armature.pose:
        return []
    bones = armature.pose.bones
    if limb == "arm":
        names = ARM_TWEAK_BONES
    elif limb == "leg":
        names = LEG_TWEAK_BONES
    elif limb == "body":
        # Body/torso tweaks: tweak_spine, spine_fk, etc. (no arm/leg)
        arm_leg_names = set(ARM_TWEAK_BONES + LEG_TWEAK_BONES)
        names = [
            b.name for b in bones
            if ("tweak" in b.name.lower() or "spine_fk" in b.name.lower())
            and b.name not in arm_leg_names
        ]
    elif limb == "both":
        # ALL tweak bones: any bone with "tweak" or "spine_fk" in the name
        names = [
            b.name for b in bones
            if "tweak" in b.name.lower() or "spine_fk" in b.name.lower()
        ]
    else:
        return []
    return [n for n in names if n in bones]


def add_tweak_constraints(orig, rep, limb):
    """On rep, add COPY_TRANSFORMS on each tweak bone targeting same bone on orig."""
    names = get_tweak_bones(rep, limb)
    for name in names:
        pb = rep.pose.bones[name]
        c = pb.constraints.new(type="COPY_TRANSFORMS")
        c.name = TWEAK_CONSTRAINT_NAME
        c.target = orig
        c.subtarget = name
        c.mix_mode = "REPLACE"


def remove_tweak_constraints(orig, rep, limb):
    """On rep, remove COPY_TRANSFORMS that target orig from tweak bones."""
    names = get_tweak_bones(rep, limb)
    removed = 0
    for name in names:
        pb = rep.pose.bones[name]
        to_remove = [
            c for c in pb.constraints
            if c.type == "COPY_TRANSFORMS" and getattr(c, "target", None) == orig
        ]
        for c in to_remove:
            pb.constraints.remove(c)
            removed += 1
    return removed


def _frame_range_from_track(rep, track_name):
    """Return (frame_start, frame_end) from rep's NLA track named track_name, or None."""
    if not track_name or not rep.animation_data or not rep.animation_data.nla_tracks:
        return None
    track = rep.animation_data.nla_tracks.get(track_name)
    if not track or not track.strips:
        return None
    start = min(s.frame_start for s in track.strips)
    end = max(s.frame_end for s in track.strips)
    return (int(start), int(end))


def bake_tweak_constraints(context, orig, rep, limb, track_name, post_clean):
    """
    Select rep's tweak bones, run nla.bake, optionally run clean + decimate.
    Returns (True, message) or (False, error_message).
    """
    names = get_tweak_bones(rep, limb)
    if not names:
        return False, f"No tweak bones found for {limb} on {rep.name}"

    scene = context.scene
    frame_range = _frame_range_from_track(rep, track_name) if track_name else None
    if not frame_range:
        frame_range = (scene.frame_start, scene.frame_end)
    frame_start, frame_end = frame_range

    # Ensure rep is active and in pose mode
    if context.view_layer.objects.active != rep:
        context.view_layer.objects.active = rep
    if rep.mode != "POSE":
        bpy.ops.object.mode_set(mode="POSE")

    # Select only tweak bones on rep
    bpy.ops.pose.select_all(action="DESELECT")
    for name in names:
        rep.pose.bones[name].select = True

    # Bake
    try:
        bpy.ops.nla.bake(
            frame_start=frame_start,
            frame_end=frame_end,
            step=1,
            only_selected=True,
            visual_keying=True,
            clear_constraints=True,
            clear_parents=True,
            use_current_action=True,
            clean_curves=False,
            bake_types={"POSE"},
            channel_types={"LOCATION", "ROTATION"},
        )
    except Exception as e:
        return False, str(e)

    if not post_clean:
        return True, f"Baked {len(names)} tweak bones ({frame_start}-{frame_end})."

    # Post-clean: find an area we can use for action/graph ops
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

    return True, f"Baked and cleaned {len(names)} tweak bones ({frame_start}-{frame_end})."
