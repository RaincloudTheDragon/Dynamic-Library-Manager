# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTIBILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import bpy

from .ui import CLASSES
from .ui.properties import DynamicLibraryManagerProperties
from .ui.preferences import DynamicLibraryManagerPreferences
from .utils import handlers as dlm_handlers


def register():
    DynamicLibraryManagerPreferences.bl_idname = __name__
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.dynamic_library_manager = bpy.props.PointerProperty(type=DynamicLibraryManagerProperties)
    from .ui.preferences import _addon_prefs, ensure_search_path_collection
    prefs = _addon_prefs()
    try:
        from .utils.prefs_sidecar import restore_sidecar_into_prefs
        restore_sidecar_into_prefs(prefs)
    except Exception as e:
        print(f"[DLM] Prefs sidecar restore failed: {e}")
    if prefs and hasattr(prefs, "symlink_search_paths"):
        ensure_search_path_collection(prefs.symlink_search_paths)
    dlm_handlers.register()


def unregister():
    try:
        from .utils.prefs_sidecar import save_sidecar
        save_sidecar()
    except Exception:
        pass
    dlm_handlers.unregister()
    del bpy.types.Scene.dynamic_library_manager
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


if __name__ == "__main__":
    register()
