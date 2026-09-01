#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""External OS stub creator for DLM path modernization.

Stub modes:
  native    — local os.symlink / mklink (OK on local volumes only)
  linux_ssh — SSH + ln -s on the Linux SMB host (required for network shares;
              client-side reparse points are unreadable by Blender even with R2R)
  copy      — dumb binary copy of modern → archaic (explicit catch-all; never an
              auto fallback). Teardown only deletes if the file still matches the
              fingerprint recorded at create time.

Never uses mklink /H.

Exit codes: 0 all ok, 1 partial, 2 fatal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from typing import Any

# Allow importing sibling helper when run as a script.
_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from path_posix_map import (  # noqa: E402
    is_network_path,
    load_ssh_config,
    path_to_posix,
    shell_quote,
)


def norm(fp: str) -> str:
    return (fp or "").replace("/", "\\") if os.name == "nt" else (fp or "").replace("\\", "/")


def write_result(path: str, data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_manifest(path: str) -> list[dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get("stubs") or [])


def save_manifest(path: str, stubs: list[dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"stubs": stubs}, f, indent=2)


def is_reparse_or_link(path: str) -> bool:
    if not os.path.lexists(path):
        return False
    try:
        return os.path.islink(path)
    except OSError:
        return False


def _same_file(a: str, b: str) -> bool:
    """True if both paths exist and refer to the same file (SMB symlink follow counts)."""
    try:
        if not (os.path.isfile(a) and os.path.isfile(b)):
            return False
        return os.path.samefile(a, b)
    except OSError:
        return False


def _safe_unlink_client_stub(path: str, *, modern: str | None = None) -> tuple[bool, str]:
    """
    Remove a *client-visible* stub only.

    Never deletes modern. Never unlinks a path that Windows reports as a normal
    file (SMB often follows server symlinks — DeleteFile would destroy modern).
    Only removes paths where ``os.path.islink`` is true (client reparse).
    """
    if not path:
        return False, "empty path"
    if modern and _same_file(path, modern):
        return False, "refusing unlink: path resolves to modern (would destroy archive)"
    if not os.path.lexists(path):
        return True, "already gone"
    if not is_reparse_or_link(path):
        return False, (
            "refusing unlink: not a client symlink "
            "(SMB may follow server links — would destroy modern)"
        )
    if modern and norm(path).upper() == norm(modern).upper():
        return False, "refusing unlink: path equals modern"
    try:
        os.unlink(path)
    except OSError as e:
        return False, str(e)
    return True, "removed client symlink"


def create_native_symlink(archaic: str, modern: str) -> tuple[bool, str]:
    """Create archaic → modern with the host OS native symlink API."""
    if os.name == "nt":
        archaic = norm(archaic)
        modern = norm(modern)
    else:
        archaic = (archaic or "").replace("\\", "/")
        modern = (modern or "").replace("\\", "/")

    if not os.path.isfile(modern):
        return False, f"modern missing: {modern}"
    if is_reparse_or_link(modern):
        return False, f"modern is a symlink (refusing — archive must stay a real file): {modern}"
    if norm(archaic).upper() == norm(modern).upper():
        return False, "archaic and modern are the same path"
    if _same_file(archaic, modern):
        return True, "already linked (archaic resolves to modern)"

    # Network paths: never native — Windows unlink/copy through SMB symlinks
    # can delete the modern archive file. Use linux_ssh instead.
    if is_network_path(archaic) or is_network_path(modern):
        return False, "native symlink refused on network path (use linux_ssh)"

    parent = os.path.dirname(archaic)
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as e:
            return False, f"mkdir failed: {e}"

    if os.path.isfile(archaic) and not is_reparse_or_link(archaic):
        return False, f"refusing to clobber real file: {archaic}"
    if os.path.lexists(archaic):
        ok_u, msg_u = _safe_unlink_client_stub(archaic, modern=modern)
        if not ok_u:
            return False, f"could not remove existing stub: {msg_u}"

    try:
        os.symlink(modern, archaic)
    except OSError as e_sym:
        if os.name != "nt":
            return False, f"os.symlink: {e_sym}"
        try:
            r = subprocess.run(
                ["cmd", "/c", "mklink", archaic, modern],
                timeout=60,
                **_hidden_run_kwargs(),
            )
        except Exception as e:
            return False, f"os.symlink: {e_sym}; mklink: {e}"
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            return False, f"os.symlink: {e_sym}; mklink failed ({r.returncode}): {err}"
        msg = "mklink"
    else:
        msg = "os.symlink"

    if not os.path.isfile(modern) or is_reparse_or_link(modern):
        return False, f"modern destroyed or became symlink after create — abort: {modern}"
    return True, msg


def remove_native_symlink(archaic: str) -> tuple[bool, str]:
    if os.name == "nt":
        archaic = norm(archaic)
    else:
        archaic = (archaic or "").replace("\\", "/")
    if not os.path.lexists(archaic):
        pruned = prune_empty_parents(archaic)
        extra = f"; pruned {len(pruned)} empty dir(s)" if pruned else ""
        return True, "already gone" + extra
    ok_u, msg_u = _safe_unlink_client_stub(archaic)
    if not ok_u:
        return False, msg_u
    pruned = prune_empty_parents(archaic)
    extra = f"; pruned {len(pruned)} empty dir(s)" if pruned else ""
    return True, "removed" + extra


def _is_prune_stop_dir(path: str) -> bool:
    """True for drive roots, UNC share roots, and filesystem root — never prune these."""
    if not path:
        return True
    if os.name == "nt":
        p = norm(path).rstrip("\\")
        if len(p) == 2 and p[1] == ":":
            return True
        if p.startswith("\\\\"):
            parts = [x for x in p.split("\\") if x]
            # \\server\share  (and nothing deeper)
            if len(parts) <= 2:
                return True
        return False
    p = path.rstrip("/") or "/"
    return p == "/"


def prune_empty_parents(file_path: str) -> list[str]:
    """
    Remove empty directories upward from *file_path*'s parent.

    Stops at the first non-empty directory (siblings remain), or at a drive /
    UNC share / filesystem root. Never deletes files — ``os.rmdir`` only.
    """
    removed: list[str] = []
    if os.name == "nt":
        cur = norm(os.path.dirname(norm(file_path or "")))
    else:
        cur = os.path.dirname((file_path or "").replace("\\", "/"))

    while cur and not _is_prune_stop_dir(cur):
        if not os.path.isdir(cur):
            break
        try:
            # Fails (safely) when any sibling file/dir remains.
            os.rmdir(cur)
            removed.append(cur)
        except OSError:
            break
        parent = os.path.dirname(cur.rstrip("\\/") if os.name == "nt" else cur.rstrip("/"))
        if os.name == "nt":
            parent = norm(parent) if parent else ""
            if not parent or parent.upper() == cur.upper():
                break
        else:
            if not parent or parent == cur:
                break
        cur = parent
    return removed


def _file_fingerprint(path: str) -> dict[str, Any] | None:
    """Size + SHA-256 of first 1 MiB (and full file if smaller)."""
    if not os.path.isfile(path) or os.path.islink(path):
        return None
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024 * 1024)
            h.update(chunk)
            if size <= 1024 * 1024:
                # Full-file hash already in digest.
                pass
            else:
                # Mix in tail so truncations/replacements are caught cheaply.
                try:
                    f.seek(max(0, size - 65536))
                    h.update(f.read(65536))
                except OSError:
                    pass
    except OSError:
        return None
    return {"size": size, "sha256_head": h.hexdigest()}


