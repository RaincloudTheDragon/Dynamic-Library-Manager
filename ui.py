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

# FMT-style UIList for linked libraries
class DYNAMICLINK_UL_library_list(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        custom_icon = 'FILE_BLEND'
        
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            # Library name and status (FMT-style layout)
            layout.scale_x = 0.4
            layout.label(text=item.name)
            
            # Status indicator
            layout.scale_x = 0.3
            if item.is_missing:
                layout.label(text="MISSING", icon='ERROR')
            elif item.has_indirect_missing:
                layout.label(text="INDIRECT", icon='ERROR')
            else:
                layout.label(text="OK", icon='FILE_BLEND')
            
            # File path (FMT-style truncated)
            layout.scale_x = 0.3
            path_text = item.filepath
            if len(path_text) > 30:
                path_text = "..." + path_text[-27:]
            layout.label(text=path_text, icon='FILE_FOLDER')
            
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon=custom_icon)

# Properties for a single linked library file
class LinkedLibraryItem(PropertyGroup):
    filepath: StringProperty(name="File Path", description="Path to the linked .blend file")
    name: StringProperty(name="Name", description="Name of the linked .blend file")
    is_missing: BoolProperty(name="Missing", description="True if the linked file is not found")
    has_indirect_missing: BoolProperty(name="Has Indirect Missing", description="True if an indirectly linked blend is missing")
    indirect_missing_count: IntProperty(name="Indirect Missing Count", description="Number of indirectly linked blends that are missing")
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
        
        # Search paths section (FMT-style)
        box = layout.box()
        box.label(text="Default Search Paths for Missing Libraries")
        
        # Add button - right-justified
        row = box.row()
        row.alignment = 'RIGHT'
        row.operator("dlm.add_search_path", text="Add search path", icon='ADD')
        
        # List search paths (FMT-style)
        for i, path_item in enumerate(self.search_paths):
            row = box.row()
            row.prop(path_item, "path", text=f"Search path {i+1}")
            # Folder icon for browsing (FMT-style)
            row.operator("dlm.browse_search_path", text="", icon='FILE_FOLDER').index = i
            # Remove button (FMT-style)
            row.operator("dlm.remove_search_path", text="", icon='REMOVE').index = i

