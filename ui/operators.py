# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import bpy
from bpy.types import Operator
from bpy.props import BoolProperty

from ..utils.remove_original import run_remove_original


class DLM_OT_make_paths_relative(Operator):
    bl_idname = "dlm.make_paths_relative"
    bl_label = "Make Paths Relative"
    bl_description = "Convert all internal file paths to relative"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            bpy.ops.file.make_paths_relative()
            self.report({"INFO"}, "All file paths made relative")
        except Exception as e:
            self.report({"ERROR"}, f"Failed to make paths relative: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class DLM_OT_make_paths_absolute(Operator):
    bl_idname = "dlm.make_paths_absolute"
    bl_label = "Make Paths Absolute"
    bl_description = "Convert all internal file paths to absolute"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            bpy.ops.file.make_paths_absolute()
            self.report({"INFO"}, "All file paths made absolute")
        except Exception as e:
            self.report({"ERROR"}, f"Failed to make paths absolute: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}


def _get_migrator_pair(context):
    """Return (orig, rep) from scene props (manual or automatic). (None, None) if invalid."""
    from ..ops.migrator import get_pair_manual, get_pair_automatic, resolve_migration_pair

    props = getattr(context.scene, "dynamic_link_manager", None)
    if not props:
        return None, None
    use_auto = getattr(props, "migrator_mode", False)
    orig, rep = get_pair_automatic(context) if use_auto else get_pair_manual(context)
    orig, rep = resolve_migration_pair(orig, rep, context.scene)
    if rep is not None and props.replacement_character != rep:
        props.replacement_character = rep
    return orig, rep


class DLM_OT_migrator_copy_attributes(Operator):
    bl_idname = "dlm.migrator_copy_attributes"
    bl_label = "CopyAttr"
    bl_description = "Copy object and armature attributes from original to replacement character"
    bl_icon = "COPY_ID"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        if not orig or not rep or orig == rep:
            self.report({"ERROR"}, "No valid character pair (set Original/Replacement or enable Automatic).")
            return {"CANCELLED"}
        try:
            from ..ops.migrator import run_copy_attr
            run_copy_attr(orig, rep)
            self.report({"INFO"}, "Copy attributes done.")
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}


class DLM_OT_migrator_migrate_nla(Operator):
    bl_idname = "dlm.migrator_migrate_nla"
    bl_label = "MigNLA"
    bl_description = "Migrate NLA tracks and strips from original to replacement character"
    bl_icon = "NLA"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        if not orig or not rep or orig == rep:
            self.report({"ERROR"}, "No valid character pair.")
            return {"CANCELLED"}
        try:
            from ..ops.migrator import run_mig_nla
            run_mig_nla(orig, rep, report=self.report, context=context)
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}


class DLM_OT_migrator_custom_properties(Operator):
    bl_idname = "dlm.migrator_custom_properties"
    bl_label = "MigCustProps"
    bl_description = "Copy custom properties from original to replacement character"
    bl_icon = "PROPERTIES"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        if not orig or not rep or orig == rep:
            self.report({"ERROR"}, "No valid character pair.")
            return {"CANCELLED"}
        try:
            from ..ops.migrator import run_mig_cust_props
            run_mig_cust_props(orig, rep)
            self.report({"INFO"}, "Custom properties done.")
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}


class DLM_OT_migrator_object_constraints(Operator):
    bl_idname = "dlm.migrator_object_constraints"
    bl_label = "MigObjConst"
    bl_description = (
        "Migrate armature object constraints (Follow Path, Copy Location, etc.) "
        "from original to replacement"
    )
    bl_icon = "CONSTRAINT"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        if not orig or not rep or orig == rep:
            self.report({"ERROR"}, "No valid character pair.")
            return {"CANCELLED"}
        try:
            from ..ops.migrator import run_mig_obj_const

            orig_to_rep = {orig: rep}
            run_mig_obj_const(orig, rep, orig_to_rep)
            self.report({"INFO"}, "Object constraints done.")
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}


