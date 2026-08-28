# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import bpy
from bpy.types import AddonPreferences
from bpy.props import StringProperty


class DynamicLinkManagerPreferences(AddonPreferences):
    bl_idname = __package__.rsplit(".", 1)[0]

    symlink_search_roots: StringProperty(
        name="Default Search Roots",
        description=(
            "Semicolon-separated folders used as the Symlink Propagation "
            "wizard's starting search roots (basename lookup for modern .blend files)"
        ),
        default="",
        subtype="NONE",
    )

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="Symlink Propagation (armature libs only)")
        box.prop(self, "symlink_search_roots", text="")
        box.label(text="Separate folders with semicolons.", icon="INFO")
        box.label(
            text="Armature libs only. Others: Atomic Remap (recommended), FMT (images), or blendfile search.",
            icon="INFO",
        )


def parse_search_roots(text: str) -> list[str]:
    """Split preference text into unique existing-or-any directory paths."""
    import os

    out: list[str] = []
    seen: set[str] = set()
    for part in (text or "").replace("\n", ";").split(";"):
        part = part.strip().strip('"').strip("'")
        if not part:
            continue
        norm = os.path.normpath(part)
        key = norm.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
    return out
