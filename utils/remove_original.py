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


def _object_in_inscene_collection_instance(ob):
    """
    True when *ob* lives inside any collection instanced by an in-scene empty.

    Characters inside ``induct_characters`` (and similar setups) have
    ``users_scene == 0`` on their armatures even though the instance empty is
    in the scene. Remove Original must not treat them as ghost leftovers.
    """
    if ob is None:
        return False
    for scene_ob in bpy.data.objects:
        if not scene_ob.users_scene:
            continue
        inst_coll = getattr(scene_ob, "instance_collection", None)
        if inst_coll is None:
            continue
        if _collection_contains_object_recursive(inst_coll, ob):
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

    For library overrides, prefer the override asset root (``override_library.hierarchy_root``
    collection, e.g. ``Regina``) — not a local staging collection (``Props``, ``Body``) that also
    lists the same objects twice in the outliner.

    Otherwise walks up from the deepest users_collection so nested linked rigs remove the outer
    instance, not an inner linked child collection.

    If rep is the replacement armature, never remove a collection whose subtree contains rep
    (avoids deleting both characters when they share a parent collection).

    rig_family: 'RIGIFY' | 'ARP' (ARP skips Rigify name heuristics in _pick_remove_target_from_chain).
    """
    if not orig or orig.type != "ARMATURE" or orig.name not in bpy.data.objects:
        return None

    from .remap_usages import _override_asset_root_for_armature, is_library_override_id

    if is_library_override_id(orig):
        asset_root = _override_asset_root_for_armature(orig, scene)
        if asset_root is not None:
            if rep is None or rep.name not in bpy.data.objects:
                return asset_root
            if not _collection_contains_object_recursive(asset_root, rep):
                return asset_root

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
        inst_coll = getattr(ob, "instance_collection", None)
        if inst_coll is None:
            continue
        if _id_belongs_to_library(inst_coll, filepath):
            hits.append(f"instance:{ob.name} -> {inst_coll.name}")
            continue
        for nested in _all_objects_in_collection(inst_coll):
            if _id_belongs_to_library(nested, filepath) or _id_belongs_to_library(
                getattr(nested, "data", None), filepath
            ):
                hits.append(f"instanced:{nested.name} via {ob.name}")
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
    """Delete local (override) objects/collections of this library that are not in any scene.

    Never deletes IDs that still serve as (or share) an override template for a
    remaining override — soft-unlinked sibling instances must stay alive.
    """
    from .remap_usages import (
        _override_reference,
        is_library_override_id,
        live_override_template_ids,
    )

    protected_refs = live_override_template_ids()
    # Linked refs still pointed at by ANY local override (incl. in-scene rep).
    live_refs = set(protected_refs)
    for ob in bpy.data.objects:
        if getattr(ob, "library", None) or not is_library_override_id(ob):
            continue
        ref = _override_reference(ob)
        if ref is not None:
            live_refs.add(ref)

    for ob in list(bpy.data.objects):
        if ob.users_scene or ob.library:
            continue
        if not _id_belongs_to_library(ob, filepath):
            continue
        # Soft-hidden sibling: shares a template still used by a live override.
        if is_library_override_id(ob):
            ref = _override_reference(ob)
            if ref is not None and ref in live_refs:
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
        if is_library_override_id(coll):
            ref = _override_reference(coll)
            if ref is not None and ref in live_refs:
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
    # Soft-unlinked override instances still pin the library as a template.
    from .remap_usages import is_library_override_id

    data_only = []
    for ob in bpy.data.objects:
        if ob.users_scene or ob.library:
            continue
        if not is_library_override_id(ob):
            continue
        if _id_belongs_to_library(ob, filepath) or _id_belongs_to_library(
            getattr(ob, "data", None), filepath
        ):
            data_only.append(f"object:{ob.name} (override template, hidden)")
    if data_only:
        return False, data_only
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


def _template_keep_ids_for_collection(coll):
    """IDs that must survive Remove Original when coll is kept as override template."""
    keep = set()
    if coll is None:
        return keep
    keep.add(coll)
    for ob in _all_objects_in_collection(coll):
        keep.add(ob)
        data = getattr(ob, "data", None)
        if data is not None:
            keep.add(data)
    return keep


def remove_unused_override_armatures(keep=None, keep_ids=None):
    """
    Remove armature library-overrides that are not in any scene (ghost leftovers like Steve).

    keep_ids: extra object pointers that must not be removed (override template armatures).
    Skips armatures that share an override.reference with any remaining override —
    those are soft-hidden sibling templates, not ghosts.
    """
    from .remap_usages import _override_reference, is_library_override_id

    removed = []
    protected = {k for k in (keep_ids or ()) if k is not None}
    if keep is not None:
        protected.add(keep)

    live_refs = set()
    for ob in bpy.data.objects:
        if ob.library or not is_library_override_id(ob):
            continue
        if not (ob.users_scene or _object_in_inscene_collection_instance(ob) or ob in protected):
            continue
        ref = _override_reference(ob)
        if ref is not None:
            live_refs.add(ref)

    for ob in list(bpy.data.objects):
        if ob.type != "ARMATURE" or ob in protected:
            continue
        if not getattr(ob, "override_library", None):
            continue
        if ob.users_scene or _object_in_inscene_collection_instance(ob):
            continue
        ref = _override_reference(ob)
        if ref is not None and ref in live_refs:
            continue
        name = ob.name
        lib_paths = collect_id_library_paths(ob)
        try:
            bpy.data.objects.remove(ob, do_unlink=True)
            removed.append((name, lib_paths))
        except Exception:
            pass
    return removed


def _unlink_collection_from_parents(coll):
    """Remove coll from every parent collection; keep the override datablock."""
    if coll is None:
        return
    for pc in list(bpy.data.collections):
        try:
            if coll.name in pc.children:
                pc.children.unlink(coll)
        except Exception:
            pass


def _objects_in_override_hierarchy(orig):
    """All objects sharing orig's override hierarchy_root (full linked asset instance)."""
    if orig is None:
        return set()
    ol = getattr(orig, "override_library", None)
    if ol is None or getattr(ol, "hierarchy_root", None) is None:
        return {orig}
    hr = ol.hierarchy_root
    out = set()
    for ob in bpy.data.objects:
        ool = getattr(ob, "override_library", None)
        if ool is not None and ool.hierarchy_root == hr:
            out.add(ob)
    return out


