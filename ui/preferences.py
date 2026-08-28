# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import bpy
from bpy.types import AddonPreferences


class DynamicLinkManagerPreferences(AddonPreferences):
    bl_idname = __package__.rsplit(".", 1)[0]

    def draw(self, context):
        layout = self.layout
        layout.label(text="No addon preferences yet.")
