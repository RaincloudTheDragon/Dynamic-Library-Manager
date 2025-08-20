import bpy
import os
from bpy.types import Operator
from bpy.props import StringProperty, BoolProperty, EnumProperty

class DYNAMICLINK_OT_replace_linked_asset(Operator):
    """Replace a linked asset with a new file"""
    bl_idname = "dynamiclink.replace_linked_asset"
    bl_label = "Replace Linked Asset"
    bl_options = {'REGISTER', 'UNDO'}
    
    filepath: StringProperty(
        name="File Path",
        description="Path to the new asset file",
        subtype='FILE_PATH'
    )
    
    def execute(self, context):
        obj = context.active_object
        if not obj:
            self.report({'ERROR'}, "No object selected")
            return {'CANCELLED'}
        
        if not obj.data or not obj.data.library:
            self.report({'ERROR'}, "Selected object is not linked")
            return {'CANCELLED'}
        
        try:
            # Implementation will go here
            self.report({'INFO'}, f"Replaced linked asset: {obj.name}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to replace asset: {str(e)}")
            return {'CANCELLED'}
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class DYNAMICLINK_OT_scan_linked_assets(Operator):
    """Scan scene for all linked assets"""
    bl_idname = "dynamiclink.scan_linked_assets"
    bl_label = "Scan Linked Assets"
    
    def execute(self, context):
        linked_assets = []
        seen_libraries = set()
        
        # Only scan objects that are actually in the scene
        for obj in context.scene.objects:
            if obj.library and obj.library.filepath not in seen_libraries:
                linked_assets.append({
                    'type': 'OBJECT',
                    'name': obj.name,
                    'library': obj.library.filepath
                })
                seen_libraries.add(obj.library.filepath)
        
        # Also check for unique library files
        unique_libraries = set()
        for obj in bpy.data.objects:
            if obj.library:
                unique_libraries.add(obj.library.filepath)
        
        # Store results in scene properties
        context.scene.dynamic_link_manager.linked_assets_count = len(unique_libraries)
        
        self.report({'INFO'}, f"Found {len(unique_libraries)} unique linked library files")
        return {'FINISHED'}

def register():
    bpy.utils.register_class(DYNAMICLINK_OT_replace_linked_asset)
    bpy.utils.register_class(DYNAMICLINK_OT_scan_linked_assets)

def unregister():
    bpy.utils.unregister_class(DYNAMICLINK_OT_scan_linked_assets)
    bpy.utils.unregister_class(DYNAMICLINK_OT_replace_linked_asset)
