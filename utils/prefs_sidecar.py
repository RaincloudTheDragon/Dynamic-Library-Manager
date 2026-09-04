"""
Sidecar JSON for DLM addon preferences.

Blender frees AddonPreferences on disable/enable (VS Code Reload Addons),
so values that must survive reloads are mirrored under the user CONFIG dir.
"""

import json
import os

import bpy

SIDECAR_VERSION = 1
SIDECAR_FILENAME = "dlm_prefs.json"

_restoring = False
_last_written = None


def is_restoring():
    return _restoring


def sidecar_path():
    base = bpy.utils.user_resource("CONFIG")
    if not base:
        return None
    return os.path.join(base, SIDECAR_FILENAME)


def prefs_snapshot(prefs):
    from ..ui.preferences import get_prefs_search_paths

    if prefs is None:
        return None
    return {
        "version": SIDECAR_VERSION,
        "symlink_search_paths": list(get_prefs_search_paths(prefs)),
    }


def apply_snapshot(data, prefs):
    from ..ui.preferences import set_prefs_search_paths

    if not data or prefs is None:
        return False

    global _restoring
    _restoring = True
    try:
        if "symlink_search_paths" in data:
            set_prefs_search_paths(
                data.get("symlink_search_paths") or [],
                prefs=prefs,
                ensure_one=True,
            )
        return True
    finally:
        _restoring = False


def load_sidecar():
    path = sidecar_path()
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception as e:
        print(f"[DLM] Could not read prefs sidecar {path}: {e}")
        return None


def save_sidecar(prefs=None):
    global _last_written
    if _restoring:
        return False

    from ..ui.preferences import _addon_prefs

    prefs = prefs or _addon_prefs()
    path = sidecar_path()
    if not prefs or not path:
        return False

    snapshot = prefs_snapshot(prefs)
    if snapshot is None:
        return False

    encoded = json.dumps(snapshot, indent=2, sort_keys=True)
    if encoded == _last_written:
        return False

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.write("\n")
        _last_written = encoded
        return True
    except Exception as e:
        print(f"[DLM] Could not write prefs sidecar {path}: {e}")
        return False


def restore_sidecar_into_prefs(prefs=None):
    from ..ui.preferences import _addon_prefs

    prefs = prefs or _addon_prefs()
    data = load_sidecar()
    if not data or not prefs:
        return False

    ok = apply_snapshot(data, prefs)
    if ok:
        global _last_written
        try:
            _last_written = json.dumps(
                prefs_snapshot(prefs), indent=2, sort_keys=True
            )
        except Exception:
            _last_written = None
    return ok
