# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

"""Shared helpers for Dynamic Link Manager."""

import bpy


def descendants(armature):
    """Return a set of objects whose parent chain leads to the given armature."""
    out = set()
    for ob in bpy.data.objects:
        p = ob.parent
        while p:
            if p == armature:
                out.add(ob)
                break
            p = p.parent
    return out


def collection_containing_armature(armature):
    """
    Return a collection that contains the armature (for linked character context).
    Prefers a collection whose name matches the character base (e.g. "Steve" for Steve_Rigify).
    """
    if not armature or armature.name not in bpy.data.objects:
        return None
    colls = getattr(armature, "users_collection", []) or []
    if not colls:
        return None
    name = armature.name
    base = name.replace("_Rigify", "").replace(".001", "").rstrip("0123456789.")
    for c in colls:
        if c.name == base or base in c.name or c.name in name:
            return c
    return colls[0]
