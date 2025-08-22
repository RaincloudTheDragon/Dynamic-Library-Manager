import bpy
import os
from bpy.types import Operator
from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty

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
        # Clear previous results
        context.scene.dynamic_link_manager.linked_libraries.clear()
        
        # Dictionary to store library info with hierarchy
        library_info = {}
        
        # Function to check if file exists
        def is_file_missing(filepath):
            if not filepath:
                return True
            # Convert relative paths to absolute
            if filepath.startswith('//'):
                # This is a relative path, we can't easily check if it exists
                # So we'll assume it's missing if it's relative
                return True
            return not os.path.exists(filepath)
        
        # Function to get library name from path
        def get_library_name(filepath):
            if not filepath:
                return "Unknown"
            return os.path.basename(filepath)
        
        # Function to detect indirect links by parsing .blend files safely
        def get_indirect_libraries(filepath):
            """Get libraries that are linked from within a .blend file"""
            # This function is no longer used with the new approach
            # Indirect links are now detected when attempting to relink
            return set()
        
        # Scan all data collections for linked items
        all_libraries = set()
        library_info = {}  # Store additional info about each library
        
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
        
        # Check bpy.data.images
        for image in bpy.data.images:
            if hasattr(image, 'library') and image.library:
                all_libraries.add(image.library.filepath)
        
        # Check bpy.data.textures
        for texture in bpy.data.textures:
            if hasattr(texture, 'library') and texture.library:
                all_libraries.add(texture.library.filepath)
        
        # Check bpy.data.node_groups
        for node_group in bpy.data.node_groups:
            if hasattr(node_group, 'library') and node_group.library:
                all_libraries.add(node_group.library.filepath)
        
        # Analyze each library for indirect links
        for filepath in all_libraries:
            if filepath:
                # Initialize with no indirect missing (will be updated during relink attempts)
                library_info[filepath] = {
                    'indirect_libraries': set(),
                    'missing_indirect_count': 0,
                    'has_indirect_missing': False
                }
        
        # Store results in scene properties
        context.scene.dynamic_link_manager.linked_assets_count = len(all_libraries)
        
        # Create library items for the UI
        for filepath in sorted(all_libraries):
            if filepath:
                lib_item = context.scene.dynamic_link_manager.linked_libraries.add()
                lib_item.filepath = filepath
                lib_item.name = get_library_name(filepath)
                lib_item.is_missing = is_file_missing(filepath)
                
                # Set indirect link information
                if filepath in library_info:
                    info = library_info[filepath]
                    lib_item.has_indirect_missing = info['has_indirect_missing']
                    lib_item.indirect_missing_count = info['missing_indirect_count']
                else:
                    lib_item.has_indirect_missing = False
                    lib_item.indirect_missing_count = 0
                

        
        # Show detailed info
        self.report({'INFO'}, f"Found {len(all_libraries)} unique linked library files")
        if all_libraries:
            for lib in sorted(all_libraries):
                self.report({'INFO'}, f"Library: {lib}")
        
        return {'FINISHED'}

def register():
    bpy.utils.register_class(DYNAMICLINK_OT_replace_linked_asset)
    bpy.utils.register_class(DYNAMICLINK_OT_scan_linked_assets)

class DYNAMICLINK_OT_open_linked_file(Operator):
    """Open the linked file in a new Blender instance"""
    bl_idname = "dynamiclink.open_linked_file"
    bl_label = "Open Linked File"
    bl_options = {'REGISTER'}
    
    filepath: StringProperty(
        name="File Path",
        description="Path to the linked file",
        default=""
    )
    
    def execute(self, context):
        if not self.filepath:
            self.report({'ERROR'}, "No file path specified")
            return {'CANCELLED'}
        
        # Try to open the linked file in a new Blender instance
        try:
            # Use Blender's built-in file browser to open the file
            bpy.ops.wm.path_open(filepath=self.filepath)
            self.report({'INFO'}, f"Opening linked file: {self.filepath}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to open linked file: {e}")
            return {'CANCELLED'}
        
        return {'FINISHED'}