def create_copy_stub(archaic: str, modern: str) -> tuple[bool, str, dict[str, Any] | None]:
    """
    Copy modern → archaic as a real file (no symlink).

    Returns (ok, message, fingerprint_or_None). Refuses to clobber non-stub files.
    Never modifies or deletes modern.
    """
    if os.name == "nt":
        archaic = norm(archaic)
        modern = norm(modern)
    else:
        archaic = (archaic or "").replace("\\", "/")
        modern = (modern or "").replace("\\", "/")

    if not os.path.isfile(modern):
        return False, f"modern missing: {modern}", None
    if is_reparse_or_link(modern):
        return False, f"modern is a symlink (refusing copy): {modern}", None
    if norm(archaic).upper() == norm(modern).upper():
        return False, "archaic and modern are the same path (refusing copy)", None
    if _same_file(archaic, modern):
        return (
            False,
            "archaic already resolves to modern via SMB symlink — "
            "refusing copy (would write through and risk archive)",
            None,
        )

    parent = os.path.dirname(archaic)
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as e:
            return False, f"mkdir failed: {e}", None

    if os.path.lexists(archaic):
        if is_reparse_or_link(archaic):
            ok_u, msg_u = _safe_unlink_client_stub(archaic, modern=modern)
            if not ok_u:
                return False, f"could not remove existing stub link: {msg_u}", None
        elif os.path.isdir(archaic):
            return False, f"refusing to clobber directory: {archaic}", None
        elif os.path.isfile(archaic):
            return False, f"refusing to clobber real file: {archaic}", None
        else:
            return False, f"refusing to clobber existing path: {archaic}", None

    modern_size = os.path.getsize(modern)
    try:
        shutil.copy2(modern, archaic)
    except OSError as e:
        return False, f"copy failed: {e}", None

    # Modern must be untouched.
    if not os.path.isfile(modern) or is_reparse_or_link(modern):
        return False, "modern missing or became symlink after copy — archive compromised", None
    if os.path.getsize(modern) != modern_size:
        return False, "modern size changed during copy — refusing to continue", None

    fp = _file_fingerprint(archaic)
    if not fp:
        return False, "copy wrote but could not fingerprint (left in place)", None
    return True, f"copy ({fp['size']} bytes)", fp


