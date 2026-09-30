# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

"""Library path helpers for Missing Library Propagation (apply after stubs).

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


def to_blend_relative(abs_path: str) -> str:
    """Return a // relative path from the current blend to *abs_path*, or absolute if unsaved."""
    if not abs_path:
        return ""
    if not bpy.data.filepath:
        return norm_path(abs_path)
    try:
        rel = bpy.path.relpath(abs_path)
        if rel:
            return rel
    except Exception:
        pass
    try:
        start = os.path.dirname(bpy.data.filepath)
        rel = os.path.relpath(abs_path, start)
        return "//" + rel.replace("\\", "/")
    except Exception:
        return norm_path(abs_path)


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


def library_is_baked_character_path(lib) -> bool:
    """True if this library looks like a Characters-Baked / *_baked.blend asset."""
    name = (getattr(lib, "name", "") or "").lower()
    raw = (getattr(lib, "filepath", "") or "").replace("/", "\\").lower()
    if "_baked" in name or "_baked" in os.path.basename(raw):
        return True
    if "characters-baked" in raw:
        return True
    return False


def collect_missing_libraries() -> list[dict[str, Any]]:
    """
    All missing .blend libraries (unique by absolute path).

    Each entry is tagged with ``is_armature`` / ``requires_armature_data`` so the
    wizard can default to armature/baked rows and optionally include the rest.
    """
    out = []
    seen = set()
    for lib in bpy.data.libraries:
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
        is_arm = library_links_armature(lib) or library_is_baked_character_path(lib)
        out.append(
            {
                "archaic_path": archaic,
                "stored_path": raw,
                "basename": os.path.basename(archaic),
                "id_name": lib.name,
                "kind": "library",
                "modern_path": "",
                "is_armature": bool(is_arm),
                # Remap readiness: armature/baked rows must expose armature data after stub load.
                "requires_armature_data": bool(is_arm),
            }
        )
    return out


def _companion_already_resolved(lib, pair: dict[str, Any]) -> bool:
    """
    True if a companion Library no longer needs relocate after a parent remap.

    Either already on the plan modern path, or loaded from some other real file
    that is not the archaic stub (nested relatives next to a relocated parent).
    """
    if library_filepath_is_modern(lib, pair):
        return True
    raw = getattr(lib, "filepath", "") or ""
    if not raw:
        return False
    resolved = abs_blend_path(raw)
    if not resolved or not os.path.isfile(resolved):
        return False
    archaic = norm_path(pair.get("archaic_path") or "").replace("/", "\\").upper()
    if archaic and norm_path(resolved).replace("/", "\\").upper() == archaic:
        return False
    stored = norm_path(pair.get("stored_path") or "").replace("/", "\\").upper()
    raw_u = norm_path(raw).replace("/", "\\").upper()
    if stored and raw_u == stored:
        return False
    return True


