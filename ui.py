import bpy
from bpy.types import Panel, PropertyGroup, AddonPreferences, UIList
from bpy.props import IntProperty, StringProperty, BoolProperty, CollectionProperty

# Properties for search paths
class SearchPathItem(PropertyGroup):
    path: StringProperty(
        name="Search Path",
        description="Path to search for missing linked libraries",
        subtype='DIR_PATH'
    )

# Properties for individual linked datablocks
class LinkedDatablockItem(PropertyGroup):
    name: StringProperty(name="Name", description="Name of the linked datablock")
    type: StringProperty(name="Type", description="Type of the linked datablock")

# UIList for linked libraries
class DLM_UL_library_list(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        custom_icon = 'FILE_BLEND'
        
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            # Library name and status
            layout.scale_x = 0.4
            layout.label(text=item.name)
            
            # Status indicator
            layout.scale_x = 0.3
            if item.is_missing:
                layout.label(text="MISSING", icon='ERROR')
            elif item.is_indirect:
                layout.label(text="INDIRECT", icon='INFO')
            else:
                layout.label(text="OK", icon='FILE_BLEND')
            
            # File path (abbreviated)
            layout.scale_x = 0.3
            path_text = item.filepath
            if path_text.startswith("\\\\"):
                # Network path: show server name
                parts = path_text.split("\\")
                if len(parts) >= 3:
                    short_path = f"\\\\{parts[2]}\\"
                else:
                    short_path = "\\\\ (network)"
            elif len(path_text) >= 2 and path_text[1] == ':':
                # Drive path: show drive letter
                short_path = f"{path_text[:2]}\\"
            elif path_text.startswith("//"):
                # Relative path
                short_path = "// (relative)"
            else:
                short_path = path_text[:15] + "..." if len(path_text) > 15 else path_text
            layout.label(text=short_path, icon='FILE_FOLDER')
            
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon=custom_icon)

# Properties for a single linked library file
class LinkedLibraryItem(PropertyGroup):
    filepath: StringProperty(name="File Path", description="Path to the linked .blend file")
    name: StringProperty(name="Name", description="Name of the linked .blend file")
    is_missing: BoolProperty(name="Missing", description="True if the linked file is not found")
    is_indirect: BoolProperty(name="Is Indirect", description="True if this is an indirectly linked library")
    is_expanded: BoolProperty(name="Expanded", description="Whether this library item is expanded in the UI", default=True)
    linked_datablocks: CollectionProperty(type=LinkedDatablockItem, name="Linked Datablocks")

class DynamicLinkManagerProperties(PropertyGroup):
    linked_libraries: CollectionProperty(type=LinkedLibraryItem, name="Linked Libraries")
    linked_libraries_index: IntProperty(
        name="Linked Libraries Index",
        description="Index of the selected linked library",
        default=0
    )
    linked_assets_count: IntProperty(
        name="Linked Assets Count",
        description="Number of linked assets found in scene",
        default=0
    )
    
    linked_libraries_expanded: BoolProperty(
        name="Linked Libraries Expanded",
        description="Whether the linked libraries section is expanded",
        default=True
    )
    
    selected_asset_path: StringProperty(
        name="Selected Asset Path",
        description="Path to the currently selected asset",
        default=""
    )

# Addon preferences for search paths
class DynamicLinkManagerPreferences(AddonPreferences):
    bl_idname = __package__
    
    search_paths: CollectionProperty(
        type=SearchPathItem,
        name="Search Paths",
        description="Paths to search for missing linked libraries"
    )
    
    def draw(self, context):
        layout = self.layout
        
                        # Search paths section
        box = layout.box()
        box.label(text="Default Search Paths for Missing Libraries")
        
        # Add button - right-justified
        row = box.row()
        row.alignment = 'RIGHT'
        row.operator("dlm.add_search_path", text="Add search path", icon='ADD')
        
                            # List search paths
        for i, path_item in enumerate(self.search_paths):
            row = box.row()
            row.prop(path_item, "path", text=f"Search path {i+1}")
            # Folder icon for browsing
            row.operator("dlm.browse_search_path", text="", icon='FILE_FOLDER').index = i
            # Remove button
            row.operator("dlm.remove_search_path", text="", icon='REMOVE').index = i