class DLM_OT_migrator_object_relatives(Operator):
    bl_idname = "dlm.migrator_object_relatives"
    bl_label = "MigObjRelatives"
    bl_description = (
        "Copy armature object parenting from original to replacement "
        "(e.g. character parented to a cart/path empty)"
    )
    bl_icon = "OBJECT_ORIGIN"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        if not orig or not rep or orig == rep:
            self.report({"ERROR"}, "No valid character pair.")
            return {"CANCELLED"}
        try:
            from ..ops.migrator import run_mig_obj_relatives

            rep = run_mig_obj_relatives(orig, rep, {orig: rep}, context.scene)
            props = context.scene.dynamic_link_manager
            if rep is not None and props.replacement_character != rep:
                props.replacement_character = rep
            self.report({"INFO"}, "Object relatives done.")
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}


class DLM_OT_migrator_bone_constraints(Operator):
    bl_idname = "dlm.migrator_bone_constraints"
    bl_label = "MigBoneConst"
    bl_description = "Migrate bone constraints from original to replacement armature"
    bl_icon = "CONSTRAINT_BONE"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        if not orig or not rep or orig == rep:
            self.report({"ERROR"}, "No valid character pair.")
            return {"CANCELLED"}
        try:
            from ..ops.migrator import run_mig_bone_const
            orig_to_rep = {orig: rep}
            run_mig_bone_const(orig, rep, orig_to_rep)
            self.report({"INFO"}, "Bone constraints done.")
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}


class DLM_OT_migrator_retarget_relations(Operator):
    bl_idname = "dlm.migrator_retarget_relations"
    bl_label = "RetargRelatives"
    bl_description = "Retarget parent/child and other relations to the replacement character"
    bl_icon = "ORIENTATION_PARENT"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        if not orig or not rep or orig == rep:
            self.report({"ERROR"}, "No valid character pair.")
            return {"CANCELLED"}
        try:
            from ..ops.migrator import run_retarg_relatives
            from ..utils import descendants
            rep_descendants = descendants(rep)
            orig_to_rep = {orig: rep}
            run_retarg_relatives(orig, rep, rep_descendants, orig_to_rep)
            self.report({"INFO"}, "Retarget relations done.")
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}


class DLM_OT_migrator_basebody_shapekeys(Operator):
    bl_idname = "dlm.migrator_basebody_shapekeys"
    bl_label = "MigBBodyShapeKeys"
    bl_description = "Migrate base body mesh shape key values from original to replacement"
    bl_icon = "SHAPEKEY_DATA"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        if not orig or not rep or orig == rep:
            self.report({"ERROR"}, "No valid character pair.")
            return {"CANCELLED"}
        try:
            from ..ops.migrator import run_mig_bbody_shapekeys
            from ..utils import descendants
            rep_descendants = descendants(rep)
            run_mig_bbody_shapekeys(orig, rep, rep_descendants, context)
            props = context.scene.dynamic_link_manager
            if props.migbbody_manual_override and (
                not props.migbbody_orig_body or not props.migbbody_rep_body
            ):
                self.report(
                    {"WARNING"},
                    "MigBBody: no CC-style base mesh matched. Pick Original/Replacement body meshes, then run again.",
                )
            else:
                self.report({"INFO"}, "Migrate BaseBody shapekeys done.")
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}


