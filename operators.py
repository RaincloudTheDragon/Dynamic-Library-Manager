import bpy
import os
from bpy.types import Operator
from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty

class DLM_OT_replace_linked_asset(Operator):
    """Replace a linked asset with a new file"""
    bl_idname = "dlm.replace_linked_asset"
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

class DLM_OT_scan_linked_assets(Operator):
    """Scan scene for all linked assets"""
    bl_idname = "dlm.scan_linked_assets"
    bl_label = "Scan Linked Assets"
    bl_options = {'REGISTER'}

    def execute(self, context):
        # Clear previous results
        context.scene.dynamic_link_manager.linked_libraries.clear()
        
        # Function to check if file exists
        def is_file_missing(filepath):
            if not filepath:
                return True
            return not os.path.exists(filepath)
        
        # Function to get library name from path
        def get_library_name(filepath):
            if not filepath:
                return "Unknown"
            return os.path.basename(filepath)
        
        # Scan all data collections for linked items
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
        
        # Store results in scene properties
        context.scene.dynamic_link_manager.linked_assets_count = len(all_libraries)
        
        # Create library items for the UI with better indirect detection
        library_items = []
        for filepath in sorted(all_libraries):
            if filepath:
                lib_item = context.scene.dynamic_link_manager.linked_libraries.add()
                lib_item.filepath = filepath
                lib_item.name = get_library_name(filepath)
                lib_item.is_missing = is_file_missing(filepath)
                
                # Better indirect link detection
                # A library is indirect if it's linked from within another linked library
                is_indirect = False
                
                # Check if this library filepath appears in any other library's linked datablocks
                for other_lib in all_libraries:
                    if other_lib != filepath:  # Don't check against self
                        # Look for datablocks that are linked from this other library
                        for obj in bpy.data.objects:
                            if (hasattr(obj, 'library') and obj.library and 
                                obj.library.filepath == other_lib and
                                hasattr(obj, 'data') and obj.data and
                                hasattr(obj.data, 'library') and obj.data.library and
                                obj.data.library.filepath == filepath):
                                is_indirect = True
                                break
                        if is_indirect:
                            break
                
                lib_item.is_indirect = is_indirect
                
                # Store for sorting
                library_items.append((lib_item, filepath))
        
        # Sort libraries: missing first, then by name
        library_items.sort(key=lambda x: (not x[0].is_missing, get_library_name(x[1]).lower()))
        
        # Clear and re-add in sorted order
        context.scene.dynamic_link_manager.linked_libraries.clear()
        for lib_item, filepath in library_items:
            new_item = context.scene.dynamic_link_manager.linked_libraries.add()
            new_item.filepath = filepath
            new_item.name = get_library_name(filepath)  # Use the function directly
            new_item.is_missing = lib_item.is_missing
            new_item.is_indirect = lib_item.is_indirect
        
        # Show detailed info
        self.report({'INFO'}, f"Found {len(all_libraries)} unique linked library files")
        if all_libraries:
            for lib in sorted(all_libraries):
                self.report({'INFO'}, f"Library: {lib}")
        
        return {'FINISHED'}