class DYNAMICLINK_OT_add_search_path(Operator):
    """Add a new search path for missing libraries"""
    bl_idname = "dynamiclink.add_search_path"
    bl_label = "Add Search Path"
    bl_options = {'REGISTER'}
    
    filepath: StringProperty(
        name="Search Path",
        description="Path to search for missing linked libraries",
        subtype='DIR_PATH'
    )
    
    def execute(self, context):
        prefs = context.preferences.addons.get(__package__)
        if prefs:
            new_path = prefs.preferences.search_paths.add()
            new_path.path = self.filepath if self.filepath else "//"
            self.report({'INFO'}, f"Added search path: {new_path.path}")
        return {'FINISHED'}
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class DYNAMICLINK_OT_remove_search_path(Operator):
    """Remove a search path"""
    bl_idname = "dynamiclink.remove_search_path"
    bl_label = "Remove Search Path"
    bl_options = {'REGISTER'}
    
    index: IntProperty(
        name="Index",
        description="Index of the search path to remove",
        default=0
    )
    
    def execute(self, context):
        prefs = context.preferences.addons.get(__package__)
        if prefs and prefs.preferences.search_paths:
            if 0 <= self.index < len(prefs.preferences.search_paths):
                prefs.preferences.search_paths.remove(self.index)
                self.report({'INFO'}, f"Removed search path at index {self.index}")
            else:
                self.report({'ERROR'}, f"Invalid index: {self.index}")
        return {'FINISHED'}

class DYNAMICLINK_OT_attempt_relink(Operator):
    """Attempt to relink missing libraries using search paths"""
    bl_idname = "dynamiclink.attempt_relink"
    bl_label = "Attempt Relink"
    bl_options = {'REGISTER'}
    
    def execute(self, context):
        prefs = context.preferences.addons.get(__package__)
        if not prefs or not prefs.preferences.search_paths:
            self.report({'ERROR'}, "No search paths configured. Add search paths in addon preferences.")
            return {'CANCELLED'}
        
        # Get missing libraries
        missing_libs = [lib for lib in context.scene.dynamic_link_manager.linked_libraries if lib.is_missing]
        if not missing_libs:
            self.report({'INFO'}, "No missing libraries to relink")
            return {'FINISHED'}
        
        self.report({'INFO'}, f"Attempting to relink {len(missing_libs)} missing libraries...")
        
        # Scan search paths for missing libraries (FMT-inspired approach)
        files_dir_list = []
        try:
            for search_path in prefs.preferences.search_paths:
                if search_path.path:
                    for dirpath, dirnames, filenames in os.walk(bpy.path.abspath(search_path.path)):
                        files_dir_list.append([dirpath, filenames])
        except FileNotFoundError:
            self.report({'ERROR'}, f"Error - Bad file path in search paths")
            return {'CANCELLED'}
        
        # Try to find and relink each missing library
        relinked_count = 0
        indirect_errors = []
        
        for lib_item in missing_libs:
            lib_filename = os.path.basename(lib_item.filepath)
            found = False
            
            # Search through all directories
            for dir_info in files_dir_list:
                dirpath, filenames = dir_info
                
                # Look for exact filename match
                if lib_filename in filenames:
                    new_path = os.path.join(dirpath, lib_filename)
                    try:
                        # Try to relink using Blender's system
                        # This will naturally detect indirect links if they exist
                        bpy.ops.file.find_missing_files()
                        found = True
                        relinked_count += 1
                        break
                    except Exception as e:
                        error_msg = str(e)
                        if "unable to relocate indirectly linked library" in error_msg:
                            indirect_errors.append(lib_item.filepath)
                            print(f"Indirect link detected for: {lib_item.filepath}")
                        else:
                            print(f"Error relinking {lib_item.filepath}: {e}")
            
            if not found:
                print(f"Could not find {lib_filename} in search paths")
        
        # Update the UI to show indirect links
        if indirect_errors:
            self.report({'WARNING'}, f"Found {len(indirect_errors)} indirectly linked libraries")
            # Mark these as having indirect missing
            for lib_item in context.scene.dynamic_link_manager.linked_libraries:
                if lib_item.filepath in indirect_errors:
                    lib_item.has_indirect_missing = True
                    lib_item.indirect_missing_count = 1
        
        self.report({'INFO'}, f"Relink attempt complete. Relinked: {relinked_count}, Indirect: {len(indirect_errors)}")
        return {'FINISHED'}

