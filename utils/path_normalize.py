# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

"""Library path helpers for Symlink Propagation (apply after stubs).

Scope: only missing libraries that contribute armatures (pose / bone data is
lost on load when the lib is missing — Blender #143902). Other missing links
are left for Atomic Remap (recommended), FMT (images), or a generic blendfile
path search / File → External Data.
"""

from __future__ import annotations

import os
from typing import Any

import bpy


def norm_path(fp: str) -> str:
    """Normalize separators to backslash (Blender/Windows style)."""
    return (fp or "").replace("/", "\\")


def abs_blend_path(fp: str) -> str:
    """Absolute path for a blend-relative or absolute filepath."""
    if not fp:
        return ""
    try:
        return os.path.normpath(norm_path(bpy.path.abspath(fp)))
    except Exception:
        return os.path.normpath(norm_path(fp))


def library_links_armature(lib) -> bool:
    """True if *lib* owns or is the override source of any armature data/object."""
    if lib is None:
        return False

    for arm in bpy.data.armatures:
        if arm.library == lib:
            return True

    for obj in bpy.data.objects:
        if obj.type != "ARMATURE":
            continue
        if obj.library == lib:
            return True
        data = obj.data
        if data is not None and getattr(data, "library", None) == lib:
            return True
        # Library override of a linked armature (local object, remote reference).
        ov = getattr(obj, "override_library", None)
        if not ov:
            continue
        ref = getattr(ov, "reference", None)
        if ref is None:
            continue
        if getattr(ref, "library", None) == lib:
            return True
        ref_data = getattr(ref, "data", None)
        if ref_data is not None and getattr(ref_data, "library", None) == lib:
            return True

    return False


def collect_missing_libraries() -> list[dict[str, Any]]:
    """
    Missing libraries that link armatures (unique by absolute path).

    Non-armature libs are skipped — remapping them after a normal load is enough
    (meshes/materials/etc. do not drop pose-side data the way armatures do).
    Prefer Atomic Remap for those; FMT for images; otherwise blendfile search /
    File → External Data.

    Each entry: archaic_path, stored_path, basename, id_name, kind.
    """
    out = []
    seen = set()
    for lib in bpy.data.libraries:
        if not library_links_armature(lib):
            continue
        raw = getattr(lib, "filepath", "") or ""
        if not raw:
            continue
        archaic = abs_blend_path(raw)
        if not archaic:
            continue
        key = archaic.upper()
        if key in seen:
            continue
        seen.add(key)
        if os.path.isfile(archaic):
            continue
        out.append(
            {
                "archaic_path": archaic,
                "stored_path": raw,
                "basename": os.path.basename(archaic),
                "id_name": lib.name,
                "kind": "library",
                "modern_path": "",
            }
        )
    return out


def apply_modern_paths(plan: list[dict[str, Any]]) -> dict[str, int]:
    """
    Rewrite library filepaths from archaic → modern (string only, no reload).

    Call only after archaic paths resolve on disk (stubs present) and the blend
    was reverted/reloaded with libraries present when needed.
    """
    by_archaic = {
        norm_path(p["archaic_path"]).upper(): p["modern_path"]
        for p in plan
        if p.get("archaic_path") and p.get("modern_path")
    }
    stats = {"libraries": 0}

    for lib in bpy.data.libraries:
        raw = getattr(lib, "filepath", "") or ""
        if not raw:
            continue
        archaic = abs_blend_path(raw)
        modern = by_archaic.get(archaic.upper())
        if not modern or norm_path(modern).upper() == archaic.upper():
            continue
        try:
            lib.filepath = modern
        except Exception:
            continue
        stats["libraries"] += 1
    return stats


def validate_archaic_present(plan: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """True if every pair with a modern_path has archaic_path on disk."""
    missing = []
    for p in plan:
        if not p.get("modern_path"):
            continue
        ap = p.get("archaic_path") or ""
        if ap and not os.path.isfile(ap):
            missing.append(ap)
    return (len(missing) == 0, missing)


def make_paths_relative() -> None:
    """Wrap Blender make_paths_relative."""
    bpy.ops.file.make_paths_relative()
