#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Session search index for Missing Library Propagation (.blend paths under search roots).

Same idea as Atomic Data Manager's process-lifetime Search Missing index: walk once,
match basenames from the flat path list. This module also mirrors the index to
``%TEMP%/dlm_path_stubs/search_index.json`` so a new wizard process can reuse it
(Atomic keeps the index in Blender's long-lived process; our wizard is short-lived).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import types
from typing import Any


_PROCESS_STORE_NAME = "dlm_mlp._process_lifetime"
_INDEX_ATTR = "file_search_index"
_DISK_NAME = "search_index.json"
_HANDOFF_DIR = "dlm_path_stubs"


def _handoff_dir(create: bool = True) -> str:
    base = os.path.join(tempfile.gettempdir(), _HANDOFF_DIR)
    if create:
        os.makedirs(base, exist_ok=True)
    return base


def disk_path() -> str:
    return os.path.join(_handoff_dir(), _DISK_NAME)


def _process_store() -> types.ModuleType:
    """Process-lifetime module (survives re-imports within the same Python process)."""
    mod = sys.modules.get(_PROCESS_STORE_NAME)
    if mod is None:
        mod = types.ModuleType(_PROCESS_STORE_NAME)
        sys.modules[_PROCESS_STORE_NAME] = mod
    return mod


def empty_index() -> dict[str, Any]:
    return {"roots_key": None, "blends": [], "updated_at": 0.0}


def _normalize_roots(roots: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for r in roots or []:
        if not (r or "").strip():
            continue
        try:
            abs_r = os.path.normpath(os.path.abspath(r))
        except Exception:
            abs_r = os.path.normpath(r)
        key = abs_r.replace("/", "\\").upper()
        if key in seen:
            continue
        if not os.path.isdir(abs_r):
            continue
        seen.add(key)
        out.append(abs_r)
    return out


def roots_key(roots: list[str] | None) -> tuple[str, ...]:
    """Order-independent identity for a set of search roots."""
    return tuple(sorted(r.replace("/", "\\").upper() for r in _normalize_roots(roots)))


def _index_from_store() -> dict[str, Any]:
    store = _process_store()
    idx = getattr(store, _INDEX_ATTR, None)
    if not isinstance(idx, dict):
        idx = empty_index()
        setattr(store, _INDEX_ATTR, idx)
    return idx


def clear_index() -> None:
    """Drop memory + disk session index."""
    setattr(_process_store(), _INDEX_ATTR, empty_index())
    path = disk_path()
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _load_disk() -> dict[str, Any] | None:
    path = disk_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    key = data.get("roots_key")
    blends = data.get("blends")
    if not isinstance(key, list) or not isinstance(blends, list):
        return None
    return {
        "roots_key": tuple(str(k) for k in key),
        "blends": [str(p) for p in blends],
        "updated_at": float(data.get("updated_at") or 0.0),
    }


def _save_disk(idx: dict[str, Any]) -> None:
    key = idx.get("roots_key")
    if not key:
        return
    payload = {
        "roots_key": list(key),
        "blends": list(idx.get("blends") or []),
        "updated_at": float(idx.get("updated_at") or time.time()),
    }
    path = disk_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except OSError:
        pass


def store_index(roots: list[str] | None, blends: list[str]) -> dict[str, Any]:
    """Remember walked .blend paths for these roots (memory + disk)."""
    idx = {
        "roots_key": roots_key(roots),
        "blends": list(blends or []),
        "updated_at": time.time(),
    }
    setattr(_process_store(), _INDEX_ATTR, idx)
    _save_disk(idx)
    return idx


def cached_blends_for_roots(roots: list[str] | None) -> list[str] | None:
    """Return cached absolute .blend paths if roots match, else None."""
    key = roots_key(roots)
    if not key:
        return None

    idx = _index_from_store()
    if idx.get("roots_key") == key and isinstance(idx.get("blends"), list):
        return list(idx["blends"])

    disk = _load_disk()
    if disk and disk.get("roots_key") == key:
        setattr(_process_store(), _INDEX_ATTR, disk)
        return list(disk.get("blends") or [])
    return None


def walk_blend_paths(roots: list[str] | None) -> list[str]:
    """Full ``os.walk`` of roots for ``*.blend`` (skip ``.`` directories)."""
    found: list[str] = []
    seen: set[str] = set()
    for root in _normalize_roots(roots):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if not name.lower().endswith(".blend"):
                    continue
                full = os.path.normpath(os.path.join(dirpath, name))
                ukey = full.replace("/", "\\").upper()
                if ukey in seen:
                    continue
                seen.add(ukey)
                found.append(full)
    return found


def get_blend_paths(
    roots: list[str] | None,
    *,
    force_refresh: bool = False,
) -> tuple[list[str], bool]:
    """
    Return (blend_paths, from_cache).

    On miss (or *force_refresh*), walk and store. Invalidates nothing on root
    mismatch — caller should ``clear_index`` when editing roots in the UI.
    """
    if force_refresh:
        clear_index()
    cached = cached_blends_for_roots(roots)
    if cached is not None:
        return cached, True
    blends = walk_blend_paths(roots)
    store_index(roots, blends)
    return blends, False


def index_stats() -> dict[str, Any]:
    """Summary for UI status (memory, falling back to disk)."""
    idx = _index_from_store()
    if not idx.get("roots_key"):
        disk = _load_disk()
        if disk:
            idx = disk
            setattr(_process_store(), _INDEX_ATTR, disk)
    key = idx.get("roots_key")
    blends = idx.get("blends") or []
    return {
        "roots": len(key) if key else 0,
        "blends": len(blends),
        "has_index": bool(key),
    }
