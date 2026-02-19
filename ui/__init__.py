# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

from .operators import OPERATOR_CLASSES
from .panels import DLM_PT_main_panel, DLM_UL_library_list
from .preferences import DynamicLinkManagerPreferences
from . import properties

PANEL_CLASSES = [DLM_PT_main_panel, DLM_UL_library_list]

CLASSES = (
    properties.SearchPathItem,
    properties.LinkedDatablockItem,
    properties.LinkedLibraryItem,
    properties.DynamicLinkManagerProperties,
    DynamicLinkManagerPreferences,
    DLM_UL_library_list,
    DLM_PT_main_panel,
    *OPERATOR_CLASSES,
)

__all__ = ["CLASSES", "OPERATOR_CLASSES", "PANEL_CLASSES", "DynamicLinkManagerPreferences", "properties"]
