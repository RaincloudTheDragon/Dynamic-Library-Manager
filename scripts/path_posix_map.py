#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows path ↔ POSIX mapping for SSH stub creation on Linux SMB hosts.

Maps are persisted under %LOCALAPPDATA%/DynamicLinkManager (not Blender prefs)
so vscode-development addon reloads do not wipe them.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from typing import Any


def norm_win(fp: str) -> str:
    return (fp or "").replace("/", "\\")


def config_dir(create: bool = True) -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "DynamicLinkManager")
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def ssh_config_path() -> str:
    return os.path.join(config_dir(), "ssh_map.json")


def load_ssh_config() -> dict[str, Any]:
    path = ssh_config_path()
    if not os.path.isfile(path):
        return {"host": "", "unc_to_posix": {}, "updated_at": 0}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"host": "", "unc_to_posix": {}, "updated_at": 0}
        data.setdefault("host", "")
        data.setdefault("unc_to_posix", {})
        return data
    except Exception:
        return {"host": "", "unc_to_posix": {}, "updated_at": 0}


def save_ssh_config(data: dict[str, Any]) -> str:
    path = ssh_config_path()
    out = dict(data)
    out["updated_at"] = time.time()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    return path


def _hidden_run_kwargs() -> dict:
    kw = {"capture_output": True, "text": True}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return kw


def drive_letter_to_unc(win_path: str) -> str | None:
    """Expand ``A:\\foo`` to ``\\\\SERVER\\share\\foo`` via ``net use``."""
    p = norm_win(win_path)
    if len(p) < 2 or p[1] != ":":
        return None
    letter = p[0].upper()
    try:
        r = subprocess.run(
            ["cmd", "/c", "net", "use", f"{letter}:"],
            timeout=30,
            **_hidden_run_kwargs(),
        )
    except Exception:
        return None
    remote = None
    for line in (r.stdout or "").splitlines():
        if "remote name" in line.lower():
            parts = line.split(None, 2)
            if len(parts) >= 3:
                remote = parts[-1].strip()
            break
    if not remote or not remote.startswith("\\\\"):
        return None
    rest = p[2:].lstrip("\\")
    return remote.rstrip("\\") + (("\\" + rest) if rest else "")


def unc_share_root(unc_path: str) -> tuple[str, str] | None:
    """Return (\\\\server\\share, relative\\under\\share) or None."""
    p = norm_win(unc_path)
    if not p.startswith("\\\\"):
        return None
    parts = [x for x in p.split("\\") if x]
    if len(parts) < 2:
        return None
    root = "\\\\" + parts[0] + "\\" + parts[1]
    rel = "\\".join(parts[2:])
    return root, rel


def is_network_path(win_path: str) -> bool:
    p = norm_win(win_path)
    if p.startswith("\\\\"):
        return True
    if len(p) >= 2 and p[1] == ":" and drive_letter_to_unc(p):
        return True
    return False


def path_to_posix(win_path: str, unc_to_posix: dict[str, str]) -> str | None:
    """Map Windows UNC/drive path to POSIX using longest UNC prefix match."""
    p = norm_win(win_path)
    candidates = [p]
    as_unc = drive_letter_to_unc(p)
    if as_unc:
        candidates.append(norm_win(as_unc))

    roots: list[tuple[str, str]] = []
    for k, v in (unc_to_posix or {}).items():
        if k and v:
            roots.append((norm_win(k).rstrip("\\"), v.rstrip("/")))
    roots.sort(key=lambda kv: len(kv[0]), reverse=True)

    best: tuple[int, str] | None = None
    for cand in candidates:
        cu = cand.upper()
        for root, posix in roots:
            ru = root.upper()
            if cu == ru or cu.startswith(ru + "\\"):
                rest = cand[len(root) :].lstrip("\\").replace("\\", "/")
                mapped = posix + (("/" + rest) if rest else "")
                score = len(root)
                if best is None or score > best[0]:
                    best = (score, mapped)
    return best[1] if best else None