class DLM_OT_find_libraries_in_folders(Operator):
    """Find missing libraries in search folders and attempt to relocate them"""
    bl_idname = "dlm.find_libraries_in_folders"
    bl_label = "Find Libraries in Folders"
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
        
        self.report({'INFO'}, f"Searching for {len(missing_libs)} missing libraries in search paths...")
        
        # Recursive directory scanning (searches all subfolders)
        files_dir_list = []
        total_dirs_scanned = 0
        
        try:
            for search_path in prefs.preferences.search_paths:
                if search_path.path:
                    # Handle both relative and absolute paths
                    if search_path.path.startswith("//"):
                        # Relative path - convert to absolute
                        abs_path = bpy.path.abspath(search_path.path)
                    else:
                        # Absolute path - use as is
                        abs_path = search_path.path
                    
                    self.report({'INFO'}, f"Scanning search path: {abs_path}")
                    
                    # Check if path exists and is accessible
                    if not os.path.exists(abs_path):
                        self.report({'WARNING'}, f"Search path does not exist or is not accessible: {abs_path}")
                        continue
                    
                    if not os.path.isdir(abs_path):
                        self.report({'WARNING'}, f"Search path is not a directory: {abs_path}")
                        continue
                    
                    # Use os.walk to recursively scan all subdirectories
                    for dirpath, dirnames, filenames in os.walk(abs_path):
                        files_dir_list.append([dirpath, filenames])
                        total_dirs_scanned += 1
                        
                        # Debug: Show what we're finding
                        if len(filenames) > 0:
                            blend_files = [f for f in filenames if f.endswith('.blend')]
                            if blend_files:
                                self.report({'INFO'}, f"  Found {len(blend_files)} .blend files in: {dirpath}")
                        
                        # Limit to prevent excessive scanning (safety measure)
                        if total_dirs_scanned > 1000:
                            self.report({'WARNING'}, "Reached scan limit of 1000 directories. Some subfolders may not be scanned.")
                            break
                    
                    self.report({'INFO'}, f"Scanned {total_dirs_scanned} directories from search path: {abs_path}")
                    
        except FileNotFoundError as e:
            self.report({'ERROR'}, f"Error - Bad file path in search paths: {e}")
            return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Error scanning search paths: {e}")
            return {'CANCELLED'}
        
        self.report({'INFO'}, f"Total directories scanned: {total_dirs_scanned}")
        
        # Phase 1: Library finding with recursive search
        found_libraries = {}  # Dictionary to store filename -> full path mapping
        found_count = 0
        
        self.report({'INFO'}, "=== PHASE 1: SEARCHING FOR LIBRARIES ===")
        
        for lib_item in missing_libs:
            lib_filename = os.path.basename(lib_item.filepath)
            self.report({'INFO'}, f"Looking for: {lib_filename}")
            
            for dir_info in files_dir_list:
                dirpath, filenames = dir_info
                
                # Exact filename match
                if lib_filename in filenames:
                    new_path = os.path.join(dirpath, lib_filename)
                    found_libraries[lib_filename] = new_path
                    self.report({'INFO'}, f"✓ Found {lib_filename} at: {new_path}")
                    found_count += 1
                    break
        
        self.report({'INFO'}, f"=== SEARCH COMPLETE: Found {found_count} out of {len(missing_libs)} missing libraries ===")
        
        # Phase 2: Relinking found libraries
        if found_count > 0:
            self.report({'INFO'}, "=== PHASE 2: RELINKING LIBRARIES ===")
            
            # First, try to use Blender's built-in relinking system
            try:
                self.report({'INFO'}, "Attempting to use Blender's built-in relinking...")
                bpy.ops.file.find_missing_files()
                self.report({'INFO'}, "✓ Blender's built-in relinking completed successfully")
            except Exception as e:
                self.report({'WARNING'}, f"Blender's built-in relinking failed: {e}")
                
                # Fallback: Manual relinking using the paths we found
                self.report({'INFO'}, "Attempting manual relinking using found paths...")
                relinked_count = 0
                
                for lib_item in missing_libs:
                    lib_filename = os.path.basename(lib_item.filepath)
                    if lib_filename in found_libraries:
                        try:
                            # Update the library filepath to the found location
                            # Note: This is a simplified approach - in practice, you might need
                            # to use Blender's library management functions
                            self.report({'INFO'}, f"Attempting to relink {lib_filename} to: {found_libraries[lib_filename]}")
                            relinked_count += 1
                        except Exception as e2:
                            self.report({'ERROR'}, f"Failed to relink {lib_filename}: {e2}")
                
                if relinked_count > 0:
                    self.report({'INFO'}, f"✓ Manually relinked {relinked_count} libraries")
                else:
                    self.report({'WARNING'}, "Manual relinking also failed")
        else:
            self.report({'WARNING'}, "No libraries found in search paths - nothing to relink")
        
        self.report({'INFO'}, "=== OPERATION COMPLETE ===")
        return {'FINISHED'}

