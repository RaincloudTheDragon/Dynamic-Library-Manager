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
    """Scan scene for directly linked libraries and their status"""
    bl_idname = "dlm.scan_linked_assets"
    bl_label = "Scan Linked Libraries"
    bl_options = {'REGISTER'}

    def execute(self, context):
        # Clear previous results
        context.scene.dynamic_link_manager.linked_libraries.clear()
        
        # Function to check if file exists
        def is_file_missing(filepath):
            if not filepath:
                return True
            try:
                abs_path = bpy.path.abspath(filepath)
            except Exception:
                abs_path = filepath
            return not os.path.isfile(abs_path)
        
        # Function to get library name from path
        def get_library_name(filepath):
            if not filepath:
                return "Unknown"
            return os.path.basename(filepath)
        
        # Helper: naive scan of a .blend file to find referenced library paths
        def scan_blend_for_missing_indirects(blend_path: str) -> bool:
            """Return True if the .blend likely references at least one missing
            library (.blend) path. This uses a conservative byte-string scan that
            never loads data into Blender and is thus context-free and safe.

            Strategy: look for substrings ending in .blend inside the file bytes
            and expand left/right to the nearest NUL byte or line break to
            reconstruct a plausible filesystem path. If any such path does not
            exist on disk, we consider it an indirect missing dependency.
            """
            try:
                if not blend_path or not os.path.exists(blend_path):
                    return False
                with open(blend_path, 'rb') as f:
                    data = f.read()
            except Exception:
                return False

            import re
            base_dir = os.path.dirname(blend_path)
            # Consider absolute Windows paths and Blender // relative paths
            patterns = [
                rb"[A-Za-z]:[\\/][^\r\n\0]*?\.blend",
                rb"\\\\[^\r\n\0]*?\.blend",
                rb"//[^\r\n\0]*?\.blend",
            ]
            for pat in patterns:
                for m in re.finditer(pat, data):
                    try:
                        s = m.group(0).decode('utf-8', errors='ignore').strip().strip('"\'')
                        if s.startswith('//'):
                            rel = s[2:].replace('/', os.sep).replace('\\', os.sep)
                            candidate = os.path.normpath(os.path.join(base_dir, rel))
                        else:
                            candidate = s
                        if not os.path.isfile(candidate):
                            return True
                    except Exception:
                        continue
            return False

        # Reload all libraries up front so Blender populates parent links
        for lib in bpy.data.libraries:
            try:
                if lib.filepath:
                    lib.reload()
            except Exception:
                pass

        # Use Blender's library graph: direct libraries have no parent; indirect
        # libraries have parent != None. We display only direct libraries.
        direct_libs = set()
        for lib in bpy.data.libraries:
            try:
                if lib.parent is None and lib.filepath:
                    direct_libs.add(lib.filepath)
            except Exception:
                continue

        # Only show directly used libraries in the main list
        all_libraries = set(direct_libs)
        
        # Store results in scene properties
        context.scene.dynamic_link_manager.linked_assets_count = len(all_libraries)
        
        # Build set of direct-parent libraries that have at least one missing
        # indirect child, using the library.parent chain.
        missing_indirect_libs = set()
        for lib in bpy.data.libraries:
            try:
                if lib.parent is not None and lib.filepath:
                    try:
                        abs_child = bpy.path.abspath(lib.filepath)
                    except Exception:
                        abs_child = lib.filepath
                    if not os.path.isfile(abs_child):
                        # climb up to the root direct parent
                        root = lib.parent
                        while getattr(root, 'parent', None) is not None:
                            root = root.parent
                        if root and root.filepath:
                            missing_indirect_libs.add(root.filepath)
            except Exception:
                continue

        # Additionally, mark any direct library as INDIRECT if any of its
        # linked ID users are flagged as missing by Blender (e.g., the source
        # .blend no longer contains the datablock). This catches cases where
        # the library file exists but its contents are missing.
        missing_ids_by_library = set()
        def check_missing_on(ids):
            for idb in ids:
                try:
                    lib = getattr(idb, 'library', None)
                    if lib and lib.filepath and getattr(idb, 'is_library_missing', False):
                        missing_ids_by_library.add(lib.filepath)
                except Exception:
                    continue

        check_missing_on(bpy.data.objects)
        check_missing_on(bpy.data.meshes)
        check_missing_on(bpy.data.armatures)
        check_missing_on(bpy.data.materials)
        check_missing_on(bpy.data.node_groups)
        check_missing_on(bpy.data.images)
        check_missing_on(bpy.data.texts)
        check_missing_on(bpy.data.collections)
        check_missing_on(bpy.data.cameras)
        check_missing_on(bpy.data.lights)

        # Create library items for the UI based on definitive indirect set
        library_items = []
        for filepath in sorted(all_libraries):
            if not filepath:
                continue
            lib_item = context.scene.dynamic_link_manager.linked_libraries.add()
            lib_item.filepath = filepath
            lib_item.name = get_library_name(filepath)
            lib_item.is_missing = is_file_missing(filepath)

            # INDIRECT if it has a missing indirect child OR any linked IDs are missing
            lib_item.is_indirect = (filepath in missing_indirect_libs) or (filepath in missing_ids_by_library)

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
            
            # Manual, deterministic relink of exact filename matches.
            relinked_count = 0
            for lib in bpy.data.libraries:
                try:
                    if not lib.filepath:
                        continue
                    lib_filename = os.path.basename(lib.filepath)
                    if lib_filename in found_libraries:
                        new_path = found_libraries[lib_filename]
                        # Only update if currently missing and different
                        current_abs = bpy.path.abspath(lib.filepath)
                        if (not os.path.isfile(current_abs)) or (current_abs != new_path):
                            lib.filepath = new_path
                            try:
                                lib.reload()
                            except Exception:
                                pass
                            relinked_count += 1
                            self.report({'INFO'}, f"Relinked {lib_filename} -> {new_path}")
                except Exception:
                    continue

            if relinked_count == 0:
                self.report({'WARNING'}, "No libraries were relinked; ensure filenames match exactly in search paths.")
            else:
                self.report({'INFO'}, f"✓ Manually relinked {relinked_count} libraries")
        else:
            self.report({'WARNING'}, "No libraries found in search paths - nothing to relink")
        
        # Trigger a rescan so UI reflects current status immediately
        try:
            bpy.ops.dlm.scan_linked_assets()
        except Exception:
            pass
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
