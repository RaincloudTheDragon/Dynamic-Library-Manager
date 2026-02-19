# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

import os
import re
import bpy


def _is_file_missing(filepath):
    if not filepath:
        return True
    try:
        abs_path = bpy.path.abspath(filepath)
    except Exception:
        abs_path = filepath
    return not os.path.isfile(abs_path)


def _get_library_name(filepath):
    return os.path.basename(filepath) if filepath else "Unknown"


def scan_linked_assets(context, report):
    props = context.scene.dynamic_link_manager
    props.linked_libraries.clear()

    for lib in bpy.data.libraries:
        try:
            if lib.filepath:
                lib.reload()
        except Exception:
            pass

    direct_libs = set()
    for lib in bpy.data.libraries:
        try:
            if getattr(lib, "parent", None) is None and lib.filepath:
                direct_libs.add(lib.filepath)
        except Exception:
            continue
    all_libraries = set(direct_libs)
    props.linked_assets_count = len(all_libraries)

    missing_indirect_libs = set()
    for lib in bpy.data.libraries:
        try:
            if getattr(lib, "parent", None) is not None and lib.filepath:
                try:
                    abs_child = bpy.path.abspath(lib.filepath)
                except Exception:
                    abs_child = lib.filepath
                if not os.path.isfile(abs_child):
                    root = lib.parent
                    while getattr(root, "parent", None) is not None:
                        root = root.parent
                    if root and root.filepath:
                        missing_indirect_libs.add(root.filepath)
        except Exception:
            continue

    missing_ids_by_library = set()
    for idb in list(bpy.data.objects) + list(bpy.data.meshes) + list(bpy.data.armatures) + list(bpy.data.materials) + list(bpy.data.node_groups) + list(bpy.data.images) + list(bpy.data.texts) + list(bpy.data.collections) + list(bpy.data.cameras) + list(bpy.data.lights):
        try:
            lib = getattr(idb, "library", None)
            if lib and lib.filepath and getattr(idb, "is_library_missing", False):
                missing_ids_by_library.add(lib.filepath)
        except Exception:
            continue

    library_items = []
    for filepath in sorted(all_libraries):
        if not filepath:
            continue
        lib_item = props.linked_libraries.add()
        lib_item.filepath = filepath
        lib_item.name = _get_library_name(filepath)
        lib_item.is_missing = _is_file_missing(filepath)
        lib_item.is_indirect = (filepath in missing_indirect_libs) or (filepath in missing_ids_by_library)
        library_items.append((lib_item, filepath))

    library_items.sort(key=lambda x: (not x[0].is_missing, _get_library_name(x[1]).lower()))
    props.linked_libraries.clear()
    for lib_item, filepath in library_items:
        new_item = props.linked_libraries.add()
        new_item.filepath = filepath
        new_item.name = _get_library_name(filepath)
        new_item.is_missing = lib_item.is_missing
        new_item.is_indirect = lib_item.is_indirect

    report({"INFO"}, f"Found {len(all_libraries)} unique linked library files")
    return {"FINISHED"}


def find_libraries_in_folders(context, report, addon_name=None):
    if addon_name is None:
        addon_name = __package__.rsplit(".", 1)[0] if "." in __package__ else __package__
    prefs = context.preferences.addons.get(addon_name)
    if not prefs or not prefs.preferences.search_paths:
        report({"ERROR"}, "No search paths configured. Add search paths in addon preferences.")
        return {"CANCELLED"}

    missing_libs = [lib for lib in context.scene.dynamic_link_manager.linked_libraries if lib.is_missing]
    if not missing_libs:
        report({"INFO"}, "No missing libraries to find")
        return {"FINISHED"}

    report({"INFO"}, f"Searching for {len(missing_libs)} missing libraries in search paths...")
    files_dir_list = []
    total_dirs_scanned = 0
    try:
        for search_path in prefs.preferences.search_paths:
            if not search_path.path:
                continue
            abs_path = bpy.path.abspath(search_path.path) if search_path.path.startswith("//") else search_path.path
            report({"INFO"}, f"Scanning search path: {abs_path}")
            if not os.path.exists(abs_path):
                report({"WARNING"}, f"Search path does not exist: {abs_path}")
                continue
            if not os.path.isdir(abs_path):
                report({"WARNING"}, f"Search path is not a directory: {abs_path}")
                continue
            for dirpath, dirnames, filenames in os.walk(abs_path):
                files_dir_list.append([dirpath, filenames])
                total_dirs_scanned += 1
                if total_dirs_scanned > 1000:
                    report({"WARNING"}, "Reached scan limit of 1000 directories.")
                    break
    except Exception as e:
        report({"ERROR"}, f"Error scanning search paths: {e}")
        return {"CANCELLED"}

    found_libraries = {}
    for lib_item in missing_libs:
        lib_filename = os.path.basename(lib_item.filepath)
        for dirpath, filenames in files_dir_list:
            if lib_filename in filenames:
                found_libraries[lib_filename] = os.path.join(dirpath, lib_filename)
                report({"INFO"}, f"Found {lib_filename} at: {os.path.join(dirpath, lib_filename)}")
                break

    if found_libraries:
        relinked_count = 0
        for lib in bpy.data.libraries:
            try:
                if not lib.filepath:
                    continue
                lib_filename = os.path.basename(lib.filepath)
                if lib_filename in found_libraries:
                    new_path = found_libraries[lib_filename]
                    current_abs = bpy.path.abspath(lib.filepath)
                    if not os.path.isfile(current_abs) or current_abs != new_path:
                        lib.filepath = new_path
                        try:
                            lib.reload()
                        except Exception:
                            pass
                        relinked_count += 1
                        report({"INFO"}, f"Relinked {lib_filename} -> {new_path}")
            except Exception:
                continue
        report({"INFO"}, f"Manually relinked {relinked_count} libraries")
    else:
        report({"WARNING"}, "No libraries found in search paths")
    try:
        bpy.ops.dlm.scan_linked_assets()
    except Exception:
        pass
    report({"INFO"}, "Operation complete.")
    return {"FINISHED"}


def attempt_relink(context, report, addon_name=None):
    if addon_name is None:
        addon_name = __package__.rsplit(".", 1)[0] if "." in __package__ else __package__
    prefs = context.preferences.addons.get(addon_name)
    if not prefs or not prefs.preferences.search_paths:
        report({"ERROR"}, "No search paths configured.")
        return {"CANCELLED"}
    missing_libs = [lib for lib in context.scene.dynamic_link_manager.linked_libraries if lib.is_missing]
    if not missing_libs:
        report({"INFO"}, "No missing libraries to relink")
        return {"FINISHED"}
    report({"INFO"}, f"Attempting to relink {len(missing_libs)} missing libraries...")
    files_dir_list = []
    try:
        for search_path in prefs.preferences.search_paths:
            if search_path.path:
                for dirpath, dirnames, filenames in os.walk(bpy.path.abspath(search_path.path)):
                    files_dir_list.append([dirpath, filenames])
    except FileNotFoundError:
        report({"ERROR"}, "Bad file path in search paths")
        return {"CANCELLED"}
    relinked_count = 0
    for lib_item in missing_libs:
        lib_filename = os.path.basename(lib_item.filepath)
        for dirpath, filenames in files_dir_list:
            if lib_filename in filenames:
                try:
                    bpy.ops.file.find_missing_files()
                    relinked_count += 1
                except Exception:
                    pass
                break
    report({"INFO"}, f"Relink attempt complete. Relinked: {relinked_count}")
    return {"FINISHED"}