class DLM_PT_main_panel(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Dynamic Link Manager'
    bl_label = "Dynamic Link Manager"
    
    def draw_header(self, context):
        layout = self.layout
        layout.operator("preferences.addon_show", text="", icon='PREFERENCES').module = __package__
    
    def draw(self, context):
        layout = self.layout
        props = context.scene.dynamic_link_manager
        
        # Main scan section (FMT-style)
        box = layout.box()
        box.label(text="Linked Libraries Analysis")
        row = box.row()
        row.operator("dlm.scan_linked_assets", text="Scan Linked Assets", icon='FILE_REFRESH')
        row.label(text=f"({props.linked_assets_count} libraries)")
        
        # Show more detailed info if we have results
        if props.linked_assets_count > 0:
            # Linked Libraries section with single dropdown (FMT-style)
            row = box.row(align=True)
            
            # Dropdown arrow for the entire section
            icon = 'DISCLOSURE_TRI_DOWN' if props.linked_libraries_expanded else 'DISCLOSURE_TRI_RIGHT'
            row.prop(props, "linked_libraries_expanded", text="", icon=icon, icon_only=True)
            
            # Section header
            row.label(text="Linked Libraries:")
            row.label(text=f"({props.linked_assets_count} libraries)")
            
            # Only show library details if section is expanded
            if props.linked_libraries_expanded:
                # FMT-style compact list view
                row = box.row()
                row.template_list("DYNAMICLINK_UL_library_list", "", props, "linked_libraries", props, "linked_libraries_index")
                
                # Action buttons below the list (FMT-style)
                row = box.row()
                row.scale_x = 0.3
                if props.linked_libraries and 0 <= props.linked_libraries_index < len(props.linked_libraries):
                    selected_lib = props.linked_libraries[props.linked_libraries_index]
                    open_op = row.operator("dlm.open_linked_file", text="Open Selected", icon='FILE_BLEND')
                    open_op.filepath = selected_lib.filepath
                else:
                    row.operator("dlm.open_linked_file", text="Open Selected", icon='FILE_BLEND')
                row.scale_x = 0.7
                row.operator("dlm.scan_linked_assets", text="Refresh", icon='FILE_REFRESH')
                
                # Show details of selected item (FMT-style info display)
                if props.linked_libraries and 0 <= props.linked_libraries_index < len(props.linked_libraries):
                    selected_lib = props.linked_libraries[props.linked_libraries_index]
                    info_box = box.box()
                    info_box.label(text=f"Selected: {selected_lib.name}")
                    
                    if selected_lib.is_missing:
                        info_box.label(text="Status: MISSING", icon='ERROR')
                    elif selected_lib.has_indirect_missing:
                        info_box.label(text=f"Status: INDIRECT MISSING ({selected_lib.indirect_missing_count} dependencies)", icon='ERROR')
                    else:
                        info_box.label(text="Status: OK", icon='FILE_BLEND')
                    
                    info_box.label(text=f"Path: {selected_lib.filepath}", icon='FILE_FOLDER')
                
                # Search Paths Management (FMT-style) - integrated into Linked Libraries Analysis
                if props.linked_assets_count > 0:
                    # Get preferences for search paths
                    prefs = context.preferences.addons.get(__package__)
                    
                    # Search paths list (FMT-style) - Each path gets its own row with folder icon
                    if prefs and prefs.preferences.search_paths:
                        for i, path_item in enumerate(prefs.preferences.search_paths):
                            row = box.row()
                            row.prop(path_item, "path", text=f"Search path {i+1}")
                            # Folder icon for browsing (FMT-style)
                            row.operator("dlm.browse_search_path", text="", icon='FILE_FOLDER').index = i
                            # Remove button (FMT-style)
                            row.operator("dlm.remove_search_path", text="", icon='REMOVE').index = i
                    
                    # Add button (FMT-style) - Just the + button, right-justified
                    row = box.row()
                    row.alignment = 'RIGHT'
                    row.operator("dlm.add_search_path", text="", icon='ADD')
                    
                    # Main action button (FMT-style)
                    missing_count = sum(1 for lib in props.linked_libraries if lib.is_missing)
                    if missing_count > 0:
                        row = box.row()
                        row.operator("dlm.fmt_style_find", text="Find libraries in these folders", icon='VIEWZOOM')
        
        # Asset replacement section (FMT-style)
        box = layout.box()
        box.label(text="Asset Replacement")
        
        obj = context.active_object
        if obj:
            box.label(text=f"Selected: {obj.name}")
            
            # Check if object itself is linked
            if obj.library:
                box.label(text=f"Linked from: {obj.library.filepath}")
                row = box.row()
                row.operator("dlm.replace_linked_asset", text="Replace Asset")
            # Check if object's data is linked
            elif obj.data and obj.data.library:
                box.label(text=f"Data linked from: {obj.data.library.filepath}")
                row = box.row()
                row.operator("dlm.replace_linked_asset", text="Replace Asset")
            # Check if it's a linked armature
            elif obj.type == 'ARMATURE' and obj.data and hasattr(obj.data, 'library') and obj.data.library:
                box.label(text=f"Armature linked from: {obj.data.library.filepath}")
                row = box.row()
                row.operator("dlm.replace_linked_asset", text="Replace Asset")
            else:
                box.label(text="Not a linked asset")
        else:
            box.label(text="No object selected")
        
        # Settings section (FMT-style)
        box = layout.box()
        box.label(text="Settings")
        row = box.row()
        row.prop(props, "selected_asset_path", text="Asset Path")

def register():
    bpy.utils.register_class(SearchPathItem)
    bpy.utils.register_class(LinkedDatablockItem)
    bpy.utils.register_class(DYNAMICLINK_UL_library_list)
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
    bpy.utils.unregister_class(DYNAMICLINK_UL_library_list)
    bpy.utils.unregister_class(LinkedDatablockItem)
    bpy.utils.unregister_class(SearchPathItem)
