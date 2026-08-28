#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""External OS stub creator for DLM path modernization.

Stub modes:
  native    — local os.symlink / mklink (OK on local volumes only)
  linux_ssh — SSH + ln -s on the Linux SMB host (required for network shares;
              client-side reparse points are unreadable by Blender even with R2R)

Never uses mklink /H.

Exit codes: 0 all ok, 1 partial, 2 fatal.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
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

    parent = os.path.dirname(archaic)
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as e:
            return False, f"mkdir failed: {e}"

    if os.path.isfile(archaic) and not is_reparse_or_link(archaic):
        return False, f"refusing to clobber real file: {archaic}"
    if is_reparse_or_link(archaic) or os.path.lexists(archaic):
        try:
            if os.path.isdir(archaic) and not os.path.islink(archaic):
                return False, f"refusing to remove directory: {archaic}"
            os.unlink(archaic)
        except OSError as e:
            return False, f"could not remove existing stub: {e}"

    try:
        os.symlink(modern, archaic)
        return True, "os.symlink"
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
        return True, "mklink"


def remove_native_symlink(archaic: str) -> tuple[bool, str]:
    if os.name == "nt":
        archaic = norm(archaic)
    else:
        archaic = (archaic or "").replace("\\", "/")
    if not os.path.lexists(archaic):
        return True, "already gone"
    if not is_reparse_or_link(archaic):
        return False, f"not a stub (refusing delete): {archaic}"
    try:
        os.unlink(archaic)
        return True, "removed"
    except OSError as e:
        return False, str(e)


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
        if os.path.lexists(aw) and not is_reparse_or_link(aw):
            return None, f"refusing to clobber real file on client: {aw}"
        if is_reparse_or_link(aw):
            try:
                os.unlink(aw)
            except OSError as e:
                return None, f"could not remove client reparse: {e}"

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
            results[len(jobs) - 1] = (False, err)

    indexed = [(i, j) for i, j in enumerate(jobs) if j is not None]
    if not indexed:
        return results

    # Remote script: emit DLM_OK <i> or DLM_FAIL <i> <reason> per item (single ssh).
    remote_parts = ["status=0"]
    for i, job in indexed:
        aq = shell_quote(job["archaic_posix"])
        mq = shell_quote(job["modern_posix"])
        parent_q = shell_quote(os.path.dirname(job["archaic_posix"]).replace("\\", "/"))
        remote_parts.append(
            f"_dlm_one() {{ "
            f"aq={aq}; mq={mq}; parent={parent_q}; i={i}; "
            f'test -f "$mq" || {{ echo "DLM_FAIL $i modern missing on host"; return 1; }}; '
            f'mkdir -p "$parent" || {{ echo "DLM_FAIL $i mkdir failed"; return 1; }}; '
            f'if [ -L "$aq" ]; then rm -f "$aq"; '
            f'elif [ -e "$aq" ]; then echo "DLM_FAIL $i refusing to clobber real file"; return 1; fi; '
            f'ln -s "$mq" "$aq" || {{ echo "DLM_FAIL $i ln -s failed"; return 1; }}; '
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
        remote_parts = ["status=0"]
        for i, _win, posix in jobs:
            aq = shell_quote(posix)
            remote_parts.append(
                f"_dlm_rm() {{ "
                f"aq={aq}; i={i}; "
                f'if [ ! -e "$aq" ] && [ ! -L "$aq" ]; then echo "DLM_OK $i GONE"; return 0; fi; '
                f'if [ -L "$aq" ]; then rm -f "$aq" && echo "DLM_OK $i" && return 0; fi; '
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
                try:
                    i = int(line.split()[1])
                except (IndexError, ValueError):
                    continue
                results[i] = (True, "removed")
                seen.add(i)
                if os.name == "nt" and is_reparse_or_link(norm(archaic_wins[i])):
                    try:
                        os.unlink(norm(archaic_wins[i]))
                    except OSError:
                        pass
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
    mode = (pair.get("stub_mode") or default_mode or "auto").lower()
    if mode == "auto":
        archaic = pair.get("archaic_path") or ""
        return "linux_ssh" if is_network_path(archaic) else "native"
    return mode


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
    default_mode: str = "auto",
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
        mode = (
            p.get("stub_mode")
            or remaining.get(norm(archaic).upper(), {}).get("stub_mode")
            or "auto"
        )
        if mode == "auto":
            mode = "linux_ssh" if is_network_path(archaic) else "native"
        entry = {"archaic_path": archaic, "stub_mode": mode, "message": ""}
        idx = len(work)
        work.append(entry)
        if mode == "linux_ssh":
            ssh_idxs.append(idx)
        else:
            ok, msg = remove_native_symlink(archaic)
            entry["message"] = msg
            if ok:
                removed.append(entry)
                remaining.pop(norm(archaic).upper(), None)
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
    default_mode = (payload.get("stub_mode") or "auto").lower()

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