class DYNAMICLINK_OT_find_in_folders(Operator):
    """Find missing libraries in search folders and subfolders"""
    bl_idname = "dynamiclink.find_in_folders"
    bl_label = "Find in Folders"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        prefs = context.preferences.addons.get(__package__)
        if not prefs or not prefs.preferences.search_paths:
            self.report({'ERROR'}, "No search paths configured. Add search paths in addon preferences.")
            return {'CANCELLED'}
        
        # Get missing libraries
        missing_libs = [lib for lib in context.scene.dynamic_link_manager.linked_libraries if lib.is_missing]
        if not missing_libs:
            self.report({'INFO'}, "No missing libraries to find")
            return {'FINISHED'}
        
        self.report({'INFO'}, f"Searching for {len(missing_libs)} missing libraries...")
        
        # Scan search paths for missing libraries (FMT-inspired approach)
        files_dir_list = []
        try:
            for search_path in prefs.preferences.search_paths:
                if search_path.path:
                    for dirpath, dirnames, filenames in os.walk(bpy.path.abspath(search_path.path)):
                        files_dir_list.append([dirpath, filenames])
        except FileNotFoundError:
            self.report({'ERROR'}, f"Error - Bad file path in search paths")
            return {'CANCELLED'}
        
        # Try to find each missing library
        found_count = 0
        
        for lib_item in missing_libs:
            lib_filename = os.path.basename(lib_item.filepath)
            
            # Search through all directories
            for dir_info in files_dir_list:
                dirpath, filenames = dir_info
                
                # Look for exact filename match
                if lib_filename in filenames:
                    new_path = os.path.join(dirpath, lib_filename)
                    self.report({'INFO'}, f"Found {lib_filename} at: {new_path}")
                    found_count += 1
                    break
        
        if found_count > 0:
            self.report({'INFO'}, f"Found {found_count} libraries in search paths")
        else:
            self.report({'WARNING'}, "No libraries found in search paths")
        
        return {'FINISHED'}

def register():
    bpy.utils.register_class(DYNAMICLINK_OT_replace_linked_asset)
    bpy.utils.register_class(DYNAMICLINK_OT_scan_linked_assets)
    bpy.utils.register_class(DYNAMICLINK_OT_open_linked_file)
    bpy.utils.register_class(DYNAMICLINK_OT_add_search_path)
    bpy.utils.register_class(DYNAMICLINK_OT_remove_search_path)
    bpy.utils.register_class(DYNAMICLINK_OT_attempt_relink)
    bpy.utils.register_class(DYNAMICLINK_OT_find_in_folders)

def unregister():
    bpy.utils.unregister_class(DYNAMICLINK_OT_find_in_folders)
    bpy.utils.unregister_class(DYNAMICLINK_OT_attempt_relink)
    bpy.utils.unregister_class(DYNAMICLINK_OT_remove_search_path)
    bpy.utils.unregister_class(DYNAMICLINK_OT_add_search_path)
    bpy.utils.unregister_class(DYNAMICLINK_OT_open_linked_file)
    bpy.utils.unregister_class(DYNAMICLINK_OT_scan_linked_assets)
    bpy.utils.unregister_class(DYNAMICLINK_OT_replace_linked_asset)