def remove_copy_stub(archaic: str, expected: dict[str, Any] | None) -> tuple[bool, str]:
    """
    Delete a copy stub only when fingerprint still matches what create recorded.

    Never deletes symlinks via this path; never deletes on fingerprint mismatch.
    """
    if os.name == "nt":
        archaic = norm(archaic)
    else:
        archaic = (archaic or "").replace("\\", "/")

    if not os.path.lexists(archaic):
        return True, "already gone"
    if is_reparse_or_link(archaic):
        return False, f"path is a symlink, not a copy stub (refusing delete): {archaic}"
    if os.path.isdir(archaic):
        return False, f"refusing to delete directory: {archaic}"
    if not expected or not expected.get("size") or not expected.get("sha256_head"):
        return False, "no copy fingerprint in manifest — refusing delete (safe)"
    fp = _file_fingerprint(archaic)
    if not fp:
        return False, f"could not fingerprint for verify: {archaic}"
    if int(fp["size"]) != int(expected["size"]) or fp["sha256_head"] != expected["sha256_head"]:
        return (
            False,
            "copy stub fingerprint mismatch — file changed or is not our copy; "
            "refusing delete",
        )
    try:
        os.unlink(archaic)
    except OSError as e:
        return False, str(e)
    pruned = prune_empty_parents(archaic)
    extra = f"; pruned {len(pruned)} empty dir(s)" if pruned else ""
    return True, "removed copy" + extra


def _hidden_run_kwargs() -> dict[str, Any]:
    """Avoid flashing console windows for ssh/cmd on Windows."""
    kw: dict[str, Any] = {"capture_output": True, "text": True}
    if os.name == "nt":
        # CREATE_NO_WINDOW — OpenSSH and cmd otherwise spawn visible consoles.
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return kw


def _ssh_run(host: str, remote_cmd: str, timeout: float = 120.0) -> tuple[int, str, str]:
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, remote_cmd],
        timeout=timeout,
        **_hidden_run_kwargs(),
    )
    return r.returncode, r.stdout or "", r.stderr or ""


