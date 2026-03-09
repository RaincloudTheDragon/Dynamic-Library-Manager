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
            try:
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
            except Exception as e:
                print(f"[DLM MigFKRot] Failed to add constraint for {bone_name}: {e}")

        # Step 2: Update scene to evaluate constraints
        context.view_layer.update()

        # Step 3: Apply visual transform (bake constraint result into pose)
        bpy.ops.pose.select_all(action='DESELECT')
        for rep_bone, _ in constraints_added:
            rep_bone.bone.select = True
        
        # Apply visual transform - this bakes the constraint result
        bpy.ops.pose.visual_transform_apply()

        # Step 4: Remove constraints
        for rep_bone, c in constraints_added:
            try:
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
