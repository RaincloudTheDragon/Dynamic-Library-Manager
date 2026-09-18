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


class DynamicLibraryManagerProperties(PropertyGroup):
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

    # Prop Migrator: Object (any type + parent hierarchy) or Collection pair
    propmig_section_expanded: BoolProperty(
        name="Prop Migrator Expanded",
        description="Show or hide the Prop Migrator section",
        default=False,
    )
    propmig_target: EnumProperty(
        name="Target",
        description=(
            "Object: migrate the pair and name-matched parented children. "
            "Collection: migrate all name-matched objects under the asset/override "
            "collections of the picked Original/Replacement objects. "
            "Bone constraints / tweak tools still live under Character Migrator"
        ),
        items=(
            ("OBJECT", "Object", "Solitary object or armature; migrate parented children"),
            ("COLLECTION", "Collection", "Map collections of the picked objects"),
        ),
        default="OBJECT",
    )
    original_prop: PointerProperty(
        name="Original Prop",
        description="Object to migrate from (any type, including armature)",
        type=bpy.types.Object,
    )
    replacement_prop: PointerProperty(
        name="Replacement Prop",
        description="Object to migrate to (any type, including armature)",
        type=bpy.types.Object,
    )
    original_prop_collection: PointerProperty(
        name="Original Collection",
        description="Collection tree to migrate from",
        type=bpy.types.Collection,
    )
    replacement_prop_collection: PointerProperty(
        name="Replacement Collection",
        description="Collection tree to migrate to",
        type=bpy.types.Collection,
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

    # CopyAttr + RetargRelatives: keep replacement object scale when enabled
    retarg_retain_scale: BoolProperty(
        name="Retain scale",
        description=(
            "On: keep replacement object scale (CopyAttr skips scale; RetargRelatives "
            "keeps matching parent scales — for scaled armatures / same scale semantics). "
            "Off (default): unit-scale the rep parent when orig was scene-scaled so "
            "applied-size prop meshes stay correct. Child Of inverses are rebuilt on "
            "retarget either way"
        ),
        default=False,
    )

    # MigNLA: keep replacement object loc/rot/scale (asymmetric hierarchies)
    mignla_retain_transforms: BoolProperty(
        name="Retain transforms",
        description=(
            "MigNLA: keep the replacement object's location/rotation/scale. "
            "On when orig and rep sit in different spaces (e.g. free armature "
            "vs rig parented under the mesh). Off (default): copy unkeyed "
            "object transforms from original (scale still respects Retain scale). "
            "Pose/NLA always migrate"
        ),
        default=False,
    )
