bl_info = {
    "name": "Dynamic Link Manager",
    "author": "RaincloudTheDragon",
    "version": (0, 5, 1),
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

# Registration
def register():
    operators.register()
    ui.register()

def unregister():
    ui.unregister()
    operators.unregister()

if __name__ == "__main__":
    register()
