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
