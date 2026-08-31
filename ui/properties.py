# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import bpy
from bpy.types import PropertyGroup
from bpy.props import (
    StringProperty,
    BoolProperty,
    PointerProperty,
    EnumProperty,
)


class DynamicLinkManagerProperties(PropertyGroup):
    # Character Migrator (collapsible): includes Situational Fixes + Tweak Tools
    charmig_section_expanded: BoolProperty(
        name="Character Migrator Expanded",
        description="Show or hide the Character Migrator section",
        default=True,
    )

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

    # Prop Migrator: object-only pairs (meshes, empties, curves, etc. — not armatures)
    propmig_section_expanded: BoolProperty(
        name="Prop Migrator Expanded",
        description="Show or hide the Prop Migrator section",
        default=False,
    )
    original_prop: PointerProperty(
        name="Original Prop",
        description="Object to migrate from (any type except armature)",
        type=bpy.types.Object,
        poll=lambda self, obj: obj and obj.type != "ARMATURE",
    )
    replacement_prop: PointerProperty(
        name="Replacement Prop",
        description="Object to migrate to (any type except armature)",
        type=bpy.types.Object,
        poll=lambda self, obj: obj and obj.type != "ARMATURE",
    )

    # MigBBody: manual mesh pair when CC/iClone-style auto-detection fails
    migbbody_manual_override: BoolProperty(
        name="Manual body meshes",
        description=(
            "Enable to pick original and replacement body meshes manually. "
            "Auto-enables if MigBBody cannot find a base mesh (non-CC rigs)."
        ),
        default=False,
    )
    migbbody_orig_body: PointerProperty(
        name="Original body",
        description="Original character body mesh (shape key source)",
        type=bpy.types.Object,
        poll=lambda self, obj: obj and obj.type == "MESH",
    )
    migbbody_rep_body: PointerProperty(
        name="Replacement body",
        description="Replacement character body mesh (shape key target)",
        type=bpy.types.Object,
        poll=lambda self, obj: obj and obj.type == "MESH",
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