def _ssh_run(host: str, remote_cmd: str, timeout: float = 120.0) -> tuple[int, str, str]:
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, remote_cmd],
        timeout=timeout,
        **_hidden_run_kwargs(),
    )
    return r.returncode, r.stdout or "", r.stderr or ""


def resolve_ssh_host(unc_server: str, preferred: str = "") -> str | None:
    """Pick a working SSH host alias (preferred, then server, then lowercase)."""
    candidates = []
    for h in (preferred, unc_server, unc_server.lower() if unc_server else ""):
        h = (h or "").strip()
        if h and h not in candidates:
            candidates.append(h)
    for host in candidates:
        code, out, _err = _ssh_run(host, "echo DLM_SSH_OK", timeout=20)
        if code == 0 and "DLM_SSH_OK" in out:
            return host
    return None


def discover_posix_root(host: str, unc_share: str, rel_under_share: str) -> str | None:
    """
    Find POSIX directory that corresponds to *unc_share*.

    Prefers locating *rel_under_share* when that file exists on the server.
    For missing archaic libs (the usual Symlink Propagation case), falls back to
    matching the share mount and any existing parent directory of *rel*.
    """
    rel_posix = rel_under_share.replace("\\", "/").lstrip("/")
    share_leaf = unc_share.rstrip("\\").split("\\")[-1].replace("'", "'\\''")
    server = (
        unc_share.strip("\\").split("\\")[0].replace("'", "'\\''")
        if unc_share.startswith("\\\\")
        else ""
    )
    rel_q = rel_posix.replace("'", "'\\''") if rel_posix else ""

    # Ordered candidate roots — no recursive find first.
    # Dedicated share mounts (/mnt/PHOENIX/$share) must beat nested lookalikes
    # like /mnt/PHOENIX/amazon/assets when the share is an empty stub volume.
    remote = f"""
rel='{rel_q}'
share='{share_leaf}'
server='{server}'
# Prefer the real SMB export path first (empty stub shares included).
preferred_roots="
/mnt/PHOENIX/$share
/mnt/$share
"
try_roots="
/mnt/PHOENIX/$share
/mnt/$share
/mnt/$share/$share
/mnt/$server/$share
/mnt/$(echo "$server" | tr '[:upper:]' '[:lower:]')/$share
/mnt/PHOENIX/$share/$share
/mnt/PHOENIX/amazon/$share
/mnt/PHOENIX/amazon/amazon
/export/$share
/srv/$share
/data/$share
"
# 0) Dedicated empty/stub share mount: use it even when rel does not exist yet.
for root in $preferred_roots; do
  [ -n "$root" ] || continue
  if [ -d "$root" ]; then echo "$root"; exit 0; fi
done
# 1) Exact file under a candidate root (modern / still-present archaic).
if [ -n "$rel" ]; then
  for root in $try_roots; do
    [ -n "$root" ] || continue
    if [ -f "$root/$rel" ]; then echo "$root"; exit 0; fi
  done
fi
# 2) Missing archaic file: accept root if any parent of rel exists under it.
if [ -n "$rel" ]; then
  for root in $try_roots; do
    [ -n "$root" ] || continue
    [ -d "$root" ] || continue
    d="$rel"
    while [ -n "$d" ]; do
      d=$(dirname "$d")
      [ "$d" = "." ] && break
      if [ -d "$root/$d" ]; then echo "$root"; exit 0; fi
    done
    first=$(echo "$rel" | cut -d/ -f1)
    if [ -n "$first" ] && [ -d "$root/$first" ]; then echo "$root"; exit 0; fi
  done
fi
# 3) Share-named directories under /mnt (even with no rel match).
while IFS= read -r d; do
  [ -d "$d" ] || continue
  # Prefer /mnt/PHOENIX/<share> or /mnt/<share> over nested .../amazon/assets.
  case "$d" in
    /mnt/PHOENIX/"$share"|/mnt/"$share") echo "$d"; exit 0 ;;
  esac
  if [ -n "$rel" ] && [ -f "$d/$rel" ]; then echo "$d"; exit 0; fi
  if [ -n "$rel" ]; then
    first=$(echo "$rel" | cut -d/ -f1)
    if [ -n "$first" ] && [ -d "$d/$first" ]; then echo "$d"; exit 0; fi
    if [ -d "$d/$share" ]; then
      if [ -z "$rel" ] || [ -d "$d/$share/$first" ] || [ -f "$d/$share/$rel" ]; then
        echo "$d/$share"; exit 0
      fi
    fi
  elif [ -d "$d" ]; then
    echo "$d"; exit 0
  fi
done <<EOF
$(find /mnt /export /srv /data -maxdepth 4 -type d -iname "$share" 2>/dev/null | head -40)
EOF
exit 1
"""
    code, out, _err = _ssh_run(host, remote, timeout=90)
    if code != 0:
        return None
    found = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    return found[0] if found else None