def _windows_path_visible(path: str) -> bool:
    """True if Windows can open/stat *path* (SMB often lags behind exists())."""
    if os.path.lexists(path) or os.path.isfile(path):
        return True
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _windows_bust_smb_cache(path: str) -> None:
    """Listdir every ancestor so newly SSH-created UNC trees show up."""
    cur = os.path.dirname(norm(path))
    # UNC: \\host\share\...\file — stop at \\host\share
    depth = 0
    while cur and depth < 12:
        try:
            os.listdir(cur)
        except OSError:
            pass
        parent = os.path.dirname(cur.rstrip("\\"))
        if not parent or parent == cur:
            break
        # Don't climb past \\server\share
        if cur.startswith("\\\\") and cur.count("\\") <= 3:
            break
        cur = parent
        depth += 1


def _windows_refresh_and_see(
    path: str, *, retries: int | None = None, delay: float = 0.5
) -> bool:
    """True if Windows can see *path* (bust SMB cache; longer wait for UNC)."""
    if os.name != "nt":
        return os.path.lexists(path) or os.path.isfile(path)
    path = norm(path)
    is_unc = path.startswith("\\\\")
    if retries is None:
        retries = 40 if is_unc else 20  # ~20s for UNC; SSH mkdir can lag SMB
    for _ in range(max(1, retries)):
        _windows_bust_smb_cache(path)
        if _windows_path_visible(path):
            return True
        time.sleep(delay)
    return False


def _windows_archaic_parent_usable(archaic: str) -> tuple[bool, str]:
    """
    Ensure the archaic parent is usable from Windows before SSH create.

    SSH can mkdir on the host under a POSIX map that the SMB share does not
    expose (e.g. \\NEXUS\\assets is an empty share). Blender only loads what
    Windows can see — fail early with a clear reason.
    """
    if os.name != "nt":
        return True, ""
    archaic = norm(archaic)
    parent = os.path.dirname(archaic)
    if not parent:
        return False, "archaic path has no parent directory"
    if os.path.isdir(parent):
        try:
            os.listdir(parent)
            return True, ""
        except OSError as e:
            return False, f"Windows cannot list archaic parent: {e}"

    # Try creating the parent tree via SMB (same view Blender uses).
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as e:
        return False, (
            f"Windows cannot create archaic parent ({e}). "
            "Share missing/ACL, or empty share (e.g. \\\\NEXUS\\assets)"
        )

    if not os.path.isdir(parent):
        return False, (
            f"Windows cannot see archaic parent after mkdir (broken/empty SMB share?): {parent}"
        )
    try:
        names = os.listdir(parent)
    except OSError as e:
        return False, f"Windows cannot list archaic parent after mkdir: {e}"
    # Some ghost shares accept mkdir then still list as empty and omit new dirs.
    base = os.path.basename(parent)
    if base and base not in names and names == []:
        # Parent itself exists via isdir but listing parent-of-parent may omit it.
        pass
    # Confirm the created path still resolves.
    if not os.path.isdir(parent):
        return False, f"archaic parent vanished after mkdir (ghost share?): {parent}"
    return True, ""


def _prep_ssh_create_pair(
    archaic_win: str, modern_win: str, ssh: dict[str, Any]
) -> tuple[dict[str, str] | None, str]:
    """Validate + map one pair; clear client reparse. Returns (job, error)."""
    if norm(archaic_win).upper() == norm(modern_win).upper():
        return None, "archaic and modern are the same path (refusing stub)"
    unc_map = ssh.get("unc_to_posix") or {}
    archaic_posix = path_to_posix(archaic_win, unc_map)
    modern_posix = path_to_posix(modern_win, unc_map)
    if not archaic_posix:
        return None, f"cannot map archaic to POSIX: {archaic_win}"
    if not modern_posix:
        return None, f"cannot map modern to POSIX: {modern_win}"
    if archaic_posix.rstrip("/") == modern_posix.rstrip("/"):
        return None, "archaic and modern POSIX paths are identical (refusing stub)"

    if os.name == "nt":
        aw = norm(archaic_win)
        mw = norm(modern_win)
        ok_p, err_p = _windows_archaic_parent_usable(aw)
        if not ok_p:
            return None, err_p
        # Never Windows-unlink on network paths — SMB may follow server symlinks
        # and DeleteFile would destroy the AssetArchive modern file.
        if is_network_path(aw) or is_network_path(mw):
            if _same_file(aw, mw):
                return None, "already linked (Windows sees modern through archaic)"
            # Leave any client reparse for SSH side ([ -L ] rm only).
        else:
            if os.path.lexists(aw) and not is_reparse_or_link(aw):
                if _same_file(aw, mw):
                    return None, "already linked (Windows sees modern through archaic)"
                return None, f"refusing to clobber real file on client: {aw}"
            if is_reparse_or_link(aw):
                ok_u, msg_u = _safe_unlink_client_stub(aw, modern=mw)
                if not ok_u:
                    return None, f"could not remove client reparse: {msg_u}"

    return {
        "archaic_win": archaic_win,
        "modern_win": modern_win,
        "archaic_posix": archaic_posix,
        "modern_posix": modern_posix,
    }, ""