class DLM_PT_main_panel(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Dynamic Link Manager'
    bl_label = "Dynamic Link Manager"
    
    def get_short_path(self, filepath):
        """Extract a short, readable path from a full filepath"""
        if not filepath:
            return "Unknown"
        
        # Handle relative paths
        if filepath.startswith("//"):
            return "// (relative)"
        
        # Handle Windows network paths
        if filepath.startswith("\\\\"):
            # Extract server name (e.g., \\NAS\ or \\NEXUS\)
            parts = filepath.split("\\")
            if len(parts) >= 3:
                return f"\\\\{parts[2]}\\"
            return "\\\\ (network)"
        
        # Handle Windows drive paths
        if len(filepath) >= 2 and filepath[1] == ':':
            return f"{filepath[:2]}\\"
        
        # Handle Unix-style paths
        if filepath.startswith("/"):
            parts = filepath.split("/")
            if len(parts) >= 2:
                return f"/{parts[1]}/"
            return "/ (root)"
        
        # Fallback
        return "Unknown"
    
    def draw_header(self, context):
        layout = self.layout
        layout.operator("preferences.addon_show", text="", icon='PREFERENCES').module = __package__
    
    def draw(self, context):
        layout = self.layout
        props = context.scene.dynamic_link_manager
        
        # Path management buttons
        row = layout.row()
        row.operator("dlm.make_paths_relative", text="Make Paths Relative", icon='FILE_PARENT')
        row.operator("dlm.make_paths_absolute", text="Make Paths Absolute", icon='FILE_FOLDER')
        
        # Main scan section
        box = layout.box()
        box.label(text="Linked Libraries Analysis")
        row = box.row()
        row.operator("dlm.scan_linked_assets", text="Scan Linked Assets", icon='FILE_REFRESH')
        
        # Show total count and missing count
        missing_count = sum(1 for lib in props.linked_libraries if lib.is_missing)
        if missing_count > 0:
            row.label(text=f"({props.linked_assets_count} libraries, {missing_count} missing)", icon='ERROR')
        else:
            row.label(text=f"({props.linked_assets_count} libraries)")
        
        # Show more detailed info if we have results
        if props.linked_assets_count > 0:
            # Linked Libraries section with single dropdown
            row = box.row(align=True)
            
            # Dropdown arrow for the entire section
            icon = 'DISCLOSURE_TRI_DOWN' if props.linked_libraries_expanded else 'DISCLOSURE_TRI_RIGHT'
            row.prop(props, "linked_libraries_expanded", text="", icon=icon, icon_only=True)
            
            # Section header
            row.label(text="Linked Libraries:")
            row.label(text=f"({props.linked_assets_count} libraries)")
            
            # Only show library details if section is expanded
            if props.linked_libraries_expanded:
                # Compact list view
                row = box.row()
                row.template_list("DLM_UL_library_list", "", props, "linked_libraries", props, "linked_libraries_index")
                
                # Action buttons below the list
                row = box.row()
                row.operator("dlm.reload_libraries", text="Reload Libraries", icon='FILE_REFRESH')
                
                # Search Paths Management - integrated into Linked Libraries Analysis
                if props.linked_assets_count > 0:
                    # Get preferences for search paths
                    prefs = context.preferences.addons.get(__package__)
                    
                    # Search paths list - Each path gets its own row with folder icon
                    if prefs and prefs.preferences.search_paths:
                        for i, path_item in enumerate(prefs.preferences.search_paths):
                            row = box.row()
                            row.prop(path_item, "path", text=f"Search path {i+1}")
                            # Folder icon for browsing
                            row.operator("dlm.browse_search_path", text="", icon='FILE_FOLDER').index = i
                            # Remove button
                            row.operator("dlm.remove_search_path", text="", icon='REMOVE').index = i
                    
                    # Add button - Just the + button, right-justified
                    row = box.row()
                    row.alignment = 'RIGHT'
                    row.operator("dlm.add_search_path", text="Add search path", icon='ADD')
                    
                    # Main action button
                    if missing_count > 0:
                        row = box.row()
                        row.operator("dlm.find_libraries_in_folders", text="Find libraries in these folders", icon='VIEWZOOM')
                
                # Show details of selected item at the bottom
                if props.linked_libraries and 0 <= props.linked_libraries_index < len(props.linked_libraries):
                    selected_lib = props.linked_libraries[props.linked_libraries_index]
                    info_box = box.box()
                    
                    # Make entire box red if library is missing
                    if selected_lib.is_missing:
                        info_box.alert = True
                    
                    info_box.label(text=f"Selected: {selected_lib.name}")
                    
                    if selected_lib.is_missing:
                        row = info_box.row()
                        row.label(text="Status: MISSING", icon='ERROR')
                    elif selected_lib.is_indirect:
                        row = info_box.row()
                        row.label(text="Status: INDIRECT", icon='INFO')
                    else:
                        row = info_box.row()
                        row.label(text="Status: OK", icon='FILE_BLEND')
                    
                    # Show full path and Open Blend button
                    row = info_box.row()
                    row.label(text=f"Path: {selected_lib.filepath}", icon='FILE_FOLDER')

                    row = info_box.row()
                    row.operator("dlm.open_linked_file", text="Open Blend", icon='FILE_BLEND').filepath = selected_lib.filepath

                    # Relocate (context-free): lets the user pick a new .blend and we reload the library
                    row = info_box.row()
                    op = row.operator("dlm.relocate_single_library", text="Relocate Library", icon='FILE_FOLDER')
                    op.target_filepath = selected_lib.filepath
                    


def register():
    bpy.utils.register_class(SearchPathItem)
    bpy.utils.register_class(LinkedDatablockItem)
    bpy.utils.register_class(DLM_UL_library_list)
    bpy.utils.register_class(LinkedLibraryItem)
    bpy.utils.register_class(DynamicLinkManagerProperties)
    bpy.utils.register_class(DynamicLinkManagerPreferences)
    bpy.utils.register_class(DLM_PT_main_panel)
    
    # Register properties to scene
    bpy.types.Scene.dynamic_link_manager = bpy.props.PointerProperty(type=DynamicLinkManagerProperties)

def unregister():
    # Unregister properties from scene
    del bpy.types.Scene.dynamic_link_manager
    
    bpy.utils.unregister_class(DLM_PT_main_panel)
    bpy.utils.unregister_class(DynamicLinkManagerPreferences)
    bpy.utils.unregister_class(DynamicLinkManagerProperties)
    bpy.utils.unregister_class(LinkedLibraryItem)
    bpy.utils.unregister_class(DLM_UL_library_list)
    bpy.utils.unregister_class(LinkedDatablockItem)
    bpy.utils.unregister_class(SearchPathItem)
