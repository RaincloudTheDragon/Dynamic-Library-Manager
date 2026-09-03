# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

from .operators import OPERATOR_CLASSES
from .panels import DLM_PT_main_panel
from .preferences import DynamicLibraryManagerPreferences
from . import properties

PANEL_CLASSES = [DLM_PT_main_panel]

CLASSES = (
    properties.DynamicLibraryManagerProperties,
    DynamicLibraryManagerPreferences,
    DLM_PT_main_panel,
    *OPERATOR_CLASSES,
)

__all__ = ["CLASSES", "OPERATOR_CLASSES", "PANEL_CLASSES", "DynamicLibraryManagerPreferences", "properties"]