def create_linux_ssh_symlinks_batch(
    pairs: list[tuple[str, str]],
    ssh: dict[str, Any],
) -> list[tuple[bool, str]]:
    """
    One SSH session for all creates. *pairs* is [(archaic_win, modern_win), ...].
    Returns parallel list of (ok, message).
    """
    host = (ssh.get("host") or "").strip()
    results: list[tuple[bool, str]] = [ (False, "no SSH host") ] * len(pairs)
    if not host:
        return results

    jobs: list[dict[str, str] | None] = []
    for archaic, modern in pairs:
        job, err = _prep_ssh_create_pair(archaic, modern, ssh)
        jobs.append(job)
        if job is None:
            idx = len(jobs) - 1
            if err.startswith("already linked"):
                results[idx] = (True, err)
            else:
                results[idx] = (False, err)

    indexed = [(i, j) for i, j in enumerate(jobs) if j is not None]
    if not indexed:
        return results

    # Remote script: emit DLM_OK <i> or DLM_FAIL <i> <reason> per item (single ssh).
    # Do NOT rmdir parents — pruning empty share dirs made \\NEXUS\assets\... trees
    # vanish from Windows and looked like "access denied" / empty folders.
    remote_parts = ["status=0"]
    for i, job in indexed:
        aq = shell_quote(job["archaic_posix"])
        mq = shell_quote(job["modern_posix"])
        parent_q = shell_quote(os.path.dirname(job["archaic_posix"]).replace("\\", "/"))
        remote_parts.append(
            f"_dlm_one() {{ "
            f"aq={aq}; mq={mq}; parent={parent_q}; i={i}; "
            # Modern (AssetArchive) must stay a real file forever — never rm/mv it.
            f'test -e "$mq" || {{ echo "DLM_FAIL $i modern missing on host"; return 1; }}; '
            f'if [ -L "$mq" ]; then echo "DLM_FAIL $i modern is a symlink — refusing"; return 1; fi; '
            f'test -f "$mq" || {{ echo "DLM_FAIL $i modern is not a regular file"; return 1; }}; '
            f'mkdir -p "$parent" || {{ echo "DLM_FAIL $i mkdir failed"; return 1; }}; '
            f'if [ -L "$aq" ]; then rm -f "$aq"; '
            f'elif [ -e "$aq" ]; then echo "DLM_FAIL $i refusing to clobber real file"; return 1; fi; '
            f'ln -s "$mq" "$aq" || {{ echo "DLM_FAIL $i ln -s failed"; return 1; }}; '
            # Re-check modern survived (guards against rm following a bad path).
            f'if [ -L "$mq" ] || [ ! -f "$mq" ]; then '
            f'echo "DLM_FAIL $i modern damaged after ln — archive must stay put"; return 1; fi; '
            f'echo "DLM_OK $i"; }}; _dlm_one || status=1'
        )
    remote_parts.append("exit 0")
    remote = "; ".join(remote_parts)

    try:
        _code, out, err = _ssh_run(host, remote, timeout=300)
    except Exception as e:
        for i, job in indexed:
            results[i] = (False, f"ssh: {e}")
        return results

    seen = set()
    for line in (out or "").splitlines():
        line = line.strip()
        if line.startswith("DLM_OK "):
            try:
                i = int(line.split()[1])
            except (IndexError, ValueError):
                continue
            if 0 <= i < len(pairs) and jobs[i]:
                j = jobs[i]
                results[i] = (True, f"linux_ssh {j['archaic_posix']} -> {j['modern_posix']}")
                seen.add(i)
        elif line.startswith("DLM_FAIL "):
            parts = line.split(None, 2)
            try:
                i = int(parts[1])
            except (IndexError, ValueError):
                continue
            msg = parts[2] if len(parts) > 2 else "failed"
            if 0 <= i < len(pairs):
                results[i] = (False, msg)
                seen.add(i)

    for i, job in indexed:
        if i not in seen:
            results[i] = (False, f"no result from ssh ({(err or out).strip()[:200]})")

    # SSH success is not enough: Blender on Windows must see the archaic path,
    # and modern (AssetArchive) must still be a real file — never moved/deleted.
    if os.name == "nt":
        for i, job in indexed:
            if not results[i][0] or not job:
                continue
            mw = norm(job["modern_win"])
            if is_reparse_or_link(mw) or not os.path.isfile(mw):
                results[i] = (
                    False,
                    f"modern archive missing or became symlink after create "
                    f"(stub must never move modern): {mw}",
                )
                continue
            aw = norm(job["archaic_win"])
            if _windows_refresh_and_see(aw):
                continue
            results[i] = (
                False,
                "ssh symlink created but Windows cannot see it "
                f"(empty/broken SMB share or wrong map): {aw}",
            )
    return results