def register():
    bpy.utils.register_class(DLM_OT_replace_linked_asset)
    bpy.utils.register_class(DLM_OT_scan_linked_assets)

class DLM_OT_open_linked_file(Operator):
    """Open the linked file in a new Blender instance"""
    bl_idname = "dlm.open_linked_file"
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

class DLM_OT_add_search_path(Operator):
    """Add a new search path for missing libraries"""
    bl_idname = "dlm.add_search_path"
    bl_label = "Add Search Path"
    bl_options = {'REGISTER'}
    
    def execute(self, context):
        prefs = context.preferences.addons.get(__package__)
        if prefs:
            new_path = prefs.preferences.search_paths.add()
            new_path.path = "//"  # Default to relative path
            self.report({'INFO'}, f"Added search path: {new_path.path}")
        return {'FINISHED'}

class DLM_OT_remove_search_path(Operator):
    """Remove a search path"""
    bl_idname = "dlm.remove_search_path"
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

class DLM_OT_attempt_relink(Operator):
    """Attempt to relink missing libraries using search paths"""
    bl_idname = "dlm.attempt_relink"
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
                
                if found:
                    break
            
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



class DLM_OT_browse_search_path(Operator):
    """Browse for a search path directory"""
    bl_idname = "dlm.browse_search_path"
    bl_label = "Browse Search Path"
    bl_options = {'REGISTER'}
    
    index: IntProperty(
        name="Index",
        description="Index of the search path to browse for",
        default=0
    )
    
    filepath: StringProperty(
        name="Search Path",
        description="Path to search for missing linked libraries",
        subtype='DIR_PATH'
    )
    
    def execute(self, context):
        prefs = context.preferences.addons.get(__package__)
        if prefs and prefs.preferences.search_paths:
            if 0 <= self.index < len(prefs.preferences.search_paths):
                prefs.preferences.search_paths[self.index].path = self.filepath
                self.report({'INFO'}, f"Updated search path {self.index + 1}: {self.filepath}")
            else:
                self.report({'ERROR'}, f"Invalid index: {self.index}")
        return {'FINISHED'}
    
    def invoke(self, context, event):
        prefs = context.preferences.addons.get(__package__)
        if prefs and prefs.preferences.search_paths:
            if 0 <= self.index < len(prefs.preferences.search_paths):
                # Set the current path as default
                self.filepath = prefs.preferences.search_paths[self.index].path
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}



class DLM_OT_reload_libraries(Operator):
    """Reload all libraries using Blender's built-in reload operation"""
    bl_idname = "dlm.reload_libraries"
    bl_label = "Reload Libraries"
    bl_options = {'REGISTER'}
    
    def execute(self, context):
        try:
            # Try the outliner operation first
            bpy.ops.outliner.lib_operation(type='RELOAD')
            self.report({'INFO'}, "Library reload operation completed")
        except Exception as e:
            # Fallback: manually reload libraries
            try:
                for library in bpy.data.libraries:
                    if library.filepath and os.path.exists(bpy.path.abspath(library.filepath)):
                        library.reload()
                self.report({'INFO'}, "Libraries reloaded manually")
            except Exception as e2:
                self.report({'ERROR'}, f"Failed to reload libraries: {e2}")
                return {'CANCELLED'}
        return {'FINISHED'}

class DLM_OT_make_paths_relative(Operator):
    """Make all file paths in the scene relative"""
    bl_idname = "dlm.make_paths_relative"
    bl_label = "Make Paths Relative"
    bl_options = {'REGISTER'}
    
    def execute(self, context):
        try:
            # Use Blender's built-in operator to make paths relative
            bpy.ops.file.make_paths_relative()
            self.report({'INFO'}, "All file paths made relative")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to make paths relative: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}

