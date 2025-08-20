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
        
        # Comprehensive debug info
        debug_info = f"Object: {obj.name}, Type: {obj.type}"
        
        # Check object library
        if hasattr(obj, 'library'):
            debug_info += f", Object has library attr: {obj.library is not None}"
            if obj.library:
                debug_info += f", Object library: {obj.library.filepath}"
        
        # Check object data
        if obj.data:
            debug_info += f", Has data: {type(obj.data).__name__}, Name: {obj.data.name}"
            
            # Check data library attribute
            if hasattr(obj.data, 'library'):
                debug_info += f", Data.library exists: {obj.data.library is not None}"
                if obj.data.library:
                    debug_info += f", Data.library.filepath: {obj.data.library.filepath}"
            
            # Check if data is in bpy.data collections
            if obj.type == 'ARMATURE' and obj.data.name in bpy.data.armatures:
                armature_data = bpy.data.armatures[obj.data.name]
                debug_info += f", Found in bpy.data.armatures"
                if hasattr(armature_data, 'library'):
                    debug_info += f", bpy.data library: {armature_data.library is not None}"
                    if armature_data.library:
                        debug_info += f", bpy.data library path: {armature_data.library.filepath}"
            
            # Check if data is in bpy.data.objects
            if obj.data.name in bpy.data.objects:
                debug_info += f", Data also in bpy.data.objects"
        
        # Check if object itself is linked
        if hasattr(obj, 'library') and obj.library:
            self.report({'INFO'}, f"Object '{obj.name}' is linked from: {obj.library.filepath}")
            return {'FINISHED'}
        
        # Check if object's data is linked
        if obj.data and hasattr(obj.data, 'library') and obj.data.library:
            self.report({'INFO'}, f"Object '{obj.name}' has linked data from: {obj.data.library.filepath}")
            return {'FINISHED'}
        
        # Check if armature data is linked through bpy.data system
        if obj.type == 'ARMATURE' and obj.data and obj.data.name in bpy.data.armatures:
            armature_data = bpy.data.armatures[obj.data.name]
            if hasattr(armature_data, 'library') and armature_data.library:
                self.report({'INFO'}, f"Armature '{obj.name}' data is linked from: {armature_data.library.filepath}")
                return {'FINISHED'}
        
        # If we get here, show debug info
        self.report({'WARNING'}, debug_info)
        self.report({'ERROR'}, "Selected object is not a linked asset")
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
        
        # Scan all objects in the scene
        for obj in context.scene.objects:
            # Check if object itself is linked
            if hasattr(obj, 'library') and obj.library:
                if obj.library.filepath not in seen_libraries:
                    linked_assets.append({
                        'type': 'OBJECT',
                        'name': obj.name,
                        'library': obj.library.filepath
                    })
                    seen_libraries.add(obj.library.filepath)
            
            # Check if object's data is linked
            elif obj.data and hasattr(obj.data, 'library') and obj.data.library:
                if obj.data.library.filepath not in seen_libraries:
                    linked_assets.append({
                        'type': 'DATA',
                        'name': f"{obj.name} ({type(obj.data).__name__})",
                        'library': obj.data.library.filepath
                    })
                    seen_libraries.add(obj.data.library.filepath)
        
        # Check all data collections for linked items
        all_libraries = set()
        
        # Check bpy.data.objects
        for obj in bpy.data.objects:
            if hasattr(obj, 'library') and obj.library:
                all_libraries.add(obj.library.filepath)
            if obj.data and hasattr(obj.data, 'library') and obj.data.library:
                all_libraries.add(obj.data.library.filepath)
        
        # Check bpy.data.armatures specifically
        for armature in bpy.data.armatures:
            if hasattr(armature, 'library') and armature.library:
                all_libraries.add(armature.library.filepath)
        
        # Check bpy.data.meshes
        for mesh in bpy.data.meshes:
            if hasattr(mesh, 'library') and mesh.library:
                all_libraries.add(mesh.library.filepath)
        
        # Check bpy.data.materials
        for material in bpy.data.materials:
            if hasattr(material, 'library') and material.library:
                all_libraries.add(material.library.filepath)
        
        # Store results in scene properties
        context.scene.dynamic_link_manager.linked_assets_count = len(all_libraries)
        
        # Show detailed info
        self.report({'INFO'}, f"Found {len(all_libraries)} unique linked library files")
        if all_libraries:
            for lib in sorted(all_libraries):
                self.report({'INFO'}, f"Library: {lib}")
        
        return {'FINISHED'}

def register():
    bpy.utils.register_class(DYNAMICLINK_OT_replace_linked_asset)
    bpy.utils.register_class(DYNAMICLINK_OT_scan_linked_assets)

def unregister():
    bpy.utils.unregister_class(DYNAMICLINK_OT_scan_linked_assets)
    bpy.utils.unregister_class(DYNAMICLINK_OT_replace_linked_asset)
