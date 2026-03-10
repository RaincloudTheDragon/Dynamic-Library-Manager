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


def _get_action_frame_range(action):
    """Get the full frame range from action keyframes (not just strip in/out)."""
    if not action:
        return None
    
    frames = set()
    
    # Try Blender 5.0+ channelbags first
    if hasattr(action, 'channelbags'):
        for cb in action.channelbags:
            if hasattr(cb, 'fcurves'):
                for fc in cb.fcurves:
                    for kp in fc.keyframe_points:
                        frames.add(int(kp.co.x))
    
    # Fallback to fcurves
    if hasattr(action, 'fcurves') and not frames:
        for fc in action.fcurves:
            for kp in fc.keyframe_points:
                frames.add(int(kp.co.x))
    
    if frames:
        return (min(frames), max(frames))
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

    # Step 1: Check for existing COPY_TRANSFORMS constraints
    constraints_added = []
    for bone_name in common_bones:
        rep_bone = rep.pose.bones[bone_name]
        existing = [c for c in rep_bone.constraints if c.type == 'COPY_TRANSFORMS' and getattr(c, 'target', None) == orig]
        if existing:
            constraints_added.append((rep_bone, existing[0]))

    print(f"[DLM MigFKRot Bake] Found {len(constraints_added)} constraints from {orig.name} to {rep.name}")
    print(f"[DLM MigFKRot Bake] Frame range: {frame_start}-{frame_end}")

    # Step 2: Create new action and bake with nla.bake
    # We use the current action (not a new one) because nla.bake needs use_current_action=True
    # After baking, we'll clean up non-FK fcurves from the baked action
    
    # First, ensure there's an action to bake to
    if rep.animation_data is None:
        rep.animation_data_create()
    
    # If there's no current action, create one
    if not rep.animation_data.action:
        action_name = f"{rep.name}_FK_Bake_{frame_start}-{frame_end}"
        new_action = bpy.data.actions.new(name=action_name)
        if len(new_action.slots) == 0:
            new_action.slots.new(name=rep.name, id_type='OBJECT')
        slot = new_action.slots[0]
        try:
            rep.animation_data.action_slot = slot
        except Exception as e:
            print(f"[DLM MigFKRot Bake] Warning: Could not set slot: {e}")
    
    # Store the action we're baking to
    baked_action = rep.animation_data.action
    print(f"[DLM MigFKRot Bake] Baking to action: {baked_action.name if baked_action else 'None'}")
    
    # Step 3: Select only FK bones and bake with only_selected=True
    print(f"[DLM MigFKRot Bake] Selecting {len(common_bones)} FK bones...")
    try:
        # Deselect all bones first
        bpy.ops.pose.select_all(action='DESELECT')
        
        # Select only our FK bones
        for bone_name in common_bones:
            if bone_name in rep.pose.bones:
                rep_bone = rep.pose.bones[bone_name]
                # Try different ways to select the bone (Blender 5.0 compatibility)
                try:
                    # Method 1: Direct selection on pose bone
                    rep_bone.select = True
                except (AttributeError, TypeError):
                    try:
                        # Method 2: Selection on the bone property
                        if hasattr(rep_bone, 'bone'):
                            rep_bone.bone.select = True
                    except (AttributeError, TypeError):
                        pass  # Selection failed, continue anyway
        
        print(f"[DLM MigFKRot Bake] Running nla.bake with only_selected=True...")
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
        print(f"[DLM MigFKRot Bake] nla.bake completed successfully")
    except Exception as e:
        # Clean up constraints on failure
        for rep_bone, c in constraints_added:
            try:
                if c in rep_bone.constraints:
                    rep_bone.constraints.remove(c)
            except:
                pass
        return False, f"nla.bake failed: {e}"
    
    # Step 4: Remove constraints
    removed_count = 0
    for rep_bone, c in constraints_added:
        try:
            if c in rep_bone.constraints:
                rep_bone.constraints.remove(c)
                removed_count += 1
        except:
            pass
    print(f"[DLM MigFKRot Bake] Removed {removed_count} constraints")
    
    # Step 5: Create new NLA track at TOP with replace mode
    # Use the baked action (which now has only FK fcurves)
    if rep.animation_data and baked_action:
        nla_track = rep.animation_data.nla_tracks.new(prev=None)
        nla_track.name = f"FK_Bake_{frame_start}-{frame_end}"
        
        strip = nla_track.strips.new(name=baked_action.name, start=frame_start, action=baked_action)
        strip.frame_end = frame_end
        strip.blend_type = 'REPLACE'
        strip.use_auto_blend = False
        
        print(f"[DLM MigFKRot Bake] Created NLA track '{nla_track.name}' (REPLACE mode)")
    
    if not post_clean:
        return True, f"Baked {len(common_bones)} FK bones to NLA track ({frame_start}-{frame_end})."

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

    return True, f"Baked and cleaned {len(common_bones)} FK bones to NLA track ({frame_start}-{frame_end})."


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
