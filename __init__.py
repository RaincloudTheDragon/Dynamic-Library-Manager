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
from .ui.properties import DynamicLinkManagerProperties
from .ui.preferences import DynamicLinkManagerPreferences


def ensure_default_search_path():
    addon = bpy.context.preferences.addons.get(__name__)
    if addon and len(addon.preferences.search_paths) == 0:
        addon.preferences.search_paths.add().path = "//"


def register():
    DynamicLinkManagerPreferences.bl_idname = __name__
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.dynamic_link_manager = bpy.props.PointerProperty(type=DynamicLinkManagerProperties)
    bpy.app.handlers.load_post.append(ensure_default_search_path)


def unregister():
    if ensure_default_search_path in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(ensure_default_search_path)
    del bpy.types.Scene.dynamic_link_manager
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


if __name__ == "__main__":
    register()
