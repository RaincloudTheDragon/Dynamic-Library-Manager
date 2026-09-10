#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read nested Library link paths from a .blend without launching Blender.

Primary: blender_asset_tracer (optional). Fallback: scan LI blocks for .blend paths.
"""

from __future__ import annotations

import os
import re
from typing import Iterable


def _decode_lib_name(raw: bytes | str) -> str:
    if isinstance(raw, bytes):
        raw = raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
    return (raw or "").strip()


def library_link_paths_bat(blend_path: str) -> list[str] | None:
    """Return stored Library.name paths via blender_asset_tracer, or None if unavailable."""
    try:
        from pathlib import Path

        from blender_asset_tracer.blendfile import BlendFile
    except ImportError:
        return None
    try:
        bf = BlendFile(Path(blend_path))
    except Exception:
        return None
    out: list[str] = []
    try:
        for block in bf.find_blocks_from_code(b"LI"):
            try:
                name = _decode_lib_name(block.get(b"name"))
            except Exception:
                continue
            if name and name.lower().endswith(".blend"):
                out.append(name)
    finally:
        try:
            bf.close()
        except Exception:
            pass
    return out


_BLEND_PATH_RE = re.compile(
    rb"(//[^\x00]*?\.blend|[A-Za-z]:[/\\][^\x00]*?\.blend|[/\\][^\x00]*?\.blend)",
    re.IGNORECASE,
)


def library_link_paths_scan(blend_path: str) -> list[str]:
    """Best-effort scan for Library-like .blend path strings inside a blend file."""
    try:
        with open(blend_path, "rb") as handle:
            head = handle.read(16)
            handle.seek(0)
            data = handle.read()
    except OSError:
        return []
    # gzip blend
    if head[:2] == b"\x1f\x8b":
        import gzip

        try:
            data = gzip.decompress(data)
        except Exception:
            return []
    found: list[str] = []
    seen: set[str] = set()
    for match in _BLEND_PATH_RE.finditer(data):
        # Prefer hits inside LI blocks (code 'LI' shortly before the string).
        start = match.start()
        window = data[max(0, start - 64) : start]
        if b"LI" not in window and b"Library" not in window:
            # Still accept // relative paths — common for nested libs.
            raw = match.group(1)
            if not raw.startswith(b"//"):
                continue
        text = _decode_lib_name(match.group(1))
        if not text or text.lower() in seen:
            continue
        # Skip the blend's own filename-only noise.
        if os.path.basename(text).lower() == os.path.basename(blend_path).lower() and not text.startswith(
            "//"
        ):
            continue
        seen.add(text.lower())
        found.append(text)
    return found


def library_link_paths(blend_path: str) -> list[str]:
    """Stored nested library filepath strings from *blend_path*."""
    if not blend_path or not os.path.isfile(blend_path):
        return []
    paths = library_link_paths_bat(blend_path)
    if paths is None:
        paths = library_link_paths_scan(blend_path)
    return list(paths)


def resolve_blend_stored_path(stored: str, base_file: str) -> str:
    """Resolve a Library stored path relative to the parent blend's directory."""
    stored = (stored or "").strip()
    if not stored:
        return ""
    base_dir = os.path.dirname(os.path.abspath(base_file))
    if stored.startswith("//"):
        rel = stored[2:].replace("\\", "/")
        return os.path.normpath(os.path.join(base_dir, rel))
    if os.path.isabs(stored):
        return os.path.normpath(stored)
    return os.path.normpath(os.path.join(base_dir, stored.replace("\\", "/")))


def find_basename_in_roots(
    basename: str,
    roots: Iterable[str],
    *,
    prefer: Iterable[str] | None = None,
) -> str:
    """Return first existing file named *basename* under *roots* (skip .folders)."""
    want = (basename or "").lower()
    if not want:
        return ""
    for path in prefer or ():
        if path and os.path.isfile(path) and os.path.basename(path).lower() == want:
            return os.path.normpath(path)
    for root in roots:
        root = (root or "").strip()
        if not root or not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if name.lower() == want:
                    return os.path.normpath(os.path.join(dirpath, name))
    return ""
