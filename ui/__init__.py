# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

from .operators import OPERATOR_CLASSES
from .panels import DLM_PT_main_panel
from .preferences import (
    DynamicLibraryManagerPreferences,
    DLM_PG_search_root,
    DLM_OT_prefs_search_root_add,
    DLM_OT_prefs_search_root_remove,
)
from . import properties

PANEL_CLASSES = [DLM_PT_main_panel]

CLASSES = (
    properties.DynamicLibraryManagerProperties,
    DLM_PG_search_root,
    DLM_OT_prefs_search_root_add,
    DLM_OT_prefs_search_root_remove,
    DynamicLibraryManagerPreferences,
    DLM_PT_main_panel,
    *OPERATOR_CLASSES,
)

__all__ = [
    "CLASSES",
    "OPERATOR_CLASSES",
    "PANEL_CLASSES",
    "DynamicLibraryManagerPreferences",
    "properties",
]