def _unlink_object_from_local_collections(ob, keep_coll):
    """
    Drop *ob* from local staging collections only.

    Override collections (and nested override subtrees) are kept so templates survive.
    Fixes outliner duplicates when the same override object is also linked under Props/Body.
    """
    if ob is None:
        return
    for uc in list(getattr(ob, "users_collection", []) or []):
        if uc == keep_coll:
            continue
        if getattr(uc, "override_library", None) is not None:
            continue
        try:
            uc.objects.unlink(ob)
        except Exception:
            pass


def _remove_orig_sibling_override_instance(orig, coll, report):
    """
    Hide the orig override instance from the scene without deleting any IDs.

    Sibling overrides (Regina / Regina.001) share linked override templates.
    Deleting orig override objects — or their datablocks — breaks the rep on
    save/reload. Unlink the override root collection and hide its hierarchy;
    also unlink objects from local staging collections that duplicate outliner entries.
    """
    from .remap_usages import object_in_collection_tree

    coll_name = coll.name if coll else "(none)"
    if coll is not None:
        _unlink_collection_from_parents(coll)

    hierarchy = _objects_in_override_hierarchy(orig)
    coll_objects = _all_objects_in_collection(coll) if coll else set()
    targets = hierarchy if hierarchy else coll_objects
    if orig is not None:
        targets = set(targets)
        targets.add(orig)

    hidden = 0
    for ob in targets:
        _unlink_object_from_local_collections(ob, coll)
        parent = ob.parent
        if (
            parent is not None
            and coll is not None
            and not object_in_collection_tree(parent, coll)
            and parent not in targets
        ):
            try:
                ob.parent = None
            except Exception:
                pass
        try:
            ob.hide_viewport = True
            ob.hide_render = True
            hidden += 1
        except Exception:
            pass

    if report:
        report(
            {"INFO"},
            f"Unlinked original override instance: {coll_name} "
            f"(kept {hidden} object(s) as override template)",
        )


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


def _add_id_local_only(entries, idb):
    """Record a local ID for orphan purge — never the linked override.reference template."""
    if idb is None:
        return
    # Linked datablocks are override templates / library sources — never orphan-purge them.
    if getattr(idb, "library", None) is not None:
        return
    key = _rna_id_key(idb)
    if key:
        entries.add(key)


