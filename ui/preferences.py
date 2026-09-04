# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import os
import bpy
from bpy.types import AddonPreferences, Operator, PropertyGroup
from bpy.props import StringProperty, CollectionProperty, IntProperty


class DLM_PG_search_root(PropertyGroup):
    """One default search-root folder for Missing Library Propagation."""

    path: StringProperty(
        name="Folder",
        description="Directory used as a starting search root for modern .blend files",
        subtype="DIR_PATH",
        default="",
    )


def _addon_prefs(context=None):
    context = context or bpy.context
    name = DynamicLibraryManagerPreferences.bl_idname
    addon = context.preferences.addons.get(name)
    return addon.preferences if addon else None


def get_prefs_search_paths(prefs=None):
    """Return non-empty default search root paths from addon preferences."""
    prefs = prefs or _addon_prefs()
    if not prefs or not hasattr(prefs, "symlink_search_paths"):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in prefs.symlink_search_paths:
        raw = (item.path or "").strip()
        if not raw:
            continue
        norm = os.path.normpath(raw)
        key = norm.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
    return out


def set_prefs_search_paths(paths, prefs=None, ensure_one=True):
    """Replace preference search roots with the given list."""
    prefs = prefs or _addon_prefs()
    if not prefs or not hasattr(prefs, "symlink_search_paths"):
        return False
    prefs.symlink_search_paths.clear()
    seen: set[str] = set()
    for raw in paths or []:
        raw = (raw or "").strip()
        if not raw:
            continue
        norm = os.path.normpath(raw)
        key = norm.upper()
        if key in seen:
            continue
        seen.add(key)
        item = prefs.symlink_search_paths.add()
        item.path = norm
    if ensure_one and len(prefs.symlink_search_paths) == 0:
        prefs.symlink_search_paths.add()
    return True


def ensure_search_path_collection(collection):
    """Guarantee at least one path row exists."""
    if collection is None:
        return
    if len(collection) == 0:
        collection.add()


def draw_search_path_list(layout, collection, *, add_idname, remove_idname):
    """
    Draw editable folder rows: DIR_PATH field (folder picker).

    First row: path + Add (+ Remove only when more than one path).
    Extra rows: path + Remove. Always keeps at least one path.
    """
    ensure_search_path_collection(collection)
    count = len(collection)

    for i, item in enumerate(collection):
        row = layout.row(align=True)
        row.prop(item, "path", text="")
        if i == 0:
            row.operator(add_idname, text="", icon="ADD")
        if count > 1:
            op = row.operator(remove_idname, text="", icon="REMOVE")
            op.index = i


def parse_search_roots(text: str) -> list[str]:
    """Split legacy semicolon/newline preference text into unique paths."""
    out: list[str] = []
    seen: set[str] = set()
    for part in (text or "").replace("\n", ";").split(";"):
        part = part.strip().strip('"').strip("'")
        if not part:
            continue
        norm = os.path.normpath(part)
        key = norm.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
    return out


class DynamicLibraryManagerPreferences(AddonPreferences):
    bl_idname = __package__.rsplit(".", 1)[0]

    symlink_search_paths: CollectionProperty(
        type=DLM_PG_search_root,
        name="Default Search Roots",
        description=(
            "Folders used as the Missing Library Propagation wizard's starting "
            "search roots (basename lookup for modern .blend files)"
        ),
    )

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="Missing Library Propagation (armature libs only)")
        draw_search_path_list(
            box,
            self.symlink_search_paths,
            add_idname="dlm.prefs_search_root_add",
            remove_idname="dlm.prefs_search_root_remove",
        )
        box.label(
            text="Armature libs only. Others: Atomic Remap (recommended), FMT (images), or blendfile search.",
            icon="INFO",
        )


class DLM_OT_prefs_search_root_add(Operator):
    """Add a folder row to default search roots"""

    bl_idname = "dlm.prefs_search_root_add"
    bl_label = "Add Search Root"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        prefs = _addon_prefs(context)
        if not prefs:
            return {"CANCELLED"}
        prefs.symlink_search_paths.add()
        return {"FINISHED"}


class DLM_OT_prefs_search_root_remove(Operator):
    """Remove a folder row from default search roots"""

    bl_idname = "dlm.prefs_search_root_remove"
    bl_label = "Remove Search Root"
    bl_options = {"INTERNAL"}

    index: IntProperty(default=0)

    def execute(self, context):
        prefs = _addon_prefs(context)
        if not prefs:
            return {"CANCELLED"}
        if len(prefs.symlink_search_paths) <= 1:
            return {"CANCELLED"}
        if 0 <= self.index < len(prefs.symlink_search_paths):
            prefs.symlink_search_paths.remove(self.index)
        return {"FINISHED"}
