# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import bpy
from bpy.types import Panel


class DLM_PT_main_panel(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Dynamic Link Manager"
    bl_label = "Dynamic Link Manager"

    def draw_header(self, context):
        layout = self.layout
        layout.operator("preferences.addon_show", text="", icon="PREFERENCES").module = __package__.rsplit(".", 1)[0]

    def draw(self, context):
        layout = self.layout
        props = context.scene.dynamic_link_manager

        # Path management
        row = layout.row()
        row.operator("dlm.make_paths_relative", text="Make Paths Relative", icon="FILE_PARENT")
        row.operator("dlm.make_paths_absolute", text="Make Paths Absolute", icon="FILE_FOLDER")
        row = layout.row()
        # Label becomes Continue when session status is stubs_ready (operator handles both).
        from ..utils import stub_handoff

        session = stub_handoff.load_session()
        status = (session or {}).get("status")
        btn = "Continue" if status == stub_handoff.STATUS_STUBS_READY else "Symlink Propagation"
        row.operator("dlm.symlink_propagation", text=btn, icon="LINKED")

        # Character Migrator: core + situational fixes + tweak tools under one section
        section_icon = "DISCLOSURE_TRI_DOWN" if props.charmig_section_expanded else "DISCLOSURE_TRI_RIGHT"
        row = layout.row(align=True)
        row.prop(props, "charmig_section_expanded", text="", icon=section_icon, icon_only=True)
        row.label(text="Character Migrator", icon="ARMATURE_DATA")
        if props.charmig_section_expanded:
            box = layout.box()
            row = box.row()
            row.prop(props, "migrator_rig_family", expand=True)
            row = box.row()
            row.prop(props, "migrator_mode", text="Automatic pair discovery")
            row = box.row()
            row.prop(props, "original_character", text="Original")
            row.operator("dlm.picker_original_character", text="", icon="EYEDROPPER")
            row = box.row()
            row.prop(props, "replacement_character", text="Replacement")
            row.operator("dlm.picker_replacement_character", text="", icon="EYEDROPPER")
            row = box.row()
            row.operator("dlm.migrator_remove_original", text="Remove Original", icon="TRASH")
            row = box.row(align=True)
            row.operator("dlm.migrator_copy_attributes", text="CopyAttr", icon="COPY_ID")
            row.operator("dlm.migrator_migrate_nla", text="MigNLA", icon="NLA")
            row.operator("dlm.migrator_custom_properties", text="MigCustProps", icon="PROPERTIES")
            row = box.row(align=True)
            row.operator("dlm.migrator_object_constraints", text="MigObjConst", icon="CONSTRAINT")
            row.operator("dlm.migrator_object_relatives", text="MigObjRelatives", icon="OBJECT_ORIGIN")
            row = box.row(align=True)
            row.operator("dlm.migrator_bone_constraints", text="MigBoneConst", icon="CONSTRAINT_BONE")
            row.operator("dlm.migrator_retarget_relations", text="RetargRelatives", icon="ORIENTATION_PARENT")

            box.separator()
            box.label(text="Situational Fixes", icon="QUESTION")
            row = box.row()
            row.prop(props, "migbbody_manual_override", text="Manual body meshes")
            row = box.row()
            row.enabled = props.migbbody_manual_override
            row.prop(props, "migbbody_orig_body", text="Original body")
            row = box.row()
            row.enabled = props.migbbody_manual_override
            row.prop(props, "migbbody_rep_body", text="Replacement body")
            row = box.row(align=True)
            row.operator("dlm.migrator_basebody_shapekeys", text="MigBBodyShapeKeys", icon="SHAPEKEY_DATA")
            row = box.row(align=True)
            row.operator("dlm.migrator_fk_rotations", text="MigFKRot", icon="BONE_DATA")
            row.operator("dlm.migrator_fk_rotations_remove", text="Remove", icon="X")
            row.operator("dlm.migrator_fk_rotations_bake", text="Bake", icon="KEYFRAME")

            box.separator()
            tweak_icon = "DISCLOSURE_TRI_DOWN" if props.tweak_tools_section_expanded else "DISCLOSURE_TRI_RIGHT"
            row = box.row(align=True)
            row.prop(props, "tweak_tools_section_expanded", text="", icon=tweak_icon, icon_only=True)
            row.label(text="Tweak Tools", icon="CONSTRAINT")
            if props.tweak_tools_section_expanded:
                row = box.row(align=True)
                row.operator("dlm.tweak_add_arm", text="Add Arm", icon="CONSTRAINT_BONE")
                row.operator("dlm.tweak_remove_arm", text="Remove Arm", icon="X")
                row.operator("dlm.tweak_bake_arm", text="Bake Arm", icon="KEYFRAME")
                row = box.row(align=True)
                row.operator("dlm.tweak_add_leg", text="Add Leg", icon="CONSTRAINT_BONE")
                row.operator("dlm.tweak_remove_leg", text="Remove Leg", icon="X")
                row.operator("dlm.tweak_bake_leg", text="Bake Leg", icon="KEYFRAME")
                row = box.row(align=True)
                row.operator("dlm.tweak_add_body", text="Add Body", icon="CONSTRAINT_BONE")
                row.operator("dlm.tweak_remove_body", text="Remove Body", icon="X")
                row.operator("dlm.tweak_bake_body", text="Bake Body", icon="KEYFRAME")
                row = box.row(align=True)
                row.operator("dlm.tweak_add_both", text="Add All", icon="CONSTRAINT_BONE")
                row.operator("dlm.tweak_remove_both", text="Remove All", icon="X")
                row.operator("dlm.tweak_bake_both", text="Bake All", icon="KEYFRAME")
                row = box.row()
                row.prop(props, "tweak_nla_track_name", text="NLA track")
                row = box.row()
                row.prop(props, "tweak_bake_post_clean", text="Post-clean after bake")

        # Prop Migrator: object-only (meshes, empties, curves — not armatures)
        section_icon = "DISCLOSURE_TRI_DOWN" if props.propmig_section_expanded else "DISCLOSURE_TRI_RIGHT"
        row = layout.row(align=True)
        row.prop(props, "propmig_section_expanded", text="", icon=section_icon, icon_only=True)
        row.label(text="Prop Migrator", icon="OBJECT_DATA")
        if props.propmig_section_expanded:
            box = layout.box()
            row = box.row()
            row.prop(props, "original_prop", text="Original")
            row.operator("dlm.picker_original_prop", text="", icon="EYEDROPPER")
            row = box.row()
            row.prop(props, "replacement_prop", text="Replacement")
            row.operator("dlm.picker_replacement_prop", text="", icon="EYEDROPPER")
            row = box.row()
            row.operator("dlm.prop_migrator_remove_original", text="Remove Original", icon="TRASH")
            row = box.row()
            row.operator("dlm.prop_migrator_run_all", text="Migrate Prop", icon="PLAY")
            row = box.row(align=True)
            row.operator("dlm.prop_migrator_copy_attributes", text="CopyAttr", icon="COPY_ID")
            row.operator("dlm.prop_migrator_migrate_nla", text="MigNLA", icon="NLA")
            row.operator("dlm.prop_migrator_custom_properties", text="MigCustProps", icon="PROPERTIES")
            row = box.row(align=True)
            row.operator("dlm.prop_migrator_object_constraints", text="MigObjConst", icon="CONSTRAINT")
            row.operator("dlm.prop_migrator_object_relatives", text="MigObjRelatives", icon="OBJECT_ORIGIN")
            row.operator("dlm.prop_migrator_retarget_relations", text="RetargRelatives", icon="ORIENTATION_PARENT")