def snapshot_ids_for_remove_original(orig, coll, rep, lib_paths):
    """
    Names of local IDs that should die with orig (objects in remove set + their .data).

    Does **not** include linked ``override_library.reference`` IDs or other library
    sources — those are Blender override templates. Library cleanup is handled only
    by ``purge_unused_library`` after scene-user checks.
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
        _add_id_local_only(entries, ob)
        data = getattr(ob, "data", None)
        if data is not None:
            _add_id_local_only(entries, data)

    if coll is not None and (rep is None or not _collection_contains_object_recursive(coll, rep)):
        _add_id_local_only(entries, coll)

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


def _id_is_live_override_template(idb):
    """True if *idb* is linked or is still an override.reference for any local override."""
    if idb is None:
        return False
    if getattr(idb, "library", None) is not None:
        return True
    from .remap_usages import live_override_template_ids

    return idb in live_override_template_ids()


def purge_snapshotted_orphan_ids(entries, keep_ids, report=None):
    """
    Clear fake users and delete snapshotted IDs that nothing in-scene still uses.

    keep_ids: set of live ID pointers (e.g. rep, rep.data) that must never be removed.
    Never deletes linked IDs or live override templates.
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
        # Name collision: local orig \"Kirk_Rigify\" deleted → get() may return the
        # linked library namesake that rep still overrides. Never remove those.
        if getattr(idb, "library", None) is not None:
            continue
        if _id_is_live_override_template(idb):
            continue
        if _id_used_by_in_scene_object(idb):
            continue
        if kind == "Object" and getattr(idb, "users_scene", None):
            continue
        # Never orphan-purge remaining library overrides (soft-hidden templates).
        if getattr(idb, "override_library", None) is not None:
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
        if _id_is_live_override_template(idb):
            continue
        if getattr(idb, "override_library", None) is not None:
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
    from .remap_usages import (
        build_override_collection_object_map,
        consolidate_migration_armature,
        needs_template_preserving_remove,
        remap_object_usages,
        remap_parents,
        resolve_migration_armature,
    )

    name = orig.name
    props = context.scene.dynamic_link_manager
    rig_family = getattr(props, "migrator_rig_family", "RIGIFY")
    ghost = rep
    rep = resolve_migration_armature(rep, context.scene)
    if ghost is not None and rep is not None and ghost != rep:
        rep = consolidate_migration_armature(ghost, rep, context.scene)
    if props.replacement_character != rep:
        props.replacement_character = rep
    coll = resolve_collection_for_remove_original(orig, rig_family, context.scene, rep)
    soft_remove = needs_template_preserving_remove(orig, rep, coll, context.scene)
    # Belt: any override tree must soft-unlink — collections.remove destroys templates.
    from .remap_usages import collection_tree_has_overrides, is_library_override_id

    if not soft_remove and (
        is_library_override_id(orig) or collection_tree_has_overrides(coll)
    ):
        soft_remove = True
        if report:
            report(
                {"INFO"},
                "Original is a library override — soft-unlinking to preserve templates",
            )
    template_keep = _template_keep_ids_for_collection(coll) if soft_remove else set()

    # Libraries + IDs that must die with orig (capture before pointers are invalidated).
    orig_lib_paths = set(collect_id_library_paths(orig))
    for ob in _all_objects_in_collection(coll):
        orig_lib_paths |= collect_id_library_paths(ob)
        data = getattr(ob, "data", None)
        if data is not None:
            orig_lib_paths |= collect_id_library_paths(data)
    # Never purge a library the replacement still overrides / links.
    rep_lib_paths = set()
    if rep is not None:
        rep_lib_paths |= collect_id_library_paths(rep)
        rep_data = getattr(rep, "data", None)
        if rep_data is not None:
            rep_lib_paths |= collect_id_library_paths(rep_data)
        from .remap_usages import override_root_collection

        rep_root_early = override_root_collection(rep, context.scene)
        if rep_root_early is not None:
            for ob in _all_objects_in_collection(rep_root_early):
                rep_lib_paths |= collect_id_library_paths(ob)
                data = getattr(ob, "data", None)
                if data is not None:
                    rep_lib_paths |= collect_id_library_paths(data)
    rep_lib_norm = {_norm_lib_path(p) for p in rep_lib_paths if p}
    if rep_lib_norm:
        blocked = [p for p in orig_lib_paths if _norm_lib_path(p) in rep_lib_norm]
        orig_lib_paths = {p for p in orig_lib_paths if _norm_lib_path(p) not in rep_lib_norm}
        if blocked and report:
            report(
                {"INFO"},
                f"Skipped purging {len(blocked)} librar(ies) still used by replacement",
            )

    orphan_entries = snapshot_ids_for_remove_original(orig, coll, rep, orig_lib_paths)
    keep_ids = set()
    if rep is not None:
        keep_ids.add(rep)
        if getattr(rep, "data", None) is not None:
            keep_ids.add(rep.data)
        from .remap_usages import (
            _override_reference,
            live_override_template_ids,
            override_root_collection,
        )

        # Protect linked templates by name — after local orig \"Kirk_Rigify\" is
        # deleted, orphan lookup by name must not remove the linked namesake.
        keep_ids |= live_override_template_ids()
        ref = _override_reference(rep)
        if ref is not None:
            keep_ids.add(ref)
            ref_data = getattr(ref, "data", None)
            if ref_data is not None:
                keep_ids.add(ref_data)

        rep_root = override_root_collection(rep, context.scene)
        if rep_root is not None:
            for ob in _all_objects_in_collection(rep_root):
                keep_ids.add(ob)
                data = getattr(ob, "data", None)
                if data is not None:
                    keep_ids.add(data)
                oref = _override_reference(ob)
                if oref is not None:
                    keep_ids.add(oref)
    if soft_remove and coll is not None:
        keep_ids |= template_keep

    # Final sweep: remap remaining scene refs off orig (+ GEO/Jiffy in its override).
    if rep is not None and orig != rep:
        mapping = build_override_collection_object_map(orig, rep)
        mapping[orig] = rep
        # Parents first — deleting orig otherwise clears them (e.g. RIG-Pallet-Jack).
        remap_parents(mapping)
        remap_object_usages(orig, rep, orig_to_rep=mapping)

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
            # Snapshot objects in the remove tree before unlink — collection.remove can
            # leave armatures alive (mesh users / external parent like a path cart) with
            # empty users_collection (Outliner shows them under the parent only).
            doomed = set(_all_objects_in_collection(coll))
            if orig is not None:
                doomed.add(orig)
            # Never delete IDs still owned by the replacement hierarchy (shared WGTS,
            # etc.). Wiping those corrupts the rep override and triggers a clean
            # resync on save/reload (rest-pose armature, animated orphan leftover).
            keep = set()
            if rep is not None:
                keep.add(rep)
                rep_data = getattr(rep, "data", None)
                if rep_data is not None:
                    keep.add(rep_data)
                from .remap_usages import override_root_collection

                rep_root = override_root_collection(rep, context.scene)
                if rep_root is not None:
                    keep |= _all_objects_in_collection(rep_root)
                for ob in list(keep):
                    data = getattr(ob, "data", None)
                    if data is not None:
                        keep.add(data)
            doomed -= keep

            context.scene.dynamic_link_manager.original_character = None
            if soft_remove:
                _remove_orig_sibling_override_instance(orig, coll, report)
            else:
                # Final guard: never collections.remove an override hierarchy.
                if is_library_override_id(coll) or collection_tree_has_overrides(coll):
                    _remove_orig_sibling_override_instance(orig, coll, report)
                    soft_remove = True
                else:
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
                    # Finish off exclusive survivors (collectionless but still parented / mesh-used).
                    removed_extra = 0
                    for ob in list(doomed):
                        if ob is None:
                            continue
                        try:
                            if ob in keep or ob == rep:
                                continue
                            if is_library_override_id(ob):
                                continue
                            _ = ob.name  # raises ReferenceError if already freed
                        except ReferenceError:
                            continue
                        try:
                            bpy.data.objects.remove(ob, do_unlink=True)
                            removed_extra += 1
                        except Exception:
                            pass
                    if removed_extra:
                        report({"INFO"}, f"Removed {removed_extra} leftover object(s) from original tree")
        else:
            # No collection — still never delete a library-override armature.
            if is_library_override_id(orig):
                try:
                    orig.hide_viewport = True
                    orig.hide_render = True
                except Exception:
                    pass
                context.scene.dynamic_link_manager.original_character = None
                soft_remove = True
                report(
                    {"INFO"},
                    f"Hid original override armature: {name} (template preserved)",
                )
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
    for gname, paths in remove_unused_override_armatures(keep=rep, keep_ids=template_keep):
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
    if soft_remove:
        if report:
            report({"INFO"}, "Skipped orphan purge (override template preserved)")
        purged = []
    else:
        purged = purge_snapshotted_orphan_ids(orphan_entries, keep_ids, report=report)
    if purged:
        preview = ", ".join(purged[:12])
        extra = f" (+{len(purged) - 12} more)" if len(purged) > 12 else ""
        report({"INFO"}, f"Purged {len(purged)} leftover ID(s) from original: {preview}{extra}")

    return True

