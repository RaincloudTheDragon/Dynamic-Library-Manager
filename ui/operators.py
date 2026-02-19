# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import bpy
import os
from bpy.types import Operator
from bpy.props import StringProperty, IntProperty

ADDON_NAME = __package__.rsplit(".", 1)[0] if "." in __package__ else __package__


def _prefs(context):
    return context.preferences.addons.get(ADDON_NAME)


class DLM_OT_replace_linked_asset(Operator):
    bl_idname = "dlm.replace_linked_asset"
    bl_label = "Replace Linked Asset"
    bl_options = {"REGISTER", "UNDO"}
    filepath: StringProperty(name="File Path", description="Path to the new asset file", subtype="FILE_PATH")

    def execute(self, context):
        obj = context.active_object
        if not obj:
            self.report({"ERROR"}, "No object selected")
            return {"CANCELLED"}
        if getattr(obj, "library", None):
            self.report({"INFO"}, f"Object '{obj.name}' is linked from: {obj.library.filepath}")
            return {"FINISHED"}
        if obj.data and getattr(obj.data, "library", None) and obj.data.library:
            self.report({"INFO"}, f"Object '{obj.name}' has linked data from: {obj.data.library.filepath}")
            return {"FINISHED"}
        if obj.type == "ARMATURE" and obj.data and obj.data.name in bpy.data.armatures:
            ad = bpy.data.armatures[obj.data.name]
            if getattr(ad, "library", None) and ad.library:
                self.report({"INFO"}, f"Armature '{obj.name}' data is linked from: {ad.library.filepath}")
                return {"FINISHED"}
        self.report({"ERROR"}, "Selected object is not a linked asset")
        return {"CANCELLED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class DLM_OT_scan_linked_assets(Operator):
    bl_idname = "dlm.scan_linked_assets"
    bl_label = "Scan Linked Libraries"
    bl_options = {"REGISTER"}

    def execute(self, context):
        from ..ops import library

        return library.scan_linked_assets(context, self.report)


class DLM_OT_find_libraries_in_folders(Operator):
    bl_idname = "dlm.find_libraries_in_folders"
    bl_label = "Find Libraries in Folders"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from ..ops import library

        return library.find_libraries_in_folders(context, self.report, ADDON_NAME)


class DLM_OT_open_linked_file(Operator):
    bl_idname = "dlm.open_linked_file"
    bl_label = "Open Linked File"
    bl_options = {"REGISTER"}
    filepath: StringProperty(name="File Path", default="")

    def execute(self, context):
        if not self.filepath:
            self.report({"ERROR"}, "No file path specified")
            return {"CANCELLED"}
        try:
            bpy.ops.wm.path_open(filepath=self.filepath)
            self.report({"INFO"}, f"Opening linked file: {self.filepath}")
        except Exception as e:
            self.report({"ERROR"}, f"Failed to open linked file: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class DLM_OT_add_search_path(Operator):
    bl_idname = "dlm.add_search_path"
    bl_label = "Add Search Path"
    bl_options = {"REGISTER"}

    def execute(self, context):
        prefs = _prefs(context)
        if prefs:
            p = prefs.preferences.search_paths.add()
            p.path = "//"
            self.report({"INFO"}, f"Added search path: {p.path}")
        return {"FINISHED"}


class DLM_OT_remove_search_path(Operator):
    bl_idname = "dlm.remove_search_path"
    bl_label = "Remove Search Path"
    bl_options = {"REGISTER"}
    index: IntProperty(name="Index", default=0)

    def execute(self, context):
        prefs = _prefs(context)
        if prefs and prefs.preferences.search_paths and 0 <= self.index < len(prefs.preferences.search_paths):
            prefs.preferences.search_paths.remove(self.index)
            self.report({"INFO"}, f"Removed search path at index {self.index}")
        return {"FINISHED"}


class DLM_OT_attempt_relink(Operator):
    bl_idname = "dlm.attempt_relink"
    bl_label = "Attempt Relink"
    bl_options = {"REGISTER"}

    def execute(self, context):
        from ..ops import library

        return library.attempt_relink(context, self.report, ADDON_NAME)


class DLM_OT_browse_search_path(Operator):
    bl_idname = "dlm.browse_search_path"
    bl_label = "Browse Search Path"
    bl_options = {"REGISTER"}
    index: IntProperty(name="Index", default=0)
    filepath: StringProperty(name="Search Path", subtype="DIR_PATH")

    def execute(self, context):
        prefs = _prefs(context)
        if prefs and prefs.preferences.search_paths and 0 <= self.index < len(prefs.preferences.search_paths):
            prefs.preferences.search_paths[self.index].path = self.filepath
            self.report({"INFO"}, f"Updated search path {self.index + 1}: {self.filepath}")
        return {"FINISHED"}

    def invoke(self, context, event):
        prefs = _prefs(context)
        if prefs and prefs.preferences.search_paths and 0 <= self.index < len(prefs.preferences.search_paths):
            self.filepath = prefs.preferences.search_paths[self.index].path
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class DLM_OT_reload_libraries(Operator):
    bl_idname = "dlm.reload_libraries"
    bl_label = "Reload Libraries"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            bpy.ops.outliner.lib_operation(type="RELOAD")
            self.report({"INFO"}, "Library reload operation completed")
        except Exception:
            try:
                for lib in bpy.data.libraries:
                    if lib.filepath and os.path.exists(bpy.path.abspath(lib.filepath)):
                        lib.reload()
                self.report({"INFO"}, "Libraries reloaded manually")
            except Exception as e:
                self.report({"ERROR"}, f"Failed to reload libraries: {e}")
                return {"CANCELLED"}
        return {"FINISHED"}


class DLM_OT_make_paths_relative(Operator):
    bl_idname = "dlm.make_paths_relative"
    bl_label = "Make Paths Relative"
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
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            bpy.ops.file.make_paths_absolute()
            self.report({"INFO"}, "All file paths made absolute")
        except Exception as e:
            self.report({"ERROR"}, f"Failed to make paths absolute: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class DLM_OT_relocate_single_library(Operator):
    bl_idname = "dlm.relocate_single_library"
    bl_label = "Relocate Library"
    bl_options = {"REGISTER", "UNDO"}
    target_filepath: StringProperty(name="Current Library Path", default="")
    filepath: StringProperty(name="New Library File", subtype="FILE_PATH", default="")

    def execute(self, context):
        if not self.target_filepath or not self.filepath:
            self.report({"ERROR"}, "No target or new file specified")
            return {"CANCELLED"}
        abs_match = bpy.path.abspath(self.target_filepath) if self.target_filepath else ""
        library = None
        for lib in bpy.data.libraries:
            try:
                if lib.filepath and bpy.path.abspath(lib.filepath) == abs_match:
                    library = lib
                    break
            except Exception:
                if lib.filepath == self.target_filepath:
                    library = lib
                    break
        if not library:
            self.report({"ERROR"}, "Could not resolve the selected library")
            return {"CANCELLED"}
        try:
            library.filepath = self.filepath
            library.reload()
            self.report({"INFO"}, f"Relocated to: {self.filepath}")
        except Exception as e:
            self.report({"ERROR"}, f"Failed to relocate: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}

    def invoke(self, context, event):
        if self.target_filepath:
            try:
                self.filepath = bpy.path.abspath(self.target_filepath)
            except Exception:
                self.filepath = self.target_filepath
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class DLM_OT_run_character_migration(Operator):
    bl_idname = "dlm.run_character_migration"
    bl_label = "Run Character Migration"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from ..ops.migrator import run_full_migration

        ok, msg = run_full_migration(context)
        if ok:
            self.report({"INFO"}, msg)
            return {"FINISHED"}
        self.report({"ERROR"}, msg)
        return {"CANCELLED"}


class DLM_OT_picker_original_character(Operator):
    bl_idname = "dlm.picker_original_character"
    bl_label = "Pick Original"
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
    bl_options = {"REGISTER"}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != "ARMATURE":
            self.report({"WARNING"}, "Select an armature")
            return {"CANCELLED"}
        context.scene.dynamic_link_manager.replacement_character = obj
        self.report({"INFO"}, f"Replacement: {obj.name}")
        return {"FINISHED"}


OPERATOR_CLASSES = [
    DLM_OT_replace_linked_asset,
    DLM_OT_scan_linked_assets,
    DLM_OT_find_libraries_in_folders,
    DLM_OT_open_linked_file,
    DLM_OT_add_search_path,
    DLM_OT_remove_search_path,
    DLM_OT_browse_search_path,
    DLM_OT_attempt_relink,
    DLM_OT_reload_libraries,
    DLM_OT_make_paths_relative,
    DLM_OT_make_paths_absolute,
    DLM_OT_relocate_single_library,
    DLM_OT_run_character_migration,
    DLM_OT_picker_original_character,
    DLM_OT_picker_replacement_character,
]
