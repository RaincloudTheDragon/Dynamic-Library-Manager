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


def _all_objects_in_collection(coll):
    """All objects in coll and nested child collections."""
    out = set()
    if coll is None:
        return out

    def walk(c):
        for ob in c.objects:
            out.add(ob)
        for child in c.children:
            walk(child)

    walk(coll)
    return out


def _rna_id_key(idb):
    """(bl_rna.identifier, name) for later lookup after pointers die."""
    if idb is None:
        return None
    try:
        return (idb.bl_rna.identifier, idb.name)
    except Exception:
        return None


def _data_collection_for_kind(kind):
    """Map RNA type identifier to a bpy.data collection, or None."""
    mapping = {
        "Object": bpy.data.objects,
        "Armature": bpy.data.armatures,
        "Mesh": bpy.data.meshes,
        "Curve": bpy.data.curves,
        "MetaBall": bpy.data.metaballs,
        "Lattice": bpy.data.lattices,
        "Camera": bpy.data.cameras,
        "Light": bpy.data.lights,
        "LightProbe": bpy.data.lightprobes,
        "Speaker": bpy.data.speakers,
        "Volume": bpy.data.volumes,
        "GreasePencil": getattr(bpy.data, "grease_pencils", None),
        "GreasePencilv3": getattr(bpy.data, "grease_pencils_v3", None)
        or getattr(bpy.data, "grease_pencils", None),
        "Collection": bpy.data.collections,
        "Action": bpy.data.actions,
        "Material": bpy.data.materials,
        "NodeTree": bpy.data.node_groups,
    }
    return mapping.get(kind)


def _add_id_and_override_refs(entries, idb):
    """Record an ID and its override reference (linked source) for later orphan purge."""
    key = _rna_id_key(idb)
    if key:
        entries.add(key)
    ol = getattr(idb, "override_library", None) if idb else None
    ref = getattr(ol, "reference", None) if ol else None
    ref_key = _rna_id_key(ref)
    if ref_key:
        entries.add(ref_key)


def snapshot_ids_for_remove_original(orig, coll, rep, lib_paths):
    """
    Names of IDs that should die with orig (objects in remove set + their .data +
    override sources + any ID still belonging to orig's libraries).

    Returns a set of (rna_type, name). Pointers are invalid after delete; look up by name.
    """
    entries = set()
    objs = set()
    if orig is not None:
        objs.add(orig)
    objs |= _all_objects_in_collection(coll)

    # Children parented under orig but possibly outside the collection.
    for ob in bpy.data.objects:
        p = ob.parent
        while p is not None:
            if p in objs:
                objs.add(ob)
                break
            p = p.parent

    for ob in objs:
        if rep is not None and ob == rep:
            continue
        _add_id_and_override_refs(entries, ob)
        data = getattr(ob, "data", None)
        if data is not None:
            _add_id_and_override_refs(entries, data)

    if coll is not None and (rep is None or not _collection_contains_object_recursive(coll, rep)):
        _add_id_and_override_refs(entries, coll)

    # Library-owned IDs (incl. indirect armature sources) so localization leftovers are caught.
    for filepath in lib_paths or ():
        for kind, coll_data in (
            ("Object", bpy.data.objects),
            ("Armature", bpy.data.armatures),
            ("Mesh", bpy.data.meshes),
            ("Collection", bpy.data.collections),
        ):
            for idb in coll_data:
                if _id_belongs_to_library(idb, filepath):
                    entries.add((kind, idb.name))

    # Never treat rep (or its armature data) as removable.
    if rep is not None:
        entries.discard(_rna_id_key(rep))
        if getattr(rep, "data", None) is not None:
            entries.discard(_rna_id_key(rep.data))

    return entries


def _id_used_by_in_scene_object(idb):
    """True if an in-scene object is this ID or uses it as .data."""
    if idb is None:
        return False
    for ob in bpy.data.objects:
        if not ob.users_scene:
            continue
        if ob == idb:
            return True
        if getattr(ob, "data", None) == idb:
            return True
    return False


def purge_snapshotted_orphan_ids(entries, keep_ids, report=None):
    """
    Clear fake users and delete snapshotted IDs that nothing in-scene still uses.

    keep_ids: set of live ID pointers (e.g. rep, rep.data) that must never be removed.
    Returns list of \"Type:name\" removed.
    """
    if not entries:
        return []
    keep_ids = {k for k in (keep_ids or ()) if k is not None}
    keep_keys = {_rna_id_key(k) for k in keep_ids}
    keep_keys.discard(None)

    removed = []

    # Objects first so armature/mesh user counts drop, then data-blocks.
    ordered = sorted(entries, key=lambda kn: (0 if kn[0] == "Object" else 1, kn[0], kn[1]))
    for kind, name in ordered:
        if (kind, name) in keep_keys:
            continue
        coll_data = _data_collection_for_kind(kind)
        if coll_data is None:
            continue
        idb = coll_data.get(name)
        if idb is None or idb in keep_ids:
            continue
        if _id_used_by_in_scene_object(idb):
            continue
        if kind == "Object" and getattr(idb, "users_scene", None):
            continue

        try:
            if getattr(idb, "use_fake_user", False):
                idb.use_fake_user = False
        except Exception:
            pass

        try:
            if kind == "Object":
                bpy.data.objects.remove(idb, do_unlink=True)
                removed.append(f"{kind}:{name}")
            elif getattr(idb, "users", 1) == 0:
                coll_data.remove(idb)
                removed.append(f"{kind}:{name}")
        except Exception as e:
            if report:
                report({"WARNING"}, f"Could not purge {kind}:{name}: {e}")

    # Second pass: data-blocks that only lost users after object removal.
    for kind, name in ordered:
        if kind == "Object" or (kind, name) in keep_keys:
            continue
        coll_data = _data_collection_for_kind(kind)
        if coll_data is None:
            continue
        idb = coll_data.get(name)
        if idb is None or idb in keep_ids:
            continue
        if _id_used_by_in_scene_object(idb):
            continue
        try:
            if getattr(idb, "use_fake_user", False):
                idb.use_fake_user = False
        except Exception:
            pass
        try:
            if getattr(idb, "users", 1) == 0:
                coll_data.remove(idb)
                label = f"{kind}:{name}"
                if label not in removed:
                    removed.append(label)
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
    props = context.scene.dynamic_link_manager
    rig_family = getattr(props, "migrator_rig_family", "RIGIFY")
    coll = resolve_collection_for_remove_original(orig, rig_family, context.scene, rep)

    # Libraries + IDs that must die with orig (capture before pointers are invalidated).
    orig_lib_paths = set(collect_id_library_paths(orig))
    for ob in _all_objects_in_collection(coll):
        orig_lib_paths |= collect_id_library_paths(ob)
        data = getattr(ob, "data", None)
        if data is not None:
            orig_lib_paths |= collect_id_library_paths(data)
    orphan_entries = snapshot_ids_for_remove_original(orig, coll, rep, orig_lib_paths)
    keep_ids = {rep, getattr(rep, "data", None)} if rep is not None else set()

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

    try:
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

    # Library unlink can localize armature/mesh data with fake users; drop those orphans.
    purged = purge_snapshotted_orphan_ids(orphan_entries, keep_ids, report=report)
    if purged:
        preview = ", ".join(purged[:12])
        extra = f" (+{len(purged) - 12} more)" if len(purged) > 12 else ""
        report({"INFO"}, f"Purged {len(purged)} leftover ID(s) from original: {preview}{extra}")

    return True

