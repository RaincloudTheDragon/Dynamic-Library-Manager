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
    linked_datablocks: CollectionProperty(type=LinkedDatablockItem, name="Linked Datablocks")

class DynamicLinkManagerProperties(PropertyGroup):
    linked_libraries: CollectionProperty(type=LinkedLibraryItem, name="Linked Libraries")
    linked_assets_count: IntProperty(
        name="Linked Assets Count",
        description="Number of linked assets found in scene",
        default=0
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
            box.label(text="Note: Counts unique library files, not individual objects")
            
            # List of linked libraries
            box.label(text="Linked Libraries:")
            for lib_item in props.linked_libraries:
                sub_box = box.box()
                row = sub_box.row(align=True)
                
                # Highlight missing files in red with warning icon
                if lib_item.is_missing:
                    row.label(text=f"MISSING: {lib_item.name}", icon='ERROR')
                    row.label(text=lib_item.filepath, icon='FILE_FOLDER')
                else:
                    row.label(text=lib_item.name, icon='FILE_BLEND')
                    row.label(text=lib_item.filepath, icon='FILE_FOLDER')
                
                # Add open button
                open_op = row.operator("dynamiclink.open_linked_file", text="Open", icon='FILE_BLEND')
                open_op.filepath = lib_item.filepath
                
                # Draw linked datablocks underneath
                if lib_item.linked_datablocks:
                    col = sub_box.column(align=True)
                    col.label(text="  Linked Datablocks:")
                    for db_item in lib_item.linked_datablocks:
                        col.label(text=f"    - {db_item.name} ({db_item.type})")
        
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
