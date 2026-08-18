# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

"""Remove Original: resolve collection, remap leftover refs, purge unused libraries."""

import os

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


def _norm_lib_path(filepath):
    """Comparable library path (absolute, normcase) for matching bpy.data.libraries entries."""
    if not filepath:
        return ""
    try:
        abs_p = bpy.path.abspath(filepath)
    except Exception:
        abs_p = filepath
    return os.path.normcase(os.path.normpath(abs_p))


def collect_id_library_paths(idb):
    """Library filepaths that keep this ID (direct .library or override reference)."""
    paths = set()
    if idb is None:
        return paths

    def add_from(block):
        if block is None:
            return
        lib = getattr(block, "library", None)
        if lib and lib.filepath:
            paths.add(lib.filepath)
        ol = getattr(block, "override_library", None)
        ref = getattr(ol, "reference", None) if ol else None
        if ref is not None:
            rlib = getattr(ref, "library", None)
            if rlib and rlib.filepath:
                paths.add(rlib.filepath)

    add_from(idb)
    add_from(getattr(idb, "data", None))
    return paths


def _id_belongs_to_library(idb, filepath):
    """True if idb is linked from filepath or is an override of that library."""
    if idb is None or not filepath:
        return False
    want = _norm_lib_path(filepath)
    for p in collect_id_library_paths(idb):
        if _norm_lib_path(p) == want:
            return True
    return False


def _library_by_path(filepath):
    """Return bpy.data.libraries entry matching filepath, or None."""
    want = _norm_lib_path(filepath)
    if not want:
        return None
    for lib in bpy.data.libraries:
        if _norm_lib_path(lib.filepath) == want:
            return lib
    return None


def _scene_users_of_library(filepath):
    """In-scene objects that still belong to this library (override or linked)."""
    hits = []
    for ob in bpy.data.objects:
        if not ob.users_scene:
            continue
        if _id_belongs_to_library(ob, filepath) or _id_belongs_to_library(getattr(ob, "data", None), filepath):
            hits.append(f"object:{ob.name}")
    return hits


def find_library_holdouts(filepath):
    """Human-readable leftover users pinning a library (objects, constraints, drivers)."""
    out = []
    for ob in bpy.data.objects:
        if _id_belongs_to_library(ob, filepath):
            where = "in-scene" if ob.users_scene else "data-only"
            if ob.library:
                kind = "linked"
            elif getattr(ob, "override_library", None):
                kind = "override"
            else:
                kind = "local"
            out.append(f"{ob.name} ({kind}, {where})")
        for c in getattr(ob, "constraints", []):
            t = getattr(c, "target", None)
            if t is not None and _id_belongs_to_library(t, filepath):
                out.append(f"{ob.name} constraint {c.name} -> {t.name}")
        if ob.type == "ARMATURE" and ob.pose:
            for pb in ob.pose.bones:
                for c in pb.constraints:
                    t = getattr(c, "target", None)
                    if t is not None and _id_belongs_to_library(t, filepath):
                        out.append(f"{ob.name}.{pb.name} constraint {c.name} -> {t.name}")
        ad = getattr(ob, "animation_data", None)
        if not ad:
            continue
        for fcu in ad.drivers:
            drv = getattr(fcu, "driver", None)
            if drv is None:
                continue
            for var in drv.variables:
                for tgt in var.targets:
                    if tgt.id is not None and _id_belongs_to_library(tgt.id, filepath):
                        out.append(f"{ob.name} driver {fcu.data_path} id={tgt.id.name}")
    return out


def _remove_unused_local_ids_for_library(filepath):
    """Delete local (override) objects/collections of this library that are not in any scene."""
    for ob in list(bpy.data.objects):
        if ob.users_scene or ob.library:
            continue
        if not _id_belongs_to_library(ob, filepath):
            continue
        try:
            bpy.data.objects.remove(ob, do_unlink=True)
        except Exception:
            pass
    for coll in list(bpy.data.collections):
        if getattr(coll, "library", None):
            continue
        if not _id_belongs_to_library(coll, filepath):
            continue
        # Skip if any remaining in-scene object lives in this collection.
        in_scene = False
        for ob in getattr(coll, "objects", []):
            if ob.users_scene:
                in_scene = True
                break
        if in_scene:
            continue
        try:
            bpy.data.collections.remove(coll)
        except Exception:
            pass


def purge_unused_library(filepath):
    """
    Drop a linked library if nothing in any scene still uses it.
    Returns (removed: bool, leftover_msgs: list[str]).
    """
    if not filepath or _library_by_path(filepath) is None:
        return True, []
    scene_users = _scene_users_of_library(filepath)
    if scene_users:
        return False, scene_users
    _remove_unused_local_ids_for_library(filepath)
    lib = _library_by_path(filepath)
    if lib is None:
        return True, []
    try:
        bpy.data.libraries.remove(lib, do_unlink=True)
        return True, []
    except Exception as e:
        leftovers = find_library_holdouts(filepath)
        leftovers.append(str(e))
        return False, leftovers


