# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

"""Resolve which collection to remove when deleting the original character armature."""

import bpy


def _parent_collection(scene, coll):
    """Return the parent of coll in the scene tree, or None if not found."""
    if coll is None:
        return None
    master = scene.collection
    # Blender 5+: children.__contains__ expects collection name strings, not Collection objects.
    if coll.name in master.children:
        return master
    for p in bpy.data.collections:
        if coll.name in p.children:
            return p
    return None


def _depth_from_scene_root(scene, coll):
    """Depth: number of steps walking up from coll until scene.collection (deeper = larger)."""
    d = 0
    cur = coll
    while cur is not None and cur != scene.collection:
        d += 1
        cur = _parent_collection(scene, cur)
    return d


def _walk_up_chain(scene, coll):
    """Return [inner, ..., top] where top is a direct child of scene.collection (or highest ancestor)."""
    chain = []
    cur = coll
    while cur is not None and cur != scene.collection:
        chain.append(cur)
        cur = _parent_collection(scene, cur)
    return chain


def _collection_contains_object_recursive(coll, ob):
    """True if ob is in coll.objects or in any descendant collection (recursive)."""
    if coll is None or ob is None:
        return False
    for o in coll.objects:
        if o == ob:
            return True
    for child in coll.children:
        if _collection_contains_object_recursive(child, ob):
            return True
    return False


def _deepest_users_collection(scene, armature):
    """Among armature.users_collection, pick the most nested (max depth) as the inner anchor."""
    colls = list(getattr(armature, "users_collection", []) or [])
    if not colls:
        return None
    best = colls[0]
    best_d = _depth_from_scene_root(scene, best)
    for c in colls[1:]:
        d = _depth_from_scene_root(scene, c)
        if d > best_d:
            best_d = d
            best = c
    return best


def _library_ptr(lib):
    """Stable id for comparing library datablocks."""
    return lib.filepath if lib else None


def _pick_remove_target_from_chain(orig, chain, rig_family):
    """
    From walk-up chain [inner..top], choose one collection to remove.
    Prefer the topmost under scene (chain[-1]) so nested linked setups remove the whole instance.
    If orig is linked, prefer the outermost chain entry whose library matches orig.library.
    """
    if not chain:
        return None
    orig_lib = _library_ptr(getattr(orig, "library", None))

    # Linked armature: outermost in chain from same library file (reversed = top -> inner)
    if orig_lib:
        for c in reversed(chain):
            if _library_ptr(getattr(c, "library", None)) == orig_lib:
                return c

    # Local override: prefer outermost collection that participates in override hierarchy
    if getattr(orig, "override_library", None):
        for c in reversed(chain):
            if getattr(c, "override_library", None) is not None:
                return c

    # Rigify: optional name hint — prefer collection whose name matches base armature name
    if rig_family == "RIGIFY":
        name = orig.name
        base = name.replace("_Rigify", "").replace(".001", "").rstrip("0123456789.")
        for c in reversed(chain):
            if c.name == base or base in c.name or c.name in name:
                return c

    # Default: top of chain (direct child of scene.collection subtree root)
    return chain[-1]


def resolve_collection_for_remove_original(orig, rig_family, scene, rep=None):
    """
    Return a collection to remove for Remove Original, or None to fall back to object-only removal.

    Walks up from the deepest users_collection so nested linked rigs remove the outer instance,
    not an inner linked child collection.

    If rep is the replacement armature, never remove a collection whose subtree contains rep
    (avoids deleting both characters when they share a parent collection).

    rig_family: 'RIGIFY' | 'ARP' (ARP skips Rigify name heuristics in _pick_remove_target_from_chain).
    """
    if not orig or orig.type != "ARMATURE" or orig.name not in bpy.data.objects:
        return None

    inner = _deepest_users_collection(scene, orig)
    if inner is None:
        return None

    chain = _walk_up_chain(scene, inner)
    if not chain:
        return None

    if rep is not None and rep.name in bpy.data.objects:
        chain = [c for c in chain if not _collection_contains_object_recursive(c, rep)]
        if not chain:
            return None

    return _pick_remove_target_from_chain(orig, chain, rig_family)
