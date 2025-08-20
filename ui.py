import bpy
from bpy.types import Panel, PropertyGroup
from bpy.props import IntProperty, StringProperty

class DynamicLinkManagerProperties(PropertyGroup):
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
        
        # Asset replacement section
        box = layout.box()
        box.label(text="Asset Replacement")
        
        obj = context.active_object
        if obj:
            box.label(text=f"Selected: {obj.name}")
            if obj.library:
                box.label(text=f"Linked from: {obj.library.filepath}")
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
    bpy.utils.register_class(DynamicLinkManagerProperties)
    bpy.utils.register_class(DYNAMICLINK_PT_main_panel)
    
    # Register properties to scene
    bpy.types.Scene.dynamic_link_manager = bpy.props.PointerProperty(type=DynamicLinkManagerProperties)

def unregister():
    # Unregister properties from scene
    del bpy.types.Scene.dynamic_link_manager
    
    bpy.utils.unregister_class(DYNAMICLINK_PT_main_panel)
    bpy.utils.unregister_class(DynamicLinkManagerProperties)
