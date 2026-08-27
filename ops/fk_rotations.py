# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

"""FK rotations: copy visible rotations from original to replacement using constraints."""

import bpy

from ..utils.nla_bake import activate_topmost_nla, bake_pose_to_replace_layer

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
        activate_topmost_nla(context, orig, log_prefix="[DLM MigFKRot]")
        activate_topmost_nla(context, rep, log_prefix="[DLM MigFKRot]")
        context.view_layer.update()

        # Ensure rep is active and in pose mode
        bpy.context.view_layer.objects.active = rep
        if rep.mode != "POSE":
            bpy.ops.object.mode_set(mode="POSE")

        # Step 1: Add COPY_TRANSFORMS constraints to each rep bone
        for bone_name in common_bones:
            rep_bone = rep.pose.bones[bone_name]

            # Check if bone already has this constraint
            existing = [
                c for c in rep_bone.constraints
                if c.type == "COPY_TRANSFORMS" and getattr(c, "target", None) == orig
            ]
            if existing:
                continue

            # Add constraint
            c = rep_bone.constraints.new(type="COPY_TRANSFORMS")
            c.name = "MigFKRot_Temp"
            c.target = orig
            c.subtarget = bone_name
            c.target_space = "POSE"
            c.owner_space = "POSE"
            constraints_added.append((rep_bone, c))

        # Step 2: Update scene to evaluate constraints
        context.view_layer.update()

        # Step 3: Apply visual transform (bake constraint result into pose)
        try:
            bpy.ops.pose.select_all(action="DESELECT")
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
        return True, (
            f"Copied FK rotations for {len(constraints_added)} bones "
            "(constraints active - run Bake to finalize)"
        )

    except Exception as e:
        print(f"[DLM MigFKRot] Error: {e}")
        # Cleanup constraints on error
        for rep_bone, c in constraints_added:
            try:
                if c in rep_bone.constraints:
                    rep_bone.constraints.remove(c)
            except Exception:
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


def _remove_migfkrot_temp_constraints(rep, fk_names):
    """Remove COPY_TRANSFORMS named MigFKRot_Temp (RNA refs from bake are often stale)."""
    removed = 0
    for bone_name in fk_names:
        pb = rep.pose.bones.get(bone_name)
        if not pb:
            continue
        for c in [
            c for c in pb.constraints
            if c.name == "MigFKRot_Temp"
            or (c.type == "COPY_TRANSFORMS" and c.name.startswith("MigFKRot"))
        ]:
            try:
                pb.constraints.remove(c)
                removed += 1
            except Exception:
                pass
    return removed


def bake_fk_rotations(context, orig, rep, track_name=None, post_clean=False):
    """
    Bake FK arm/finger rotations to a dedicated top REPLACE NLA/ALS layer.
    Returns (True, message) or (False, error_message).
    """
    print(f"[DLM MigFKRot Bake] START: orig={orig.name}, rep={rep.name}")

    fk_names = _get_fk_bones(rep)
    print(f"[DLM MigFKRot Bake] Found {len(fk_names)} FK bones: {fk_names[:5]}...")

    if not fk_names:
        return False, f"No FK bones found on {rep.name}"

    common_bones = [n for n in fk_names if n in orig.pose.bones and n in rep.pose.bones]
    print(f"[DLM MigFKRot Bake] {len(common_bones)} common bones between orig and rep")

    if not common_bones:
        return False, "No matching FK bones found on both armatures"

    # Frame range from source action keyframes, else scene range
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

    frame_range = _get_action_frame_range(source_action) if source_action else None
    if not frame_range:
        frame_range = (context.scene.frame_start, context.scene.frame_end)
    frame_start, frame_end = frame_range

    constraints_added = 0
    for bone_name in common_bones:
        rep_bone = rep.pose.bones[bone_name]
        existing = [
            c for c in rep_bone.constraints
            if c.type == "COPY_TRANSFORMS" and getattr(c, "target", None) == orig
        ]
        if existing:
            constraints_added += 1
    print(f"[DLM MigFKRot Bake] Found {constraints_added} constraints from {orig.name} to {rep.name}")
    print(f"[DLM MigFKRot Bake] Frame range: {frame_start}-{frame_end}")

    base_name = (track_name or "").strip() or f"FK_Bake_{frame_start}-{frame_end}"
    ok, msg, _track, _action = bake_pose_to_replace_layer(
        context,
        orig,
        rep,
        common_bones,
        frame_start=frame_start,
        frame_end=frame_end,
        layer_name=base_name,
        channel_types={"ROTATION"},
        clear_constraints=False,
        clear_parents=False,
        post_clean=post_clean,
        log_prefix="[DLM MigFKRot Bake]",
    )
    if not ok:
        return False, msg

    removed_count = _remove_migfkrot_temp_constraints(rep, common_bones)
    print(f"[DLM MigFKRot Bake] Removed {removed_count} constraints")

    if post_clean:
        return True, (
            f"Baked and cleaned {len(common_bones)} FK bones to NLA track "
            f"({frame_start}-{frame_end})."
        )
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

    removed = _remove_migfkrot_temp_constraints(rep, fk_names)
    return True, f"Removed {removed} FK rotation constraints."
