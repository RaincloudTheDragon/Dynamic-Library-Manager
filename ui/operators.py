# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import bpy
import os
from bpy.types import Operator
from bpy.props import StringProperty, BoolProperty
from bpy.props import StringProperty, IntProperty

from ..utils.remove_original import resolve_collection_for_remove_original

ADDON_NAME = __package__.rsplit(".", 1)[0] if "." in __package__ else __package__


def _prefs(context):
    return context.preferences.addons.get(ADDON_NAME)


class DLM_OT_replace_linked_asset(Operator):
    bl_idname = "dlm.replace_linked_asset"
    bl_label = "Replace Linked Asset"
    bl_description = "Open file browser to replace the linked asset with another file"
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
    bl_description = "Scan the current file for linked libraries and list their status"
    bl_options = {"REGISTER"}

    def execute(self, context):
        from ..ops import library

        return library.scan_linked_assets(context, self.report)


class DLM_OT_find_libraries_in_folders(Operator):
    bl_idname = "dlm.find_libraries_in_folders"
    bl_label = "Find Libraries in Folders"
    bl_description = "Search addon search paths for missing library blend files"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from ..ops import library

        return library.find_libraries_in_folders(context, self.report, ADDON_NAME)


class DLM_OT_open_linked_file(Operator):
    bl_idname = "dlm.open_linked_file"
    bl_label = "Open Linked File"
    bl_description = "Open the selected linked blend file in a new Blender instance"
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
    bl_description = "Add a new folder to the list of search paths for finding libraries"
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
    bl_description = "Remove the selected search path from the list"
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
    bl_description = "Try to relink missing libraries using the configured search paths"
    bl_options = {"REGISTER"}

    def execute(self, context):
        from ..ops import library

        return library.attempt_relink(context, self.report, ADDON_NAME)


class DLM_OT_browse_search_path(Operator):
    bl_idname = "dlm.browse_search_path"
    bl_label = "Browse Search Path"
    bl_description = "Browse to set the folder for the selected search path"
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
    bl_description = "Reload all linked libraries (or fallback manual reload)"
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


class DLM_OT_relocate_single_library(Operator):
    bl_idname = "dlm.relocate_single_library"
    bl_label = "Relocate Library"
    bl_description = "Point the selected library to a new blend file and reload"
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


def _get_migrator_pair(context):
    """Return (orig, rep) from scene props (manual or automatic). (None, None) if invalid."""
    from ..ops.migrator import get_pair_manual, get_pair_automatic

    props = getattr(context.scene, "dynamic_link_manager", None)
    if not props:
        return None, None
    use_auto = getattr(props, "migrator_mode", False)
    orig, rep = get_pair_automatic(context) if use_auto else get_pair_manual(context)
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

        name = orig.name

        # Collect actions from original character before removal
        actions_to_remove = set()
        if orig.animation_data:
            # Active action
            if orig.animation_data.action:
                actions_to_remove.add(orig.animation_data.action)
            # NLA strips
            for track in orig.animation_data.nla_tracks:
                for strip in track.strips:
                    if strip.action:
                        actions_to_remove.add(strip.action)

        # Remove collected actions from bpy.data.actions
        removed_actions = []
        for action in actions_to_remove:
            action_name = action.name
            try:
                bpy.data.actions.remove(action)
                removed_actions.append(action_name)
            except Exception as e:
                self.report({"WARNING"}, f"Could not remove action {action_name}: {e}")

        if removed_actions:
            self.report({"INFO"}, f"Removed {len(removed_actions)} action(s) from original")

        props = context.scene.dynamic_link_manager
        rig_family = getattr(props, "migrator_rig_family", "RIGIFY")
        try:
            coll = resolve_collection_for_remove_original(orig, rig_family, context.scene, rep)
            if coll:
                coll_name = coll.name  # Store name BEFORE removal (RNA invalidates after remove)
                context.scene.dynamic_link_manager.original_character = None
                try:
                    bpy.data.collections.remove(coll)
                    self.report({"INFO"}, f"Removed collection: {coll_name}")
                except Exception as remove_err:
                    self.report({"WARNING"}, f"Collection {coll_name} removal issue: {remove_err}")
                    try:
                        bpy.data.objects.remove(orig, do_unlink=True)
                        self.report({"INFO"}, f"Removed original object: {name}")
                    except Exception as e2:
                        self.report({"ERROR"}, f"Could not remove original after collection failure: {e2}")
                        return {"CANCELLED"}
            else:
                bpy.data.objects.remove(orig, do_unlink=True)
                context.scene.dynamic_link_manager.original_character = None
                self.report({"INFO"}, f"Removed original character: {name}")
        except Exception as e:
            self.report({"ERROR"}, f"Failed to remove original: {e}")
            return {"CANCELLED"}

        # Rename replacement actions with ".rep" suffix
        if rep and rep.animation_data:
            renamed_actions = []
            # Active action
            if rep.animation_data.action and ".rep" in rep.animation_data.action.name:
                old_name = rep.animation_data.action.name
                new_name = old_name.replace(".rep", "")
                rep.animation_data.action.name = new_name
                renamed_actions.append(f"{old_name} -> {new_name}")
            # NLA strips
            for track in rep.animation_data.nla_tracks:
                for strip in track.strips:
                    if strip.action and ".rep" in strip.action.name:
                        old_name = strip.action.name
                        new_name = old_name.replace(".rep", "")
                        strip.action.name = new_name
                        renamed_actions.append(f"{old_name} -> {new_name}")
            if renamed_actions:
                self.report({"INFO"}, f"Renamed {len(renamed_actions)} replacement action(s)")

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
    DLM_OT_migrator_remove_original,
    DLM_OT_picker_original_character,
    DLM_OT_picker_replacement_character,
    DLM_OT_migrator_copy_attributes,
    DLM_OT_migrator_migrate_nla,
    DLM_OT_migrator_custom_properties,
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