def apply_modern_paths(plan: list[dict[str, Any]], *, make_relative: bool = True) -> dict[str, Any]:
    """
    Relocate libraries archaic → modern via ``bpy.ops.wm.lib_relocate`` (reload + remap).

    Matches by absolute archaic path, stored path, then basename / id_name.
    Uses the operator's ``relative_path`` flag for blend-relative // paths.

    Primaries (non-companion) relocate first. After each relocate, remaining
    work is re-checked — companions already pointing at modern (e.g. nested
    paths remapped with the parent) skip a second NAS reload.

    Important: do **not** skip merely because abspath(raw) resolves through a
    stub symlink to the modern file — the stored filepath string can still be
    archaic, and skipping leaves session stuck on stubs_ready (Remap loops).
    Does not save the blend — caller / user decides when to write.
    Never assigns ``Library.filepath`` directly (unsupported; see Blender #163709).
    """
    stats = {
        "libraries": 0,
        "skipped_missing_modern": 0,
        "already_modern": 0,
        "skipped_after_parent": 0,
        "applied": [],
        "failed": [],
    }

    # Snapshot before relocate — wm.lib_relocate mutates bpy.data.libraries.
    # companion flag drives primary-first order.
    work: list[dict[str, Any]] = []
    for lib in list(bpy.data.libraries):
        raw = getattr(lib, "filepath", "") or ""
        if not raw:
            continue
        pair = find_plan_pair_for_library(lib, plan)
        if not pair:
            continue

        modern = pair.get("modern_path") or ""
        if not modern:
            continue
        modern_abs = norm_path(modern)
        if not os.path.isfile(modern_abs):
            stats["skipped_missing_modern"] += 1
            continue

        # Skip only when the *stored* string is already the modern target.
        if library_filepath_is_modern(lib, pair):
            stats["already_modern"] += 1
            continue

        work.append(
            {
                "lib_name": lib.name,
                "raw": raw,
                "modern_abs": modern_abs,
                "companion": bool(pair.get("companion")),
                "pair": pair,
            }
        )

    # Primaries first so nested companions can resolve without a second relocate.
    work.sort(key=lambda item: (1 if item["companion"] else 0, item["lib_name"]))

    for item in work:
        pair = item["pair"]
        modern_abs = item["modern_abs"]
        is_companion = bool(item["companion"])
        # Re-resolve: parent relocate may rename/remap this Library datablock.
        lib = bpy.data.libraries.get(item["lib_name"])
        if lib is None:
            lib = _library_still_needing_pair(pair, companion=is_companion)
        if lib is None:
            # Gone or already remapped away with a parent — no NAS hit needed.
            if is_companion:
                stats["skipped_after_parent"] += 1
            else:
                stats["already_modern"] += 1
            continue

        raw = getattr(lib, "filepath", "") or item["raw"]
        if library_filepath_is_modern(lib, pair):
            if is_companion:
                stats["skipped_after_parent"] += 1
            else:
                stats["already_modern"] += 1
            continue
        if is_companion and _companion_already_resolved(lib, pair):
            stats["skipped_after_parent"] += 1
            continue

        # Stored path still archaic — must relocate this ID.
        lib_name = lib.name
        directory = os.path.dirname(modern_abs) + os.sep
        filename = os.path.basename(modern_abs)
        try:
            result = bpy.ops.wm.lib_relocate(
                library=lib_name,
                filepath=modern_abs,
                directory=directory,
                filename=filename,
                relative_path=bool(make_relative),
            )
        except Exception as e:
            stats["failed"].append({"id_name": lib_name, "from": raw, "error": str(e)})
            continue

        # Operator returns a set like {'FINISHED'} or {'CANCELLED'}.
        if not (isinstance(result, (set, frozenset)) and "FINISHED" in result):
            stats["failed"].append(
                {
                    "id_name": lib_name,
                    "from": raw,
                    "error": f"lib_relocate returned {result!r}",
                }
            )
            continue

        to_fp = _filepath_after_relocate(lib_name, modern_abs)
        stats["libraries"] += 1
        stats["applied"].append(
            {
                "id_name": lib_name,
                "from": raw,
                "to": to_fp or modern_abs,
                "modern_abs": modern_abs,
                "companion": is_companion,
            }
        )
    return stats


def _library_still_needing_pair(pair: dict[str, Any], *, companion: bool = False):
    """Return a Library that still matches *pair* and still needs relocate, or None."""
    for lib in bpy.data.libraries:
        raw = getattr(lib, "filepath", "") or ""
        if not raw:
            continue
        matched = find_plan_pair_for_library(lib, [pair])
        if matched is None:
            continue
        if library_filepath_is_modern(lib, pair):
            continue
        if companion and _companion_already_resolved(lib, pair):
            continue
        return lib
    return None


def _filepath_after_relocate(lib_name: str, modern_abs: str) -> str:
    """Best-effort stored filepath after lib_relocate (name may change)."""
    modern_u = modern_abs.replace("/", "\\").upper()
    lib_after = bpy.data.libraries.get(lib_name)
    if lib_after is not None:
        return getattr(lib_after, "filepath", "") or ""
    for cand in bpy.data.libraries:
        raw_c = getattr(cand, "filepath", "") or ""
        if not raw_c:
            continue
        if norm_path(raw_c).replace("/", "\\").upper() == modern_u:
            return raw_c
        if abs_blend_path(raw_c).replace("/", "\\").upper() == modern_u:
            return raw_c
    return ""


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


