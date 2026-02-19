# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import bpy
from bpy.types import AddonPreferences
from bpy.props import StringProperty, CollectionProperty
from . import properties


class DynamicLinkManagerPreferences(AddonPreferences):
    bl_idname = __package__.rsplit(".", 1)[0]

    search_paths: CollectionProperty(
        type=properties.SearchPathItem,
        name="Search Paths",
        description="Paths to search for missing linked libraries",
    )

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="Default Search Paths for Missing Libraries")
        row = box.row()
        row.alignment = "RIGHT"
        row.operator("dlm.add_search_path", text="Add search path", icon="ADD")
        for i, path_item in enumerate(self.search_paths):
            row = box.row()
            row.prop(path_item, "path", text=f"Search path {i+1}")
            row.operator("dlm.browse_search_path", text="", icon="FILE_FOLDER").index = i
            row.operator("dlm.remove_search_path", text="", icon="REMOVE").index = i