class DLM_OT_migrator_fk_rotations(Operator):
    bl_idname = "dlm.migrator_fk_rotations"
    bl_label = "MigFKRot"
    bl_description = "Copy FK arm and finger rotations from original to replacement (uses constraints)"
    bl_icon = "BONE_DATA"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        if not orig or not rep or orig == rep:
            self.report({"ERROR"}, "No valid character pair.")
            return {"CANCELLED"}
        try:
            from ..ops.fk_rotations import copy_fk_rotations
            ok, msg = copy_fk_rotations(context, orig, rep)
            if ok:
                self.report({"INFO"}, msg)
                return {"FINISHED"}
            else:
                self.report({"ERROR"}, msg)
                return {"CANCELLED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}


class DLM_OT_migrator_fk_rotations_bake(Operator):
    bl_idname = "dlm.migrator_fk_rotations_bake"
    bl_label = "Bake MigFKRot"
    bl_description = "Bake FK rotations to keyframes using nla.bake (similar to tweak tools)"
    bl_icon = "KEYFRAME"
    bl_options = {"REGISTER", "UNDO"}

    track_name: StringProperty(name="NLA Track", description="Optional NLA track name for frame range", default="")
    post_clean: BoolProperty(name="Post-clean", description="Clean curves after bake", default=False)

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        if not orig or not rep or orig == rep:
            self.report({"ERROR"}, "No valid character pair.")
            return {"CANCELLED"}
        try:
            from ..ops.fk_rotations import bake_fk_rotations
            ok, msg = bake_fk_rotations(context, orig, rep, track_name=self.track_name or None, post_clean=self.post_clean)
            if ok:
                self.report({"INFO"}, msg)
                return {"FINISHED"}
            else:
                self.report({"ERROR"}, msg)
                return {"CANCELLED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}


class DLM_OT_migrator_fk_rotations_remove(Operator):
    bl_idname = "dlm.migrator_fk_rotations_remove"
    bl_label = "Remove MigFKRot"
    bl_description = "Remove FK rotation COPY_TRANSFORMS constraints (similar to tweak_remove_arm)"
    bl_icon = "X"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        if not orig or not rep or orig == rep:
            self.report({"ERROR"}, "No valid character pair.")
            return {"CANCELLED"}
        try:
            from ..ops.fk_rotations import remove_fk_rotations
            ok, msg = remove_fk_rotations(context, rep)
            if ok:
                self.report({"INFO"}, msg)
                return {"FINISHED"}
            else:
                self.report({"ERROR"}, msg)
                return {"CANCELLED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}




class DLM_OT_migrator_remove_original(Operator):
    bl_idname = "dlm.migrator_remove_original"
    bl_label = "Remove Original"
    bl_description = "Delete the original character armature and its data from the scene"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        if not orig:
            self.report({"WARNING"}, "No original character selected")
            return {"CANCELLED"}
        if orig == rep:
            self.report({"ERROR"}, "Original and replacement cannot be the same object")
            return {"CANCELLED"}

        if not run_remove_original(context, orig, rep, self.report):
            return {"CANCELLED"}
        return {"FINISHED"}

class DLM_OT_picker_original_character(Operator):
    bl_idname = "dlm.picker_original_character"
    bl_label = "Pick Original"
    bl_description = "Set the original character armature from the active object"
    bl_options = {"REGISTER"}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != "ARMATURE":
            self.report({"WARNING"}, "Select an armature")
            return {"CANCELLED"}
        context.scene.dynamic_link_manager.original_character = obj
        self.report({"INFO"}, f"Original: {obj.name}")
        return {"FINISHED"}


class DLM_OT_picker_replacement_character(Operator):
    bl_idname = "dlm.picker_replacement_character"
    bl_label = "Pick Replacement"
    bl_description = "Set the replacement character armature from the active object"
    bl_options = {"REGISTER"}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != "ARMATURE":
            self.report({"WARNING"}, "Select an armature")
            return {"CANCELLED"}
        context.scene.dynamic_link_manager.replacement_character = obj
        self.report({"INFO"}, f"Replacement: {obj.name}")
        return {"FINISHED"}


def _tweak_poll(context):
    orig, rep = _get_migrator_pair(context)
    return orig is not None and rep is not None


class DLM_OT_tweak_add_arm(Operator):
    bl_idname = "dlm.tweak_add_arm"
    bl_label = "Add Arm Tweaks"
    bl_description = "Add tweak bone constraints to arm bones on the replacement character"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _tweak_poll(context)

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        from ..ops import tweak_tools
        tweak_tools.add_tweak_constraints(orig, rep, "arm")
        self.report({"INFO"}, "Arm tweak constraints added.")
        return {"FINISHED"}


class DLM_OT_tweak_remove_arm(Operator):
    bl_idname = "dlm.tweak_remove_arm"
    bl_label = "Remove Arm Tweaks"
    bl_description = "Remove arm tweak constraints from the replacement character"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _tweak_poll(context)

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        from ..ops import tweak_tools
        n = tweak_tools.remove_tweak_constraints(orig, rep, "arm")
        self.report({"INFO"}, f"Removed {n} arm tweak constraints.")
        return {"FINISHED"}


class DLM_OT_tweak_bake_arm(Operator):
    bl_idname = "dlm.tweak_bake_arm"
    bl_label = "Bake Arm Tweaks"
    bl_description = "Bake arm tweak constraints to keyframes and optionally remove constraints"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _tweak_poll(context)

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        props = context.scene.dynamic_link_manager
        from ..ops import tweak_tools
        ok, msg = tweak_tools.bake_tweak_constraints(
            context, orig, rep, "arm",
            getattr(props, "tweak_nla_track_name", "") or "",
            getattr(props, "tweak_bake_post_clean", False),
        )
        if ok:
            self.report({"INFO"}, msg)
            return {"FINISHED"}
        self.report({"ERROR"}, msg)
        return {"CANCELLED"}


class DLM_OT_tweak_add_leg(Operator):
    bl_idname = "dlm.tweak_add_leg"
    bl_label = "Add Leg Tweaks"
    bl_description = "Add tweak bone constraints to leg bones on the replacement character"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _tweak_poll(context)

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        from ..ops import tweak_tools
        tweak_tools.add_tweak_constraints(orig, rep, "leg")
        self.report({"INFO"}, "Leg tweak constraints added.")
        return {"FINISHED"}


class DLM_OT_tweak_remove_leg(Operator):
    bl_idname = "dlm.tweak_remove_leg"
    bl_label = "Remove Leg Tweaks"
    bl_description = "Remove leg tweak constraints from the replacement character"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _tweak_poll(context)

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        from ..ops import tweak_tools
        n = tweak_tools.remove_tweak_constraints(orig, rep, "leg")
        self.report({"INFO"}, f"Removed {n} leg tweak constraints.")
        return {"FINISHED"}


class DLM_OT_tweak_bake_leg(Operator):
    bl_idname = "dlm.tweak_bake_leg"
    bl_label = "Bake Leg Tweaks"
    bl_description = "Bake leg tweak constraints to keyframes and optionally remove constraints"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _tweak_poll(context)

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        props = context.scene.dynamic_link_manager
        from ..ops import tweak_tools
        ok, msg = tweak_tools.bake_tweak_constraints(
            context, orig, rep, "leg",
            getattr(props, "tweak_nla_track_name", "") or "",
            getattr(props, "tweak_bake_post_clean", False),
        )
        if ok:
            self.report({"INFO"}, msg)
            return {"FINISHED"}
        self.report({"ERROR"}, msg)
        return {"CANCELLED"}


class DLM_OT_tweak_add_body(Operator):
    bl_idname = "dlm.tweak_add_body"
    bl_label = "Add Body Tweaks"
    bl_description = "Add tweak bone constraints to body/torso bones (spine, no arm/leg)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _tweak_poll(context)

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        from ..ops import tweak_tools
        tweak_tools.add_tweak_constraints(orig, rep, "body")
        self.report({"INFO"}, "Body tweak constraints added.")
        return {"FINISHED"}


class DLM_OT_tweak_remove_body(Operator):
    bl_idname = "dlm.tweak_remove_body"
    bl_label = "Remove Body Tweaks"
    bl_description = "Remove body/torso tweak constraints from the replacement character"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _tweak_poll(context)

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        from ..ops import tweak_tools
        n = tweak_tools.remove_tweak_constraints(orig, rep, "body")
        self.report({"INFO"}, f"Removed {n} body tweak constraints.")
        return {"FINISHED"}


class DLM_OT_tweak_bake_body(Operator):
    bl_idname = "dlm.tweak_bake_body"
    bl_label = "Bake Body Tweaks"
    bl_description = "Bake body/torso tweak constraints to keyframes and optionally remove constraints"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _tweak_poll(context)

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        props = context.scene.dynamic_link_manager
        from ..ops import tweak_tools
        ok, msg = tweak_tools.bake_tweak_constraints(
            context, orig, rep, "body",
            getattr(props, "tweak_nla_track_name", "") or "",
            getattr(props, "tweak_bake_post_clean", False),
        )
        if ok:
            self.report({"INFO"}, msg)
            return {"FINISHED"}
        self.report({"ERROR"}, msg)
        return {"CANCELLED"}


class DLM_OT_tweak_add_both(Operator):
    bl_idname = "dlm.tweak_add_both"
    bl_label = "Add All Tweaks"
    bl_description = "Add tweak bone constraints to all tweak bones (arm, leg, body)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _tweak_poll(context)

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        from ..ops import tweak_tools
        tweak_tools.add_tweak_constraints(orig, rep, "both")
        self.report({"INFO"}, "All tweak constraints added.")
        return {"FINISHED"}


class DLM_OT_tweak_remove_both(Operator):
    bl_idname = "dlm.tweak_remove_both"
    bl_label = "Remove All Tweaks"
    bl_description = "Remove all tweak constraints from the replacement character"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _tweak_poll(context)

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        from ..ops import tweak_tools
        n = tweak_tools.remove_tweak_constraints(orig, rep, "both")
        self.report({"INFO"}, f"Removed {n} tweak constraints.")
        return {"FINISHED"}


class DLM_OT_tweak_bake_both(Operator):
    bl_idname = "dlm.tweak_bake_both"
    bl_label = "Bake All Tweaks"
    bl_description = "Bake all tweak constraints (arm, leg, body) to keyframes and optionally remove constraints"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _tweak_poll(context)

    def execute(self, context):
        orig, rep = _get_migrator_pair(context)
        props = context.scene.dynamic_link_manager
        from ..ops import tweak_tools
        ok, msg = tweak_tools.bake_tweak_constraints(
            context, orig, rep, "both",
            getattr(props, "tweak_nla_track_name", "") or "",
            getattr(props, "tweak_bake_post_clean", False),
        )
        if ok:
            self.report({"INFO"}, msg)
            return {"FINISHED"}
        self.report({"ERROR"}, msg)
        return {"CANCELLED"}


OPERATOR_CLASSES = [
    DLM_OT_make_paths_relative,
    DLM_OT_make_paths_absolute,
    DLM_OT_migrator_remove_original,
    DLM_OT_picker_original_character,
    DLM_OT_picker_replacement_character,
    DLM_OT_migrator_copy_attributes,
    DLM_OT_migrator_migrate_nla,
    DLM_OT_migrator_custom_properties,
    DLM_OT_migrator_object_constraints,
    DLM_OT_migrator_object_relatives,
    DLM_OT_migrator_bone_constraints,
    DLM_OT_migrator_retarget_relations,
    DLM_OT_migrator_basebody_shapekeys,
    DLM_OT_tweak_add_arm,
    DLM_OT_tweak_remove_arm,
    DLM_OT_tweak_bake_arm,
    DLM_OT_tweak_add_leg,
    DLM_OT_tweak_remove_leg,
    DLM_OT_tweak_bake_leg,
    DLM_OT_tweak_add_body,
    DLM_OT_tweak_remove_body,
    DLM_OT_tweak_bake_body,
    DLM_OT_tweak_add_both,
    DLM_OT_tweak_remove_both,
    DLM_OT_tweak_bake_both,
    DLM_OT_migrator_fk_rotations,
    DLM_OT_migrator_fk_rotations_bake,
    DLM_OT_migrator_fk_rotations_remove,
]