def remove_linux_ssh_symlinks_batch(
    archaic_wins: list[str],
    ssh: dict[str, Any],
) -> list[tuple[bool, str]]:
    """One SSH session to remove many stubs. Returns parallel (ok, message) list."""
    host = (ssh.get("host") or "").strip()
    unc_map = ssh.get("unc_to_posix") or {}
    results: list[tuple[bool, str]] = [(False, "no SSH host")] * len(archaic_wins)
    if not host:
        return results

    jobs: list[tuple[int, str, str]] = []  # i, win, posix
    for i, archaic_win in enumerate(archaic_wins):
        posix = path_to_posix(archaic_win, unc_map)
        if not posix:
            ok, msg = remove_native_symlink(archaic_win)
            results[i] = (ok, msg)
            continue
        jobs.append((i, archaic_win, posix))

    if jobs:
        # Remove the symlink only — never rmdir parents on SMB (teardown prune
        # deleted \\NEXUS\assets\BlenderAssets\... trees and broke Explorer views).
        remote_parts = ["status=0"]
        for i, _win, posix in jobs:
            aq = shell_quote(posix)
            remote_parts.append(
                f"_dlm_rm() {{ "
                f"aq={aq}; i={i}; "
                f'if [ ! -e "$aq" ] && [ ! -L "$aq" ]; then '
                f'echo "DLM_OK $i GONE"; return 0; fi; '
                f'if [ -L "$aq" ]; then '
                f'rm -f "$aq" || {{ echo "DLM_FAIL $i rm failed"; return 1; }}; '
                f'echo "DLM_OK $i"; return 0; fi; '
                f'echo "DLM_FAIL $i not a symlink — refusing delete"; return 1; '
                f"}}; _dlm_rm || status=1"
            )
        remote_parts.append("exit 0")
        try:
            _code, out, err = _ssh_run(host, "; ".join(remote_parts), timeout=180)
        except Exception as e:
            for i, _w, _p in jobs:
                results[i] = (False, f"ssh: {e}")
            return results

        seen = set()
        for line in (out or "").splitlines():
            line = line.strip()
            if line.startswith("DLM_OK "):
                parts = line.split()
                try:
                    i = int(parts[1])
                except (IndexError, ValueError):
                    continue
                msg = "already gone" if "GONE" in parts else "removed"
                results[i] = (True, msg)
                seen.add(i)
                # Client-side reparse leftover only — never unlink SMB-followed files.
                if os.name == "nt":
                    _safe_unlink_client_stub(norm(archaic_wins[i]))
            elif line.startswith("DLM_FAIL "):
                parts = line.split(None, 2)
                try:
                    i = int(parts[1])
                except (IndexError, ValueError):
                    continue
                results[i] = (False, parts[2] if len(parts) > 2 else "failed")
                seen.add(i)
        for i, _w, _p in jobs:
            if i not in seen:
                results[i] = (False, f"no result from ssh ({(err or '').strip()[:200]})")
    return results


