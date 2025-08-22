import bpy
from bpy.types import Panel, PropertyGroup
from bpy.props import IntProperty, StringProperty, BoolProperty, CollectionProperty

# Properties for individual linked datablocks
class LinkedDatablockItem(PropertyGroup):
    name: StringProperty(name="Name", description="Name of the linked datablock")
    type: StringProperty(name="Type", description="Type of the linked datablock")

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

class DYNAMICLINK_PT_main_panel(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Dynamic Link Manager'
    bl_label = "Asset Replacement"
    
    def draw(self, context):
        layout = self.layout
        props = context.scene.dynamic_link_manager
        
        # Scan section
        box = layout.box()
        box.label(text="Scene Analysis")
        row = box.row()
        row.operator("dynamiclink.scan_linked_assets", text="Scan Linked Assets")
        row.label(text=f"Libraries: {props.linked_assets_count}")
        
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
                 # List all libraries
                 for i, lib_item in enumerate(props.linked_libraries):
                     # Create a box for each library
                     if lib_item.is_missing or lib_item.has_indirect_missing:
                         sub_box = box.box()
                         sub_box.alert = True  # Red tint for missing/indirect missing
                     else:
                         sub_box = box.box()
                     
                     # Library name and status
                     row1 = sub_box.row(align=True)
                     row1.label(text=lib_item.name, icon='FILE_BLEND')
                     
                     # Status indicator
                     if lib_item.is_missing:
                         row1.label(text="MISSING", icon='ERROR')
                     elif lib_item.has_indirect_missing:
                         row1.label(text="INDIRECT MISSING", icon='ERROR')
                     
                     # File path (truncated for space)
                     row2 = sub_box.row()
                     path_text = lib_item.filepath
                     if len(path_text) > 50:
                         path_text = "..." + path_text[-47:]
                     row2.label(text=path_text, icon='FILE_FOLDER')
                     
                     # Warning message for indirect missing
                     if lib_item.has_indirect_missing and not lib_item.is_missing:
                         row3 = sub_box.row()
                         row3.label(text=f"⚠️ {lib_item.indirect_missing_count} indirectly linked blend(s) missing", icon='ERROR')
                         row3.label(text="Open this blend to relink", icon='INFO')
                     
                     # Action buttons row
                     row4 = sub_box.row(align=True)
                     
                     # Open button
                     if lib_item.is_missing or lib_item.has_indirect_missing:
                         open_op = row4.operator("dynamiclink.open_linked_file", text="Open", icon='ERROR')
                     else:
                         open_op = row4.operator("dynamiclink.open_linked_file", text="Open", icon='FILE_BLEND')
                     open_op.filepath = lib_item.filepath
                

        
        # Asset replacement section
        box = layout.box()
        box.label(text="Asset Replacement")
        
        obj = context.active_object
        if obj:
            box.label(text=f"Selected: {obj.name}")
            
            # Check if object itself is linked
            if obj.library:
                box.label(text=f"Linked from: {obj.library.filepath}")
                row = box.row()
                row.operator("dynamiclink.replace_linked_asset", text="Replace Asset")
            # Check if object's data is linked
            elif obj.data and obj.data.library:
                box.label(text=f"Data linked from: {obj.data.library.filepath}")
                row = box.row()
                row.operator("dynamiclink.replace_linked_asset", text="Replace Asset")
            # Check if it's a linked armature
            elif obj.type == 'ARMATURE' and obj.data and hasattr(obj.data, 'library') and obj.data.library:
                box.label(text=f"Armature linked from: {obj.data.library.filepath}")
                row = box.row()
                row.operator("dynamiclink.replace_linked_asset", text="Replace Asset")
            else:
                box.label(text="Not a linked asset")
        else:
            box.label(text="No object selected")
        
        # Batch operations section
        box = layout.box()
        box.label(text="Batch Operations")
        row = box.row()
        row.operator("dynamiclink.scan_linked_assets", text="Refresh Scan")
        
        # Settings section
        box = layout.box()
        box.label(text="Settings")
        row = box.row()
        row.prop(props, "selected_asset_path", text="Asset Path")

def register():
    bpy.utils.register_class(LinkedDatablockItem)
    bpy.utils.register_class(LinkedLibraryItem)
    bpy.utils.register_class(DynamicLinkManagerProperties)
    bpy.utils.register_class(DYNAMICLINK_PT_main_panel)
    
    # Register properties to scene
    bpy.types.Scene.dynamic_link_manager = bpy.props.PointerProperty(type=DynamicLinkManagerProperties)

def unregister():
    # Unregister properties from scene
    del bpy.types.Scene.dynamic_link_manager
    
    bpy.utils.unregister_class(DYNAMICLINK_PT_main_panel)
    bpy.utils.unregister_class(DynamicLinkManagerProperties)
    bpy.utils.unregister_class(LinkedLibraryItem)
    bpy.utils.unregister_class(LinkedDatablockItem)
