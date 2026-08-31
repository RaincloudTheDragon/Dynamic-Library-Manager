# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

"""Blender app handlers for Symlink Propagation (post-revert apply)."""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent


@persistent
def dlm_load_post(_dummy):
    """After File > Revert / load: run pending symlink apply if requested."""
    try:
        from ..utils import path_normalize

        result = path_normalize.run_pending_symlink_apply()
        if result.get("remapped"):
            print(f"[DLM] Symlink Propagation: remapped {result['remapped']} armature library path(s)")
            for row in (result.get("applied") or [])[:8]:
                print(f"[DLM]   {row.get('id_name')}: {row.get('from')!r} → {row.get('to')!r}")
        elif result.get("message") and result.get("message") != "no pending apply":
            print(f"[DLM] Symlink Propagation apply: {result.get('message')}")
    except Exception as e:
        print(f"[DLM] Symlink Propagation load_post failed: {e}")


def register():
    if dlm_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(dlm_load_post)


def unregister():
    if dlm_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(dlm_load_post)
