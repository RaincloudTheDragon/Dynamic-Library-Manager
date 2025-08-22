# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTIBILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

bl_info = {
    "name": "Dynamic Link Manager",
    "author": "RaincloudTheDragon",
    "version": (0, 0, 1),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > Dynamic Link Manager",
    "description": "Replace linked assets and characters with ease",
    "warning": "",
    "doc_url": "",
    "category": "Import-Export",
}

import bpy
from bpy.props import StringProperty, BoolProperty, EnumProperty
from bpy.types import Panel, Operator, PropertyGroup

# Import local modules
from . import operators
from . import ui

def ensure_default_search_path():
    """Ensure there's always at least one search path"""
    prefs = bpy.context.preferences.addons.get(__name__)
    if prefs and len(prefs.preferences.search_paths) == 0:
        new_path = prefs.preferences.search_paths.add()
        new_path.path = "//"  # Default to relative path

def register():
    operators.register()
    ui.register()
    # Ensure default search path exists
    bpy.app.handlers.load_post.append(ensure_default_search_path)

def unregister():
    ui.unregister()
    operators.unregister()
    # Remove the handler
    if ensure_default_search_path in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(ensure_default_search_path)

if __name__ == "__main__":
    register()
