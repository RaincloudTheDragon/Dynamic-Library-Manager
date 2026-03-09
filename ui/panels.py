# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import bpy
from bpy.types import Panel, UIList
from . import properties


class DLM_UL_library_list(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            layout.scale_x = 0.4
            layout.label(text=item.name)
            layout.scale_x = 0.3
            if item.is_missing:
                layout.label(text="MISSING", icon="ERROR")
            elif item.is_indirect:
                layout.label(text="INDIRECT", icon="INFO")
            else:
                layout.label(text="OK", icon="FILE_BLEND")
            layout.scale_x = 0.3
            path_text = item.filepath or ""
            if path_text.startswith("\\\\"):
                parts = path_text.split("\\")
                short_path = f"\\\\{parts[2]}\\" if len(parts) >= 3 else "\\\\ (network)"
            elif len(path_text) >= 2 and path_text[1] == ":":
                short_path = f"{path_text[:2]}\\"
            elif path_text.startswith("//"):
                short_path = "// (relative)"
            else:
                short_path = path_text[:15] + "..." if len(path_text) > 15 else path_text
            layout.label(text=short_path, icon="FILE_FOLDER")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text="", icon="FILE_BLEND")


def _get_short_path(filepath):
    if not filepath:
        return "Unknown"
    if filepath.startswith("//"):
        return "// (relative)"
    if filepath.startswith("\\\\"):
        parts = filepath.split("\\")
        return f"\\\\{parts[2]}\\" if len(parts) >= 3 else "\\\\ (network)"
    if len(filepath) >= 2 and filepath[1] == ":":
        return f"{filepath[:2]}\\"
    if filepath.startswith("/"):
        parts = filepath.split("/")
        return f"/{parts[1]}/" if len(parts) >= 2 else "/ (root)"
    return "Unknown"


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

        # CharMig section (placeholder; full UI in implementation step 5)
        box = layout.box()
        box.label(text="Character Migrator")
        row = box.row()
        row.prop(props, "migrator_mode", text="Automatic pair discovery")
        row = box.row()
        row.prop(props, "original_character", text="Original")
        row.operator("dlm.picker_original_character", text="", icon="EYEDROPPER")
        row = box.row()
        row.prop(props, "replacement_character", text="Replacement")
        row.operator("dlm.picker_replacement_character", text="", icon="EYEDROPPER")
        row = box.row()
        row.operator("dlm.run_character_migration", text="Run migration", icon="ARMATURE_DATA")
        row = box.row(align=True)
        row.operator("dlm.migrator_copy_attributes", text="CopyAttr", icon="COPY_ID")
        row.operator("dlm.migrator_migrate_nla", text="MigNLA", icon="NLA")
        row.operator("dlm.migrator_custom_properties", text="MigCustProps", icon="PROPERTIES")
        row = box.row(align=True)
        row.operator("dlm.migrator_bone_constraints", text="MigBoneConst", icon="CONSTRAINT_BONE")
        row.operator("dlm.migrator_retarget_relations", text="RetargRelatives", icon="ORIENTATION_PARENT")
        row.operator("dlm.migrator_basebody_shapekeys", text="MigBBodyShapeKeys", icon="SHAPEKEY_DATA")
        row = box.row()
        row.operator("dlm.migrator_fk_rotations", text="MigFKRot", icon="BONE_DATA")

        # Tweak Tools
        tweak_box = layout.box()
        tweak_box.label(text="Tweak Tools", icon="CONSTRAINT")
        row = tweak_box.row(align=True)
        row.operator("dlm.tweak_add_arm", text="Add Arm", icon="CONSTRAINT_BONE")
        row.operator("dlm.tweak_remove_arm", text="Remove Arm", icon="X")
        row.operator("dlm.tweak_bake_arm", text="Bake Arm", icon="KEYFRAME")
        row = tweak_box.row(align=True)
        row.operator("dlm.tweak_add_leg", text="Add Leg", icon="CONSTRAINT_BONE")
        row.operator("dlm.tweak_remove_leg", text="Remove Leg", icon="X")
        row.operator("dlm.tweak_bake_leg", text="Bake Leg", icon="KEYFRAME")
        row = tweak_box.row(align=True)
        row.operator("dlm.tweak_add_both", text="Add Both", icon="CONSTRAINT_BONE")
        row.operator("dlm.tweak_remove_both", text="Remove Both", icon="X")
        row.operator("dlm.tweak_bake_both", text="Bake Both", icon="KEYFRAME")
        row = tweak_box.row()
        row.prop(props, "tweak_nla_track_name", text="NLA track")
        row = tweak_box.row()
        row.prop(props, "tweak_bake_post_clean", text="Post-clean after bake")

        # Linked Libraries: header row (always), main box only when expanded
        missing_count = sum(1 for lib in props.linked_libraries if lib.is_missing)
        section_icon = "DISCLOSURE_TRI_DOWN" if props.linked_libraries_section_expanded else "DISCLOSURE_TRI_RIGHT"
        row = layout.row(align=True)
        row.prop(props, "linked_libraries_section_expanded", text="", icon=section_icon, icon_only=True)
        row.label(text="Linked Libraries Analysis")
        if missing_count > 0:
            row.label(text=f"({props.linked_assets_count} libs, {missing_count} missing)", icon="ERROR")
        else:
            row.label(text=f"({props.linked_assets_count} libraries)")
        if props.linked_libraries_section_expanded:
            box = layout.box()
            row = box.row()
            row.operator("dlm.scan_linked_assets", text="Scan Linked Assets", icon="FILE_REFRESH")
            if props.linked_assets_count > 0:
                row = box.row()
                row.template_list("DLM_UL_library_list", "", props, "linked_libraries", props, "linked_libraries_index")
                row = box.row()
                row.operator("dlm.reload_libraries", text="Reload Libraries", icon="FILE_REFRESH")
                prefs = context.preferences.addons.get(__package__.rsplit(".", 1)[0])
                if prefs and prefs.preferences.search_paths:
                    for i, path_item in enumerate(prefs.preferences.search_paths):
                        row = box.row()
                        row.prop(path_item, "path", text=f"Search path {i+1}")
                        row.operator("dlm.browse_search_path", text="", icon="FILE_FOLDER").index = i
                        row.operator("dlm.remove_search_path", text="", icon="REMOVE").index = i
                row = box.row()
                row.alignment = "RIGHT"
                row.operator("dlm.add_search_path", text="Add search path", icon="ADD")
                if missing_count > 0:
                    row = box.row()
                    row.operator("dlm.find_libraries_in_folders", text="Find libraries in these folders", icon="VIEWZOOM")
                if props.linked_libraries and 0 <= props.linked_libraries_index < len(props.linked_libraries):
                    selected_lib = props.linked_libraries[props.linked_libraries_index]
                    info_box = box.box()
                    if selected_lib.is_missing:
                        info_box.alert = True
                    info_box.label(text=f"Selected: {selected_lib.name}")
                    if selected_lib.is_missing:
                        info_box.label(text="Status: MISSING", icon="ERROR")
                    elif selected_lib.is_indirect:
                        info_box.label(text="Status: INDIRECT", icon="INFO")
                    else:
                        info_box.label(text="Status: OK", icon="FILE_BLEND")
                    info_box.label(text=f"Path: {selected_lib.filepath}", icon="FILE_FOLDER")
                    info_box.operator("dlm.open_linked_file", text="Open Blend", icon="FILE_BLEND").filepath = selected_lib.filepath
                    op = info_box.operator("dlm.relocate_single_library", text="Relocate Library", icon="FILE_FOLDER")
                    op.target_filepath = selected_lib.filepath