def validate_modern_present(plan: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """True if every modern_path in the plan exists on disk."""
    missing = []
    for p in plan:
        mp = p.get("modern_path") or ""
        if mp and not os.path.isfile(mp):
            missing.append(mp)
    return (len(missing) == 0, missing)


def library_filepath_is_modern(lib, pair: dict[str, Any]) -> bool:
    """True if *lib*'s stored filepath already is the pair's modern target."""
    modern = pair.get("modern_path") or ""
    if not modern or not lib:
        return False
    raw = getattr(lib, "filepath", "") or ""
    if not raw:
        return False
    raw_u = norm_path(raw).replace("/", "\\").upper()
    modern_u = norm_path(modern).replace("/", "\\").upper()
    try:
        rel_u = norm_path(to_blend_relative(modern)).replace("/", "\\").upper()
    except Exception:
        rel_u = ""
    if raw_u == modern_u or (rel_u and raw_u == rel_u):
        return True
    # abspath may already resolve to modern after a prior Remap / relative write
    resolved = abs_blend_path(raw)
    if resolved and norm_path(resolved).replace("/", "\\").upper() == modern_u:
        return True
    return False


def _index_plan_pairs(plan: list[dict[str, Any]]) -> tuple[dict, dict, dict]:
    """Build archaic/stored, basename, and id_name lookup tables for *plan*."""
    by_archaic: dict[str, dict[str, Any]] = {}
    by_basename: dict[str, dict[str, Any]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for p in plan:
        if not p.get("modern_path"):
            continue
        for key in (p.get("archaic_path"), p.get("stored_path")):
            if key:
                by_archaic[norm_path(key).upper()] = p
        base = (p.get("basename") or os.path.basename(p.get("archaic_path") or "")).lower()
        if base and base not in by_basename:
            by_basename[base] = p
        idn = (p.get("id_name") or "").lower()
        if idn and idn not in by_id:
            by_id[idn] = p
    return by_archaic, by_basename, by_id


def find_plan_pair_for_library(lib, plan: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the wizard pair matching *lib*, or None."""
    by_archaic, by_basename, by_id = _index_plan_pairs(plan)
    raw = getattr(lib, "filepath", "") or ""
    if not raw:
        return None
    raw_norm = norm_path(raw)
    archaic_resolved = abs_blend_path(raw)
    pair = by_archaic.get(raw_norm.upper())
    if not pair and archaic_resolved:
        pair = by_archaic.get(archaic_resolved.upper())
    if not pair:
        pair = by_id.get((lib.name or "").lower())
    if not pair:
        pair = by_basename.get(os.path.basename(raw_norm).lower())
    if not pair and archaic_resolved:
        pair = by_basename.get(os.path.basename(archaic_resolved).lower())
    return pair


def remap_readiness(plan: list[dict[str, Any]]) -> tuple[bool, str]:
    """
    Whether Remap is safe to run after stubs + Revert.

    Only wizard-plan (in-scope) libraries gate Remap. Other missing libs in the
    blend (lighting, materials, scenes, …) are ignored — use Atomic/FMT for those.

    For each in-scope lib:
      - already on modern path → ok (no stub required)
      - still archaic → modern + archaic stub must exist; lib must load with
        armature/baked data (not is_missing, not empty stub hit)
    """
    needing: list[str] = []
    already_modern: list[str] = []
    still_missing: list[str] = []
    no_arm_data: list[str] = []
    missing_modern: list[str] = []
    missing_stubs: list[str] = []

    for lib in bpy.data.libraries:
        pair = find_plan_pair_for_library(lib, plan)
        if not pair:
            # Out of Missing Library Propagation scope — never blocks Remap.
            continue

        modern = pair.get("modern_path") or ""
        if not modern:
            continue
        if not os.path.isfile(modern):
            missing_modern.append(os.path.basename(modern) or lib.name)
            continue

        if library_filepath_is_modern(lib, pair):
            already_modern.append(lib.name)
            continue

        archaic = pair.get("archaic_path") or ""
        if archaic and not os.path.isfile(archaic):
            missing_stubs.append(os.path.basename(archaic) or lib.name)
            continue

        if getattr(lib, "is_missing", False):
            still_missing.append(lib.name)
            continue
        # Armature/baked rows must expose armature data after stub load (bad hit).
        # Non-armature rows (Propagation scope = All) set requires_armature_data False.
        # Legacy plan rows omit the flag — treat as armature-scoped.
        if pair.get("requires_armature_data", True) and not (
            library_links_armature(lib) or library_is_baked_character_path(lib)
        ):
            no_arm_data.append(lib.name)
            continue
        needing.append(lib.name)

    if missing_modern:
        preview = "; ".join(missing_modern[:4])
        return False, f"{len(missing_modern)} in-scope modern path(s) missing: {preview}"
    if missing_stubs:
        preview = "; ".join(missing_stubs[:4])
        return False, (
            f"{len(missing_stubs)} in-scope stub(s) missing — fix in wizard, then Revert: {preview}"
        )
    if still_missing:
        preview = ", ".join(still_missing[:4])
        return False, (
            f"In-scope library still missing (bad/outdated stub?): {preview} — "
            "swap stub, then Revert"
        )
    if no_arm_data:
        preview = ", ".join(no_arm_data[:4])
        return False, (
            f"In-scope lib loaded without armature data (invalid stub hit?): {preview} — "
            "swap stub, then Revert before Remap"
        )
    if not needing and not already_modern:
        return False, (
            "No in-scope libraries match wizard pairs — Revert after stubs so Blender "
            "reloads archaic paths, or paths were invalidated"
        )
    if not needing:
        return True, f"{len(already_modern)} in-scope librar(ies) already modern"
    extra = f", {len(already_modern)} already modern" if already_modern else ""
    return True, f"{len(needing)} in-scope librar(ies) ready to remap{extra}"


def make_paths_relative() -> None:
    """Wrap Blender make_paths_relative."""
    bpy.ops.file.make_paths_relative()


def save_mainfile_after_rempath() -> bool:
    """
    Persist remapped library paths to disk (legacy helper).

    ``wm.lib_relocate`` usually dirties the blend; always write anyway so a
    no-op Ctrl+S cannot leave archaic relatives on disk.
    """
    if not bpy.data.filepath:
        return False
    try:
        bpy.ops.wm.save_mainfile()
        return True
    except Exception as e:
        print(f"[DLM] save_mainfile after rempath failed: {e}")
        return False


def schedule_save_after_rempath() -> None:
    """Save on a short timer — operators are unsafe inside load_post handlers."""

    def _tick():
        ok = save_mainfile_after_rempath()
        print(f"[DLM] Missing Library Propagation: saved remapped paths={ok}")
        return None

    try:
        bpy.app.timers.register(_tick, first_interval=0.15)
    except Exception as e:
        print(f"[DLM] Could not schedule save after rempath: {e}")
        save_mainfile_after_rempath()


def run_pending_symlink_apply() -> dict[str, Any]:
    """
    Consume session pending_apply after File > Revert / load (legacy).

    Prefer explicit Remap after Revert — new flow does not set pending_apply.
    Never auto-saves; Remap relocates via ``wm.lib_relocate`` (reload + remap).
    """
    from . import stub_handoff

    session = stub_handoff.load_session()
    if not session or not session.get("pending_apply"):
        return {"ok": False, "remapped": 0, "message": "no pending apply"}

    plan = list(session.get("pairs") or [])
    do_relative = bool(session.get("pending_do_relative", True))
    # Clear flag first so a failed apply cannot loop on every load.
    stub_handoff.set_session_status(
        stub_handoff.STATUS_STUBS_READY,
        pending_apply=False,
        pending_do_relative=False,
    )

    if not plan:
        stub_handoff.set_session_status(
            stub_handoff.STATUS_STUBS_READY,
            remapped_count=0,
            message="pending apply had no pairs",
        )
        return {"ok": False, "remapped": 0, "message": "no pairs"}

    ready, reason = remap_readiness(plan)
    if not ready:
        stub_handoff.set_session_status(
            stub_handoff.STATUS_STUBS_READY,
            remapped_count=0,
            message=reason,
        )
        return {"ok": False, "remapped": 0, "message": reason}

    stats = apply_modern_paths(plan, make_relative=do_relative)
    n = int(stats.get("libraries") or 0)
    already = int(stats.get("already_modern") or 0)
    if n > 0:
        stub_handoff.set_session_status(
            stub_handoff.STATUS_APPLY_DONE,
            remapped_count=n,
            message=f"remapped={n} (not saved — save manually when ready)",
            applied=stats.get("applied") or [],
        )
        return {"ok": True, "remapped": n, "message": f"remapped={n}", "applied": stats.get("applied")}

    if already > 0 and already >= len([p for p in plan if p.get("modern_path")]):
        stub_handoff.set_session_status(
            stub_handoff.STATUS_APPLY_DONE,
            remapped_count=0,
            message=f"already modern ({already}); nothing to rewrite",
        )
        return {"ok": True, "remapped": 0, "message": "already modern"}

    stub_handoff.set_session_status(
        stub_handoff.STATUS_STUBS_READY,
        remapped_count=0,
        message="apply matched 0 libraries — paths unchanged",
    )
    return {"ok": False, "remapped": 0, "message": "matched 0 libraries"}