def auto_discover_maps(
    sample_win_paths: list[str],
    preferred_host: str = "",
) -> dict[str, Any]:
    """
    Build host + unc_to_posix from network paths that exist on Windows.

    Uses ``net use`` for drive→UNC and SSH ``find`` for POSIX share roots.
    """
    result: dict[str, Any] = {
        "ok": False,
        "host": preferred_host or "",
        "unc_to_posix": dict(load_ssh_config().get("unc_to_posix") or {}),
        "message": "",
        "probes": [],
    }

    # Prefer existing modern files as probes; always keep UNC samples (archaic may be missing).
    probes = []
    seen: set[str] = set()
    for p in sample_win_paths:
        p = norm_win(p)
        if not p or p.upper() in seen:
            continue
        is_unc = p.startswith("\\\\")
        if is_unc or os.path.isfile(p) or os.path.isdir(os.path.dirname(p) or p):
            probes.append(p)
            seen.add(p.upper())
    if not probes:
        probes = [norm_win(p) for p in sample_win_paths if p]

    share_rels: dict[str, str] = {}  # unc_share -> relative file path
    servers: set[str] = set()
    for p in probes:
        unc = p if p.startswith("\\\\") else drive_letter_to_unc(p)
        if not unc:
            # Still record bare UNC samples even when the archaic file is missing
            # (dirname may also be missing on a dead share layout).
            if p.startswith("\\\\"):
                unc = p
            else:
                result["probes"].append({"path": p, "error": "not UNC / unmapped drive"})
                continue
        parsed = unc_share_root(unc)
        if not parsed:
            result["probes"].append({"path": p, "error": "bad UNC"})
            continue
        share, rel = parsed
        servers.add(share.split("\\")[2] if share.startswith("\\\\") else "")
        if rel and (share not in share_rels or len(rel) > len(share_rels[share])):
            # Prefer a real file relative path for find; keep missing archaic rels too.
            if os.path.isfile(p) or share not in share_rels:
                share_rels[share] = rel
        result["probes"].append({"path": p, "unc": unc, "share": share, "rel": rel})

    servers.discard("")
    if not share_rels:
        result["message"] = "No network share paths to probe"
        return result

    host = None
    for srv in servers:
        host = resolve_ssh_host(srv, preferred_host)
        if host:
            break
    if not host:
        result["message"] = f"SSH failed for server(s): {', '.join(sorted(servers))}"
        return result
    result["host"] = host

    maps = dict(result["unc_to_posix"])
    discovered = 0
    for share, rel in share_rels.items():
        if not rel:
            continue
        posix_root = discover_posix_root(host, share, rel)
        if posix_root:
            maps[share] = posix_root
            discovered += 1
            result["probes"].append({"share": share, "posix_root": posix_root})
        else:
            result["probes"].append({"share": share, "error": f"POSIX root not found for {rel}"})

    result["unc_to_posix"] = maps
    if discovered:
        result["ok"] = True
        result["message"] = f"Mapped {discovered} share(s) via SSH host {host}"
        save_ssh_config({"host": host, "unc_to_posix": maps})
    else:
        result["message"] = f"SSH ok ({host}) but could not locate share roots under /mnt"
    return result


def shell_quote(s: str) -> str:
    return "'" + (s or "").replace("'", "'\\''") + "'"
