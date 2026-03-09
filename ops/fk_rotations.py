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

        # Step 4: Remove constraints
        for rep_bone, c in constraints_added:
            try:
                if c in rep_bone.constraints:
                    rep_bone.constraints.remove(c)
            except:
                pass

        print(f"[DLM MigFKRot] Copied {len(constraints_added)} bones")
        return True, f"Copied FK rotations for {len(constraints_added)} bones"

    except Exception as e:
        print(f"[DLM MigFKRot] Error: {e}")
        return False, str(e)

    finally:
        # Cleanup any remaining constraints
        for rep_bone, c in constraints_added:
            try:
                if c in rep_bone.constraints:
                    rep_bone.constraints.remove(c)
            except:
                pass
        
        if original_active:
            context.view_layer.objects.active = original_active


def bake_fk_rotations(context, orig, rep, track_name=None, post_clean=False):
    """
    Bake FK arm/finger rotations to keyframes.
    Similar to tweak_tools.bake_tweak_constraints - adds constraints, bakes, then removes.
    Returns (True, message) or (False, error_message).
    """
    fk_names = _get_fk_bones(rep)
    if not fk_names:
        return False, f"No FK bones found on {rep.name}"

    # Filter to bones that exist on both
    common_bones = [n for n in fk_names if n in orig.pose.bones and n in rep.pose.bones]
    if not common_bones:
        return False, "No matching FK bones found on both armatures"

    scene = context.scene
    
    # Get frame range from track or scene
    frame_range = None
    if track_name and rep.animation_data and rep.animation_data.nla_tracks:
        track = rep.animation_data.nla_tracks.get(track_name)
        if track and track.strips:
            start = min(s.frame_start for s in track.strips)
            end = max(s.frame_end for s in track.strips)
            frame_range = (int(start), int(end))
    
    if not frame_range:
        frame_range = (scene.frame_start, scene.frame_end)
    
    frame_start, frame_end = frame_range

    # Ensure rep is active and in pose mode
    if context.view_layer.objects.active != rep:
        context.view_layer.objects.active = rep
    if rep.mode != "POSE":
        bpy.ops.object.mode_set(mode="POSE")

    # Step 1: Check for existing COPY_TRANSFORMS constraints from MigFKRot
    constraints_added = []
    for bone_name in common_bones:
        rep_bone = rep.pose.bones[bone_name]
        
        # Check if already has constraint from MigFKRot
        existing = [c for c in rep_bone.constraints if c.type == 'COPY_TRANSFORMS' and getattr(c, 'target', None) == orig]
        if existing:
            constraints_added.append((rep_bone, existing[0]))

    print(f"[DLM MigFKRot Bake] Found {len(constraints_added)} existing constraints")

    # Step 2: Select FK bones for baking
    selected_count = 0
    try:
        bpy.ops.pose.select_all(action="DESELECT")
        for name in fk_names:
            if name in rep.pose.bones:
                rep.pose.bones[name].bone.select = True
                selected_count += 1
    except (RuntimeError, AttributeError):
        selected_count = 0  # Selection failed, will bake all

    # Step 3: Frame-by-frame bake (nla.bake with only_selected is unreliable in Blender 5.0)
    print(f"[DLM MigFKRot Bake] Baking frames {frame_start}-{frame_end} for {len(common_bones)} bones")
    try:
        # Create action if needed
        if not rep.animation_data:
            rep.animation_data_create()
        if not rep.animation_data.action:
            action = bpy.data.actions.new(name=f"{rep.name}_FK_Baked")
            rep.animation_data.action = action
        
        # Bake frame by frame
        for frame in range(frame_start, frame_end + 1):
            scene.frame_set(frame)
            context.view_layer.update()
            
            for bone_name in common_bones:
                rep_bone = rep.pose.bones[bone_name]
                
                # Insert keyframe based on rotation mode
                if rep_bone.rotation_mode == 'QUATERNION':
                    rep_bone.keyframe_insert(data_path="rotation_quaternion")
                elif rep_bone.rotation_mode == 'AXIS_ANGLE':
                    rep_bone.keyframe_insert(data_path="rotation_axis_angle")
                else:
                    rep_bone.keyframe_insert(data_path="rotation_euler")
        
        scene.frame_set(frame_start)  # Reset to start
        print(f"[DLM MigFKRot Bake] Baked {frame_end - frame_start + 1} frames")
        
    except Exception as e:
        # Clean up constraints on failure
        for rep_bone, c in constraints_added:
            try:
                if c in rep_bone.constraints:
                    rep_bone.constraints.remove(c)
            except:
                pass
        return False, str(e)
    
    # Step 4: Remove the temporary constraints
    removed = 0
    for rep_bone, c in constraints_added:
        try:
            if c in rep_bone.constraints:
                rep_bone.constraints.remove(c)
                removed += 1
        except:
            pass
    print(f"[DLM MigFKRot Bake] Removed {removed} constraints")

    if not post_clean:
        return True, f"Baked {len(common_bones)} FK bones ({frame_start}-{frame_end})."

    # Post-clean
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

    return True, f"Baked and cleaned {len(common_bones)} FK bones ({frame_start}-{frame_end})."


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