def remove_unused_override_armatures(keep=None):
    """
    Remove armature library-overrides that are not in any scene (ghost leftovers like Steve).
    Returns list of (name, library_paths) for each removed armature.
    """
    removed = []
    for ob in list(bpy.data.objects):
        if ob.type != "ARMATURE" or ob is keep:
            continue
        if not getattr(ob, "override_library", None):
            continue
        if ob.users_scene:
            continue
        name = ob.name
        lib_paths = collect_id_library_paths(ob)
        try:
            bpy.data.objects.remove(ob, do_unlink=True)
            removed.append((name, lib_paths))
        except Exception:
            pass
    return removed


def _action_used_by(action, ob):
    """True if ob's animation_data still references action (active or NLA)."""
    if not action or not ob:
        return False
    ad = getattr(ob, "animation_data", None)
    if not ad:
        return False
    if ad.action == action:
        return True
    for track in ad.nla_tracks:
        for strip in track.strips:
            if strip.action == action:
                return True
    return False


def _orig_actions(orig):
    """Actions currently assigned on orig (active + NLA)."""
    actions = set()
    ad = getattr(orig, "animation_data", None)
    if not ad:
        return actions
    if ad.action:
        actions.add(ad.action)
    for track in ad.nla_tracks:
        for strip in track.strips:
            if strip.action:
                actions.add(strip.action)
    return actions


def _rename_rep_actions(rep):
    """Strip .rep suffix from replacement actions after orig is gone."""
    renamed = []
    if not rep or not getattr(rep, "animation_data", None):
        return renamed
    ad = rep.animation_data

    def _strip_rep(action):
        if action is None or ".rep" not in action.name:
            return None
        old = action.name
        action.name = old.replace(".rep", "")
        return f"{old} -> {action.name}"

    msg = _strip_rep(ad.action)
    if msg:
        renamed.append(msg)
    for track in ad.nla_tracks:
        for strip in track.strips:
            msg = _strip_rep(strip.action)
            if msg:
                renamed.append(msg)
    return renamed


def run_remove_original(context, orig, rep, report):
    """
    Remap leftover orig→rep refs, delete orig's collection/object, purge unused libraries.

    report: Operator.report. Returns True on success, False if orig could not be deleted.
    """
    from .remap_usages import remap_object_usages

    name = orig.name
    orig_lib_paths = collect_id_library_paths(orig)

    # Final sweep: remap remaining scene refs off orig (orig is about to die).
    if rep is not None and orig != rep:
        remap_object_usages(orig, rep, orig_to_rep={orig: rep})

    # Only drop orig actions that nothing surviving still uses (incl. rep).
    removed_actions = []
    for action in list(_orig_actions(orig)):
        if _action_used_by(action, rep):
            continue
        keep = False
        for ob in bpy.data.objects:
            if ob is orig:
                continue
            if _action_used_by(action, ob):
                keep = True
                break
        if keep:
            continue
        action_name = action.name
        try:
            bpy.data.actions.remove(action)
            removed_actions.append(action_name)
        except Exception as e:
            report({"WARNING"}, f"Could not remove action {action_name}: {e}")
    if removed_actions:
        report({"INFO"}, f"Removed {len(removed_actions)} action(s) from original")

    props = context.scene.dynamic_link_manager
    rig_family = getattr(props, "migrator_rig_family", "RIGIFY")
    try:
        coll = resolve_collection_for_remove_original(orig, rig_family, context.scene, rep)
        if coll:
            coll_name = coll.name
            context.scene.dynamic_link_manager.original_character = None
            try:
                bpy.data.collections.remove(coll)
                report({"INFO"}, f"Removed collection: {coll_name}")
            except Exception as remove_err:
                report({"WARNING"}, f"Collection {coll_name} removal issue: {remove_err}")
                try:
                    bpy.data.objects.remove(orig, do_unlink=True)
                    report({"INFO"}, f"Removed original object: {name}")
                except Exception as e2:
                    report({"ERROR"}, f"Could not remove original after collection failure: {e2}")
                    return False
        else:
            bpy.data.objects.remove(orig, do_unlink=True)
            context.scene.dynamic_link_manager.original_character = None
            report({"INFO"}, f"Removed original character: {name}")
    except Exception as e:
        report({"ERROR"}, f"Failed to remove original: {e}")
        return False

    renamed = _rename_rep_actions(rep)
    if renamed:
        report({"INFO"}, f"Renamed {len(renamed)} replacement action(s)")

    # Ghost override armatures not in any scene (e.g. leftover Steve after character swap).
    ghost_libs = set()
    for gname, paths in remove_unused_override_armatures(keep=rep):
        ghost_libs.update(paths)
        report({"INFO"}, f"Removed unused override armature: {gname}")

    purge_paths = set(orig_lib_paths) | ghost_libs
    for filepath in sorted(purge_paths, key=lambda p: p.lower()):
        ok, leftovers = purge_unused_library(filepath)
        lib_label = os.path.basename(filepath) if filepath else filepath
        if ok:
            report({"INFO"}, f"Purged unused library: {lib_label}")
        elif leftovers:
            preview = "; ".join(leftovers[:8])
            extra = f" (+{len(leftovers) - 8} more)" if len(leftovers) > 8 else ""
            report({"WARNING"}, f"Library still in use ({lib_label}): {preview}{extra}")

    return True