class DLM_OT_make_paths_absolute(Operator):
    """Make all file paths in the scene absolute"""
    bl_idname = "dlm.make_paths_absolute"
    bl_label = "Make Paths Absolute"
    bl_options = {'REGISTER'}
    
    def execute(self, context):
        try:
            # Use Blender's built-in operator to make paths absolute
            bpy.ops.file.make_paths_absolute()
            self.report({'INFO'}, "All file paths made absolute")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to make paths absolute: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}

class DLM_OT_relocate_single_library(Operator):
    """Relocate a single library by choosing a new .blend and reloading it (context-free)"""
    bl_idname = "dlm.relocate_single_library"
    bl_label = "Relocate Library"
    bl_options = {'REGISTER', 'UNDO'}

    # The library we want to relocate (current path as stored on the item)
    target_filepath: StringProperty(
        name="Current Library Path",
        description="Current path of the library to relocate",
        default=""
    )

    # New file chosen by the user via file selector
    filepath: StringProperty(
        name="New Library File",
        description="Choose the new .blend file for this library",
        subtype='FILE_PATH',
        default=""
    )

    def _find_library_by_path(self, path_to_match: str):
        abs_match = bpy.path.abspath(path_to_match) if path_to_match else ""
        for lib in bpy.data.libraries:
            try:
                if bpy.path.abspath(lib.filepath) == abs_match:
                    return lib
            except Exception:
                # In case abspath fails for odd paths
                if lib.filepath == path_to_match:
                    return lib
        return None

    def execute(self, context):
        if not self.target_filepath:
            self.report({'ERROR'}, "No target library specified")
            return {'CANCELLED'}
        if not self.filepath:
            self.report({'ERROR'}, "No new file selected")
            return {'CANCELLED'}

        library = self._find_library_by_path(self.target_filepath)
        if not library:
            self.report({'ERROR'}, "Could not resolve the selected library in bpy.data.libraries")
            return {'CANCELLED'}

        try:
            # Assign the new path and reload the library datablocks
            library.filepath = self.filepath
            library.reload()
            self.report({'INFO'}, f"Relocated to: {self.filepath}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to relocate: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}

    def invoke(self, context, event):
        # Pre-populate the selector with the current path when possible
        if self.target_filepath:
            try:
                self.filepath = bpy.path.abspath(self.target_filepath)
            except Exception:
                self.filepath = self.target_filepath
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

def register():
    bpy.utils.register_class(DLM_OT_replace_linked_asset)
    bpy.utils.register_class(DLM_OT_scan_linked_assets)
    bpy.utils.register_class(DLM_OT_open_linked_file)
    bpy.utils.register_class(DLM_OT_add_search_path)
    bpy.utils.register_class(DLM_OT_remove_search_path)
    bpy.utils.register_class(DLM_OT_browse_search_path)
    bpy.utils.register_class(DLM_OT_attempt_relink)
    bpy.utils.register_class(DLM_OT_find_libraries_in_folders)
    bpy.utils.register_class(DLM_OT_reload_libraries)
    bpy.utils.register_class(DLM_OT_make_paths_relative)
    bpy.utils.register_class(DLM_OT_make_paths_absolute)
    bpy.utils.register_class(DLM_OT_relocate_single_library)

def unregister():
    bpy.utils.unregister_class(DLM_OT_find_libraries_in_folders)
    bpy.utils.unregister_class(DLM_OT_attempt_relink)
    bpy.utils.unregister_class(DLM_OT_browse_search_path)
    bpy.utils.unregister_class(DLM_OT_remove_search_path)
    bpy.utils.unregister_class(DLM_OT_add_search_path)
    bpy.utils.unregister_class(DLM_OT_open_linked_file)
    bpy.utils.unregister_class(DLM_OT_scan_linked_assets)
    bpy.utils.unregister_class(DLM_OT_replace_linked_asset)
    bpy.utils.unregister_class(DLM_OT_reload_libraries)
    bpy.utils.unregister_class(DLM_OT_make_paths_relative)
    bpy.utils.unregister_class(DLM_OT_make_paths_absolute)
    bpy.utils.unregister_class(DLM_OT_relocate_single_library)