def create_linux_ssh_symlink(
    archaic_win: str,
    modern_win: str,
    ssh: dict[str, Any],
) -> tuple[bool, str]:
    """Create one archaic→modern stub (wrapper around the batch helper)."""
    return create_linux_ssh_symlinks_batch([(archaic_win, modern_win)], ssh)[0]


def remove_linux_ssh_symlink(archaic_win: str, ssh: dict[str, Any]) -> tuple[bool, str]:
    return remove_linux_ssh_symlinks_batch([archaic_win], ssh)[0]


def resolve_stub_mode(pair: dict[str, Any], default_mode: str) -> str:
    mode = (pair.get("stub_mode") or default_mode or "copy").lower()
    if mode == "auto":
        archaic = pair.get("archaic_path") or ""
        # Never auto-pick copy — that is an explicit catch-all only.
        return "linux_ssh" if is_network_path(archaic) else "native"
    if mode in ("native", "linux_ssh", "copy"):
        return mode
    return "native"


def merge_ssh(payload_ssh: dict[str, Any] | None) -> dict[str, Any]:
    cfg = load_ssh_config()
    ssh = {
        "host": cfg.get("host") or "",
        "unc_to_posix": dict(cfg.get("unc_to_posix") or {}),
    }
    if payload_ssh:
        if payload_ssh.get("host"):
            ssh["host"] = payload_ssh["host"]
        if payload_ssh.get("unc_to_posix"):
            ssh["unc_to_posix"].update(payload_ssh["unc_to_posix"])
    return ssh


def run_create(
    pairs: list[dict[str, Any]],
    manifest_file: str,
    ssh: dict[str, Any],
    default_mode: str = "copy",
) -> dict[str, Any]:
    created = []
    failed = []
    stubs = load_manifest(manifest_file)
    by_archaic = {norm(s["archaic_path"]).upper(): s for s in stubs}

    ssh_jobs: list[tuple[int, str, str]] = []  # index into work list
    work: list[dict[str, Any]] = []

    for p in pairs:
        archaic = p.get("archaic_path") or ""
        modern = p.get("modern_path") or ""
        mode = resolve_stub_mode(p, default_mode)
        entry = {
            "archaic_path": archaic,
            "modern_path": modern,
            "stub_mode": mode,
            "message": "",
        }
        idx = len(work)
        work.append(entry)
        if mode == "linux_ssh":
            ssh_jobs.append((idx, archaic, modern))
        elif mode == "copy":
            ok, msg, fp = create_copy_stub(archaic, modern)
            entry["message"] = msg
            if ok:
                created.append(entry)
                man = {
                    "archaic_path": archaic,
                    "modern_path": modern,
                    "stub_mode": "copy",
                }
                if fp:
                    man["copy_fingerprint"] = fp
                by_archaic[norm(archaic).upper()] = man
            else:
                failed.append(entry)
        else:
            ok, msg = create_native_symlink(archaic, modern)
            entry["message"] = msg
            if ok:
                created.append(entry)
                by_archaic[norm(archaic).upper()] = {
                    "archaic_path": archaic,
                    "modern_path": modern,
                    "stub_mode": mode,
                }
            else:
                failed.append(entry)

    if ssh_jobs:
        batch = create_linux_ssh_symlinks_batch([(a, m) for _i, a, m in ssh_jobs], ssh)
        for (idx, _a, _m), (ok, msg) in zip(ssh_jobs, batch):
            entry = work[idx]
            entry["message"] = msg
            if ok:
                created.append(entry)
                by_archaic[norm(entry["archaic_path"]).upper()] = {
                    "archaic_path": entry["archaic_path"],
                    "modern_path": entry["modern_path"],
                    "stub_mode": entry["stub_mode"],
                }
            else:
                failed.append(entry)

    save_manifest(manifest_file, list(by_archaic.values()))
    return {"created": created, "failed": failed}


