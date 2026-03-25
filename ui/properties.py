# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import bpy
from bpy.types import PropertyGroup
from bpy.props import (
    IntProperty,
    StringProperty,
    BoolProperty,
    CollectionProperty,
    PointerProperty,
    EnumProperty,
)


class SearchPathItem(PropertyGroup):
    path: StringProperty(
        name="Search Path",
        description="Path to search for missing linked libraries",
        subtype="DIR_PATH",
    )


class LinkedDatablockItem(PropertyGroup):
    name: StringProperty(name="Name", description="Name of the linked datablock")
    type: StringProperty(name="Type", description="Type of the linked datablock")


class LinkedLibraryItem(PropertyGroup):
    filepath: StringProperty(name="File Path", description="Path to the linked .blend file")
    name: StringProperty(name="Name", description="Name of the linked .blend file")
    is_missing: BoolProperty(name="Missing", description="True if the linked file is not found")
    is_indirect: BoolProperty(name="Is Indirect", description="True if this is an indirectly linked library")
    is_expanded: BoolProperty(name="Expanded", default=True)
    linked_datablocks: CollectionProperty(type=LinkedDatablockItem, name="Linked Datablocks")


class DynamicLinkManagerProperties(PropertyGroup):
    linked_libraries: CollectionProperty(type=LinkedLibraryItem, name="Linked Libraries")
    linked_libraries_index: IntProperty(name="Linked Libraries Index", default=0)
    linked_assets_count: IntProperty(name="Linked Assets Count", default=0)
    linked_libraries_section_expanded: BoolProperty(
        name="Linked Libraries Analysis Expanded",
        description="Show or hide the Linked Libraries Analysis section",
        default=False,
    )
    selected_asset_path: StringProperty(name="Selected Asset Path", default="")

    # Character migrator: rig family (future ARP-specific migration; Remove Original uses it for collection resolution)
    migrator_rig_family: EnumProperty(
        name="Rig family",
        description="Rigify vs Auto-Rig Pro: affects Remove Original collection detection and future bone heuristics",
        items=(
            ("RIGIFY", "Rigify", "Rigify rig naming and defaults"),
            ("ARP", "ARP", "Auto-Rig Pro rig naming and collection behavior"),
        ),
        default="RIGIFY",
    )

    # Character migrator (manual mode)
    migrator_mode: BoolProperty(
        name="Automatic",
        description="Automatic: discover pair by Name_Rigify / Name_Rigify.001. Manual: use fields below",
        default=False,
    )
    original_character: PointerProperty(
        name="Original Character",
        description="Armature to migrate from",
        type=bpy.types.Object,
        poll=lambda self, obj: obj and obj.type == "ARMATURE",
    )
    replacement_character: PointerProperty(
        name="Replacement Character",
        description="Armature to migrate to",
        type=bpy.types.Object,
        poll=lambda self, obj: obj and obj.type == "ARMATURE",
    )

    # Tweak tools (collapsible section)
    tweak_tools_section_expanded: BoolProperty(
        name="Tweak Tools Expanded",
        description="Show or hide the Tweak Tools section",
        default=False,
    )
    tweak_nla_track_name: StringProperty(
        name="NLA Track (bake range)",
        description="If set, bake uses this NLA track on the replacement armature for frame range; else scene range",
        default="",
    )
    tweak_bake_post_clean: BoolProperty(
        name="Post-clean after bake",
        description="Run action clean keyframes and graph decimate (error 0.001) after baking",
        default=False,
    )