def run_teardown(
    pairs: list[dict[str, Any]],
    manifest_file: str,
    ssh: dict[str, Any],
) -> dict[str, Any]:
    stubs = load_manifest(manifest_file)
    targets = pairs if pairs else stubs

    removed = []
    failed = []
    remaining = {norm(s["archaic_path"]).upper(): s for s in stubs}

    ssh_idxs: list[int] = []
    work: list[dict[str, Any]] = []

    for p in targets:
        archaic = p.get("archaic_path") or ""
        key = norm(archaic).upper()
        man = remaining.get(key) or {}
        mode = (
            p.get("stub_mode")
            or man.get("stub_mode")
            or "copy"
        )
        if mode == "auto":
            mode = "linux_ssh" if is_network_path(archaic) else "native"
        entry = {"archaic_path": archaic, "stub_mode": mode, "message": ""}
        idx = len(work)
        work.append(entry)
        if mode == "linux_ssh":
            ssh_idxs.append(idx)
        elif mode == "copy":
            ok, msg = remove_copy_stub(archaic, man.get("copy_fingerprint"))
            entry["message"] = msg
            if ok:
                removed.append(entry)
                remaining.pop(key, None)
            else:
                failed.append(entry)
        else:
            ok, msg = remove_native_symlink(archaic)
            entry["message"] = msg
            if ok:
                removed.append(entry)
                remaining.pop(key, None)
            else:
                failed.append(entry)

    if ssh_idxs:
        batch = remove_linux_ssh_symlinks_batch(
            [work[i]["archaic_path"] for i in ssh_idxs], ssh
        )
        for idx, (ok, msg) in zip(ssh_idxs, batch):
            entry = work[idx]
            entry["message"] = msg
            if ok:
                removed.append(entry)
                remaining.pop(norm(entry["archaic_path"]).upper(), None)
            else:
                failed.append(entry)

    save_manifest(manifest_file, list(remaining.values()))
    return {"removed": removed, "failed": failed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DLM path stub symlinker")
    parser.add_argument("--payload", required=True, help="JSON payload path")
    parser.add_argument("--result", required=True, help="JSON result path")
    parser.add_argument("--manifest", required=True, help="Stub manifest path")
    args = parser.parse_args(argv)

    try:
        with open(args.payload, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        write_result(args.result, {"ok": False, "error": f"bad payload: {e}", "exit_code": 2})
        return 2

    action = (payload.get("action") or "create").lower()
    pairs = list(payload.get("pairs") or [])
    ssh = merge_ssh(payload.get("ssh"))
    default_mode = (payload.get("stub_mode") or "copy").lower()

    if action == "teardown":
        out = run_teardown(pairs, args.manifest, ssh)
        failed = out.get("failed") or []
        ok = len(failed) == 0
        write_result(
            args.result,
            {"ok": ok, "exit_code": 0 if ok else 1, "action": action, **out, "created": []},
        )
        return 0 if ok else 1

    if action == "create":
        if not pairs:
            write_result(
                args.result,
                {
                    "ok": False,
                    "exit_code": 1,
                    "action": action,
                    "created": [],
                    "failed": [],
                    "error": "no pairs needing stubs",
                },
            )
            return 1
        out = run_create(pairs, args.manifest, ssh, default_mode=default_mode)
        failed = out.get("failed") or []
        created = out.get("created") or []
        ok = len(failed) == 0 and len(created) > 0
        partial = len(created) > 0 and len(failed) > 0
        write_result(
            args.result,
            {
                "ok": ok or partial,
                "exit_code": 0 if ok else (1 if partial or failed else 2),
                "action": action,
                **out,
                "removed": [],
            },
        )
        return 0 if ok else 1

    write_result(args.result, {"ok": False, "error": f"unknown action: {action}", "exit_code": 2})
    return 2


if __name__ == "__main__":
    sys.exit(main())
