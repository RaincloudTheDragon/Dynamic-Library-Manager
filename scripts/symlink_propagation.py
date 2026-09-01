#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Symlink Propagation wizard — search modern libs, create stubs, await Blender apply, teardown.

Driven by a session JSON written by Dynamic Link Manager (utils/stub_handoff.py).
Uses scripts/path_symlinker.py for native OS stub create/teardown.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any


# ---------------------------------------------------------------------------
# Session / symlinker helpers (no Blender)
# ---------------------------------------------------------------------------

STATUS_OPENED = "opened"
STATUS_STUBS_READY = "stubs_ready"
STATUS_APPLY_DONE = "apply_done"
STATUS_DONE = "done"


def read_json(path: str) -> Any | None:
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_session(path: str) -> dict[str, Any]:
    data = read_json(path)
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid or missing session: {path}")
    return data


def save_session(path: str, data: dict[str, Any]) -> None:
    data = dict(data)
    data["updated_at"] = time.time()
    write_json(path, data)


def scripts_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def symlinker_path() -> str:
    return os.path.join(scripts_dir(), "path_symlinker.py")


if scripts_dir() not in sys.path:
    sys.path.insert(0, scripts_dir())

from path_posix_map import (  # noqa: E402
    auto_discover_maps,
    is_phantom_drive_letter,
    load_ssh_config,
    save_ssh_config,
)


def run_symlinker(
    action: str,
    pairs: list[dict[str, Any]],
    session_dir: str,
    stub_mode: str = "copy",
    ssh: dict[str, Any] | None = None,
    subst_drives: bool = False,
) -> dict[str, Any]:
    """Call path_symlinker via subprocess with payload next to the session."""
    payload_file = os.path.join(session_dir, "payload.json")
    result_file = os.path.join(session_dir, "result.json")
    manifest_file = os.path.join(session_dir, "manifest.json")
    ssh = ssh if ssh is not None else load_ssh_config()

    stub_pairs = [
        {
            "archaic_path": p["archaic_path"],
            "modern_path": p.get("modern_path", ""),
            "kind": p.get("kind", "library"),
            "stub_mode": p.get("stub_mode") or stub_mode,
        }
        for p in pairs
        if p.get("archaic_path") and (action == "teardown" or p.get("modern_path"))
    ]
    write_json(
        payload_file,
        {
            "action": action,
            "pairs": stub_pairs,
            "stub_mode": stub_mode,
            "subst_drives": bool(subst_drives) if os.name == "nt" else False,
            "session_dir": session_dir,
            "ssh": {
                "host": ssh.get("host") or "",
                "unc_to_posix": ssh.get("unc_to_posix") or {},
            },
            "manifest_path": manifest_file,
            "result_path": result_file,
        },
    )
    if os.path.isfile(result_file):
        try:
            os.remove(result_file)
        except OSError:
            pass

    cmd = [
        sys.executable,
        symlinker_path(),
        "--payload",
        payload_file,
        "--result",
        result_file,
        "--manifest",
        manifest_file,
    ]
    try:
        kw = {"capture_output": True, "text": True, "timeout": 600}
        if os.name == "nt":
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        proc = subprocess.run(cmd, **kw)
    except Exception as e:
        return {"ok": False, "error": str(e), "created": [], "failed": [], "removed": []}

    result = read_json(result_file) or {}
    result.setdefault("exit_code", proc.returncode)
    result.setdefault("ok", proc.returncode == 0)
    if proc.stderr:
        result["stderr"] = proc.stderr[-2000:]
    return result


def related_basenames(basename: str) -> list[str]:
    """Exact basename plus *_baked / un-baked sibling names for search."""
    if not basename:
        return []
    stem, ext = os.path.splitext(basename)
    if ext.lower() != ".blend":
        return [basename]
    out = [basename]
    low = stem.lower()
    if low.endswith("_baked"):
        sibling = stem[: -len("_baked")] + ext
    else:
        sibling = stem + "_baked" + ext
    if sibling.lower() != basename.lower():
        out.append(sibling)
    return out


def find_basenames(roots: list[str], basenames: set[str]) -> dict[str, list[str]]:
    """Walk roots for matching .blend basenames; skip directory names starting with '.'."""
    # lower filename -> original request basenames that accept this hit (exact + baked sibling)
    wanted: dict[str, list[str]] = {}
    for b in basenames:
        if not b:
            continue
        for rel in related_basenames(b):
            wanted.setdefault(rel.lower(), []).append(b)
    hits: dict[str, list[str]] = {b: [] for b in basenames}
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                key = name.lower()
                if key not in wanted:
                    continue
                full = os.path.normpath(os.path.join(dirpath, name))
                for original in wanted[key]:
                    if original in hits and full not in hits[original]:
                        hits[original].append(full)
    return hits


def rank_modern_hits(candidates: list[str], *, want_basename: str = "") -> list[str]:
    """Prefer exact basename, then AssetArchive / non-nested over live project trees."""

    want = (want_basename or "").lower()

    def score(path: str) -> tuple:
        u = path.replace("/", "\\").upper()
        base = os.path.basename(path).lower()
        # Higher is better.
        s = 0
        if want and base == want:
            s += 200
        elif want:
            # Related baked/unbaked sibling — keep visible but below exact.
            s += 40
        if "\\0 ASSETARCHIVE\\" in u or u.endswith("\\0 ASSETARCHIVE") or "\\ASSETARCHIVE\\" in u:
            s += 100
        if "CHARACTERS-BAKED" in u and ("_baked" in want or "characters-baked" in want):
            s += 30
        # Nested project false tree: ...\\SomeProject\\1 BlenderAssets\\...
        if "\\1 BLENDERASSETS\\" in u:
            parts = u.split("\\")
            try:
                i = parts.index("1 BLENDERASSETS")
                if i >= 1 and parts[i - 1] not in ("1 AMAZON_ACTIVE_PROJECTS", "AMAZON_ACTIVE_PROJECTS"):
                    s -= 50
            except ValueError:
                pass
        return (s, -len(path))

    return sorted(candidates, key=score, reverse=True)


class TreeHoverTip:
    """Delayed tooltip for ttk.Treeview cells/headings (tk has no built-in hover menus)."""

    def __init__(self, tree: ttk.Treeview, text_fn, delay_ms: int = 450):
        self.tree = tree
        self.text_fn = text_fn
        self.delay_ms = delay_ms
        self._after: str | None = None
        self._tip: tk.Toplevel | None = None
        self._last_key: tuple[Any, ...] | None = None
        tree.bind("<Motion>", self._on_motion, add="+")
        tree.bind("<Leave>", self._on_leave, add="+")

    def _on_leave(self, _event=None) -> None:
        self._cancel()
        self._hide()

    def _on_motion(self, event) -> None:
        region = self.tree.identify_region(event.x, event.y)
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y) if region == "cell" else ""
        key = (region, col, row)
        if key == self._last_key:
            return
        self._last_key = key
        self._cancel()
        self._hide()
        text = self.text_fn(region, col, row)
        if not text:
            return
        self._after = self.tree.after(
            self.delay_ms, lambda e=event, t=text: self._show(e, t)
        )

    def _cancel(self) -> None:
        if self._after:
            self.tree.after_cancel(self._after)
            self._after = None

    def _hide(self) -> None:
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None

    def _show(self, event, text: str) -> None:
        self._hide()
        tip = tk.Toplevel(self.tree)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)
        lbl = tk.Label(
            tip,
            text=text,
            justify=tk.LEFT,
            relief=tk.SOLID,
            borderwidth=1,
            background="#ffffe0",
            foreground="#000000",
            font=("Segoe UI", 9),
            padx=8,
            pady=6,
            wraplength=420,
        )
        lbl.pack()
        tip.update_idletasks()
        x = event.x_root + 16
        y = event.y_root + 12
        tip.wm_geometry(f"+{x}+{y}")
        self._tip = tip


class WidgetHoverTip:
    """Delayed tooltip for buttons and other simple widgets."""

    def __init__(self, widget, text: str, delay_ms: int = 450):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after: str | None = None
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")

    def _on_enter(self, event) -> None:
        self._cancel()
        self._after = self.widget.after(
            self.delay_ms, lambda e=event: self._show(e)
        )

    def _on_leave(self, _event=None) -> None:
        self._cancel()
        self._hide()

    def _cancel(self) -> None:
        if self._after:
            self.widget.after_cancel(self._after)
            self._after = None

    def _hide(self) -> None:
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None

    def _show(self, event) -> None:
        self._hide()
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)
        lbl = tk.Label(
            tip,
            text=self.text,
            justify=tk.LEFT,
            relief=tk.SOLID,
            borderwidth=1,
            background="#ffffe0",
            foreground="#000000",
            font=("Segoe UI", 9),
            padx=8,
            pady=6,
            wraplength=360,
        )
        lbl.pack()
        tip.update_idletasks()
        tip.wm_geometry(f"+{event.x_root + 16}+{event.y_root + 12}")
        self._tip = tip


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


class SymlinkPropagationApp(tk.Tk):
    def __init__(self, session_file: str):
        super().__init__()
        self.session_file = session_file
        self.session_dir = os.path.dirname(session_file)
        self.session = load_session(session_file)
        self.title("Symlink Propagation")
        self.geometry("980x640")
        self.minsize(720, 480)

        cfg = load_ssh_config()
        self.stub_mode = tk.StringVar(value=self.session.get("stub_mode") or "copy")

        self.search_roots: list[str] = list(self.session.get("search_roots") or [])
        self.rows: list[dict[str, Any]] = []
        for m in self.session.get("missing") or []:
            self.rows.append(
                {
                    "archaic_path": m.get("archaic_path", ""),
                    "stored_path": m.get("stored_path", ""),
                    "basename": m.get("basename") or os.path.basename(m.get("archaic_path", "")),
                    "id_name": m.get("id_name", ""),
                    "kind": m.get("kind", "library"),
                    "modern_path": m.get("modern_path", ""),
                    "candidates": [],
                }
            )
        # Restore pairs if re-opening mid session
        by_arch = {
            (p.get("archaic_path") or "").upper(): p.get("modern_path", "")
            for p in (self.session.get("pairs") or [])
        }
        for row in self.rows:
            mp = by_arch.get(row["archaic_path"].upper(), "")
            if mp:
                row["modern_path"] = mp

        subst_default = self.session.get("subst_drives")
        if subst_default is None:
            subst_default = any(
                is_phantom_drive_letter(r.get("archaic_path") or "") for r in self.rows
            )
        self.subst_drives = tk.BooleanVar(value=bool(subst_default))
        self.ssh_host = tk.StringVar(value=cfg.get("host") or "")
        self.ssh_map_var = tk.StringVar(value=self._format_maps(cfg.get("unc_to_posix") or {}))

        self._poll_after: str | None = None
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        status = self.session.get("status") or STATUS_OPENED
        if status == STATUS_STUBS_READY:
            self._set_phase_waiting_blender()
        elif status == STATUS_APPLY_DONE:
            self._set_phase_teardown_ready()
        else:
            self._set_phase_search()

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        top = ttk.Frame(self)
        top.pack(fill=tk.X, **pad)

        ttk.Label(top, text="Search roots").pack(anchor=tk.W)
        roots_row = ttk.Frame(top)
        roots_row.pack(fill=tk.X)
        self.roots_list = tk.Listbox(roots_row, height=3, exportselection=False)
        self.roots_list.pack(side=tk.LEFT, fill=tk.X, expand=True)
        for r in self.search_roots:
            self.roots_list.insert(tk.END, r)
        btns = ttk.Frame(roots_row)
        btns.pack(side=tk.LEFT, padx=4)
        b_add = ttk.Button(btns, text="Add…", command=self._add_root)
        b_add.pack(fill=tk.X)
        b_rem = ttk.Button(btns, text="Remove", command=self._remove_root)
        b_rem.pack(fill=tk.X, pady=2)
        b_search = ttk.Button(btns, text="Search", command=self._run_search)
        b_search.pack(fill=tk.X)
        WidgetHoverTip(b_add, "Add a folder to search for modern .blend files by exact basename.")
        WidgetHoverTip(b_rem, "Remove the selected search root from this session’s list.")
        WidgetHoverTip(
            b_search,
            "Walk search roots for exact basename matches. Skips folder names starting with '.'.",
        )

        ssh_frame = ttk.LabelFrame(
            top,
            text="Stub mode (symlinks on network shares hosted on a Linux machine require SSH to that host)",
        )
        ssh_frame.pack(fill=tk.X, pady=6)
        mode_row = ttk.Frame(ssh_frame)
        mode_row.pack(fill=tk.X, padx=4, pady=2)
        ttk.Radiobutton(mode_row, text="Auto", variable=self.stub_mode, value="auto").pack(side=tk.LEFT)
        ttk.Radiobutton(mode_row, text="Linux SSH", variable=self.stub_mode, value="linux_ssh").pack(
            side=tk.LEFT, padx=8
        )
        ttk.Radiobutton(mode_row, text="Native only", variable=self.stub_mode, value="native").pack(
            side=tk.LEFT
        )
        rb_copy = ttk.Radiobutton(mode_row, text="Copy file", variable=self.stub_mode, value="copy")
        rb_copy.pack(side=tk.LEFT, padx=8)
        WidgetHoverTip(
            rb_copy,
            "Explicit catch-all: copy the modern .blend bytes to the archaic path "
            "(works on SMB when symlinks fail). Never chosen by Auto.\n\n"
            "Teardown deletes the copy only if size+hash still match what we wrote — "
            "mismatch refuses delete.",
        )
        if os.name == "nt":
            subst_row = ttk.Frame(ssh_frame)
            subst_row.pack(fill=tk.X, padx=4, pady=(0, 4))
            cb_subst = ttk.Checkbutton(
                subst_row,
                text="Subst unmapped drive letters",
                variable=self.subst_drives,
            )
            cb_subst.pack(side=tk.LEFT)
            WidgetHoverTip(
                cb_subst,
                "When an archaic path uses a drive letter that is not mapped on this PC "
                "(e.g. phantom T:\\...), map that letter to a temp folder under this "
                "session via subst, then create Native or Copy stubs under it.\n\n"
                "Does not apply to UNC paths (use Linux SSH). subst can target UNC on "
                "Windows, but symlinks on network shares remain unreliable — this "
                "option is for missing local letters only.\n\n"
                "Teardown runs subst X: /D only for letters this wizard created.",
            )
        host_row = ttk.Frame(ssh_frame)
        host_row.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(host_row, text="SSH host").pack(side=tk.LEFT)
        ttk.Entry(host_row, textvariable=self.ssh_host, width=24).pack(side=tk.LEFT, padx=4)
        b_map = ttk.Button(host_row, text="Auto-map POSIX…", command=self._auto_map)
        b_map.pack(side=tk.LEFT, padx=4)
        WidgetHoverTip(
            b_map,
            "Discover UNC/drive → Linux paths via net use + SSH (saved under LocalAppData, not Blender prefs).",
        )
        ttk.Label(ssh_frame, textvariable=self.ssh_map_var, wraplength=900).pack(
            anchor=tk.W, padx=4, pady=2
        )

        mid = ttk.Frame(self)
        mid.pack(fill=tk.BOTH, expand=True, **pad)

        cols = ("basename", "stored", "archaic", "modern", "status")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("basename", text="Basename")
        self.tree.heading("stored", text="Stored")
        self.tree.heading("archaic", text="Archaic (abs)")
        self.tree.heading("modern", text="Modern path")
        self.tree.heading("status", text="")
        self.tree.column("basename", width=150, stretch=False)
        self.tree.column("stored", width=70, stretch=False)
        self.tree.column("archaic", width=260)
        self.tree.column("modern", width=260)
        self.tree.column("status", width=70, stretch=False)
        scroll = ttk.Scrollbar(mid, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.LEFT, fill=tk.Y)
        self._col_by_id = {
            "#1": "basename",
            "#2": "stored",
            "#3": "archaic",
            "#4": "modern",
            "#5": "status",
        }
        TreeHoverTip(self.tree, self._tree_hover_text)

        row_btns = ttk.Frame(mid)
        row_btns.pack(side=tk.LEFT, fill=tk.Y, padx=4)
        b_browse = ttk.Button(row_btns, text="Browse…", command=self._browse_modern)
        b_browse.pack(fill=tk.X)
        b_pick = ttk.Button(row_btns, text="Pick hit…", command=self._pick_candidate)
        b_pick.pack(fill=tk.X, pady=2)
        b_clear = ttk.Button(row_btns, text="Clear", command=self._clear_modern)
        b_clear.pack(fill=tk.X)
        WidgetHoverTip(
            b_browse,
            "Manually choose the modern .blend for the selected row (use when the basename changed).",
        )
        WidgetHoverTip(
            b_pick,
            "Choose among multiple Search hits for the selected row.",
        )
        WidgetHoverTip(b_clear, "Clear the modern path on the selected row.")

        bottom = ttk.Frame(self)
        bottom.pack(fill=tk.X, **pad)
        self.status_var = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self.status_var, wraplength=700).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.action_btn = ttk.Button(bottom, text="Create stubs", command=self._create_stubs)
        self.action_btn.pack(side=tk.RIGHT)
        self.confirm_btn = ttk.Button(
            bottom, text="I've finished in Blender", command=self._confirm_apply_done
        )
        self.confirm_btn.pack(side=tk.RIGHT, padx=4)
        self.confirm_btn.pack_forget()
        self._action_tip = WidgetHoverTip(
            self.action_btn,
            "Create temporary stubs at archaic paths so Blender can load libraries, "
            "then Revert and Remap in Blender (Remap does not save). "
            "Only removes/replaces symlinks — never real files.",
        )
        WidgetHoverTip(
            self.confirm_btn,
            "Skip waiting for apply_done in the session file and go straight to teardown.",
        )

        self._refresh_tree()

    @staticmethod
    def _format_maps(maps: dict[str, str]) -> str:
        if not maps:
            return "No UNC→POSIX maps yet (Auto-map uses net use + SSH find; saved outside Blender prefs)."
        parts = [f"{k} → {v}" for k, v in maps.items()]
        return "Maps: " + "; ".join(parts)

    def _ssh_payload(self) -> dict[str, Any]:
        cfg = load_ssh_config()
        host = (self.ssh_host.get() or "").strip() or (cfg.get("host") or "")
        return {"host": host, "unc_to_posix": dict(cfg.get("unc_to_posix") or {})}

    def _auto_map(self) -> None:
        samples = []
        for r in self.rows:
            if r.get("modern_path"):
                samples.append(r["modern_path"])
            if r.get("archaic_path"):
                samples.append(r["archaic_path"])
        samples.extend(self.search_roots)
        if not samples:
            messagebox.showinfo("Auto-map", "Set modern paths or search roots first.")
            return
        self.status_var.set("Discovering POSIX maps via SSH…")
        self.update_idletasks()
        preferred = (self.ssh_host.get() or "").strip()

        def work() -> None:
            result = auto_discover_maps(samples, preferred_host=preferred)
            self.after(0, lambda: self._auto_map_done(result))

        threading.Thread(target=work, daemon=True).start()

    def _auto_map_done(self, result: dict[str, Any]) -> None:
        if result.get("host"):
            self.ssh_host.set(result["host"])
        self.ssh_map_var.set(self._format_maps(result.get("unc_to_posix") or {}))
        if result.get("ok"):
            self.status_var.set(result.get("message") or "Maps saved.")
            messagebox.showinfo("Auto-map", result.get("message") or "OK")
        else:
            self.status_var.set(result.get("message") or "Auto-map failed")
            messagebox.showerror("Auto-map", result.get("message") or "Failed")

    def _row_index(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except ValueError:
            return None

    @staticmethod
    def _stored_kind(stored: str) -> str:
        """How Blender stored the library path: relative (//) or absolute."""
        s = (stored or "").strip()
        if not s:
            return "?"
        if s.startswith("//"):
            return "relative"
        return "absolute"

    def _tree_hover_text(self, region: str, col_id: str, row_iid: str) -> str:
        """Tooltip copy for tree headings/cells."""
        col = self._col_by_id.get(col_id, "")
        row = None
        if row_iid:
            try:
                row = self.rows[int(row_iid)]
            except (ValueError, IndexError):
                row = None

        if col == "archaic":
            base = (
                "Where Blender is looking right now for this linked library "
                "(absolute path after resolving // relative paths against this anim blend).\n\n"
                "If the anim .blend was moved (e.g. one folder deeper/shallower), relatives "
                "like ../../../1 BlenderAssets resolve to the wrong place — the file is "
                "“missing” even though a modern copy exists elsewhere."
            )
            if row and row.get("archaic_path"):
                return f"{base}\n\n{row['archaic_path']}"
            return base

        if col == "stored":
            kind = self._stored_kind((row or {}).get("stored_path") or "")
            stored = (row or {}).get("stored_path") or ""
            if kind == "relative":
                msg = (
                    "Blender stored this as a // relative path (from the anim blend). "
                    "Moving the anim file changes where those relatives resolve."
                )
            elif kind == "absolute":
                msg = (
                    "Blender stored this as an absolute path. Relatives are not involved; "
                    "the link is broken because that absolute location is gone or wrong."
                )
            else:
                msg = "How Blender stored the library filepath (relative // vs absolute)."
            return f"{msg}\n\n{stored}" if stored else msg

        if col == "modern":
            return (
                "Target .blend to rempath to after stubs load. "
                "Search fills this by exact basename; use Browse/Pick when names changed."
            )

        if col == "basename":
            return "Library filename Blender links (exact basename match for Search)."

        if col == "status":
            return "ok = modern file exists on disk; hits = Search found candidates."

        return ""

    def _refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(self.rows):
            modern = row.get("modern_path") or ""
            n = len(row.get("candidates") or [])
            status = ""
            if modern:
                status = "ok" if os.path.isfile(modern) else "missing"
            elif n > 1:
                status = f"{n} hits"
            elif n == 1:
                status = "1 hit"
            self.tree.insert(
                "",
                tk.END,
                iid=str(i),
                values=(
                    row.get("basename", ""),
                    self._stored_kind(row.get("stored_path") or ""),
                    row.get("archaic_path", ""),
                    modern,
                    status,
                ),
            )

    def _persist_roots(self) -> None:
        self.session["search_roots"] = list(self.search_roots)
        save_session(self.session_file, self.session)

    def _add_root(self) -> None:
        path = filedialog.askdirectory(title="Add search root")
        if not path:
            return
        path = os.path.normpath(path)
        if path not in self.search_roots:
            self.search_roots.append(path)
            self.roots_list.insert(tk.END, path)
            self._persist_roots()

    def _remove_root(self) -> None:
        sel = self.roots_list.curselection()
        if not sel:
            return
        idx = sel[0]
        self.roots_list.delete(idx)
        del self.search_roots[idx]
        self._persist_roots()

    def _run_search(self) -> None:
        if not self.search_roots:
            messagebox.showinfo("Search", "Add at least one search root folder.")
            return
        missing_roots = [r for r in self.search_roots if not os.path.isdir(r)]
        if missing_roots:
            messagebox.showwarning(
                "Search",
                "These search roots do not exist (check for typos):\n\n"
                + "\n".join(missing_roots),
            )
        ok_roots = [r for r in self.search_roots if os.path.isdir(r)]
        if not ok_roots:
            self.status_var.set("Search skipped — no existing search roots.")
            return
        basenames = {r["basename"] for r in self.rows if r.get("basename")}
        self.status_var.set("Searching…")
        self.update_idletasks()

        def work() -> None:
            hits = find_basenames(ok_roots, basenames)
            self.after(0, lambda: self._apply_search_hits(hits, skipped=missing_roots))

        threading.Thread(target=work, daemon=True).start()

    def _apply_search_hits(self, hits: dict[str, list[str]], skipped: list[str] | None = None) -> None:
        for row in self.rows:
            want = row["basename"]
            cands = rank_modern_hits(hits.get(want, []), want_basename=want)
            row["candidates"] = cands
            if not row.get("modern_path"):
                exact = [c for c in cands if os.path.basename(c).lower() == want.lower()]
                if len(exact) == 1:
                    row["modern_path"] = exact[0]
                elif len(exact) > 1:
                    row["modern_path"] = exact[0]
                elif len(cands) == 1:
                    row["modern_path"] = cands[0]
                elif len(cands) > 1:
                    # Multiple related hits (e.g. unbaked + baked) — prefer exact-ranked top.
                    row["modern_path"] = cands[0]
        self._refresh_tree()
        filled = sum(1 for r in self.rows if r.get("modern_path"))
        msg = f"Search done — {filled}/{len(self.rows)} modern paths set."
        if skipped:
            msg += f" ({len(skipped)} root(s) missing on disk)"
        self.status_var.set(msg)

    def _browse_modern(self) -> None:
        idx = self._row_index()
        if idx is None:
            messagebox.showinfo("Browse", "Select a row first.")
            return
        path = filedialog.askopenfilename(
            title="Modern .blend",
            filetypes=[("Blender", "*.blend"), ("All", "*.*")],
        )
        if not path:
            return
        self.rows[idx]["modern_path"] = os.path.normpath(path)
        self._refresh_tree()

    def _pick_candidate(self) -> None:
        idx = self._row_index()
        if idx is None:
            messagebox.showinfo("Pick", "Select a row first.")
            return
        cands = self.rows[idx].get("candidates") or []
        if not cands:
            messagebox.showinfo("Pick", "No search hits for this row. Run Search or Browse.")
            return
        win = tk.Toplevel(self)
        win.title("Choose modern path")
        win.geometry("640x320")
        lb = tk.Listbox(win, exportselection=False)
        lb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        for c in cands:
            lb.insert(tk.END, c)
        lb.selection_set(0)

        def ok() -> None:
            sel = lb.curselection()
            if sel:
                self.rows[idx]["modern_path"] = cands[sel[0]]
                self._refresh_tree()
            win.destroy()

        ttk.Button(win, text="Use selected", command=ok).pack(pady=4)

    def _clear_modern(self) -> None:
        idx = self._row_index()
        if idx is None:
            return
        self.rows[idx]["modern_path"] = ""
        self._refresh_tree()

    def _pairs_from_rows(self) -> list[dict[str, Any]]:
        mode = self.stub_mode.get() or "copy"
        return [
            {
                "archaic_path": r["archaic_path"],
                "modern_path": r.get("modern_path") or "",
                "stored_path": r.get("stored_path") or "",
                "basename": r.get("basename") or "",
                "id_name": r.get("id_name") or "",
                "kind": r.get("kind") or "library",
                "needs_stub": True,
                "stub_mode": mode,
            }
            for r in self.rows
            if r.get("archaic_path") and r.get("modern_path")
        ]

    def _set_phase_search(self) -> None:
        self.action_btn.configure(text="Create stubs", command=self._create_stubs, state=tk.NORMAL)
        self.confirm_btn.pack_forget()
        self._action_tip.text = (
            "Create temporary stubs at archaic paths so Blender can load libraries, "
            "then Revert and Remap in Blender (Remap does not save). "
            "Only removes/replaces symlinks — never real files."
        )
        self.status_var.set(
            f"{len(self.rows)} missing libraries. Search, Auto-map POSIX (for SMB), then Create stubs."
        )

    def _set_phase_waiting_blender(self) -> None:
        self.action_btn.configure(text="Waiting for Blender…", state=tk.DISABLED)
        self.confirm_btn.pack(side=tk.RIGHT, padx=4)
        self._action_tip.text = "Waiting until Blender writes apply_done (or use I’ve finished in Blender)."
        self.status_var.set(
            "Stubs ready. In Blender: Revert → verify hits → Remap (no auto-save), "
            "then return here — or press I've finished in Blender."
        )
        self._start_poll()

    def _set_phase_teardown_ready(self) -> None:
        if self._poll_after:
            self.after_cancel(self._poll_after)
            self._poll_after = None
        self.confirm_btn.pack_forget()
        self.action_btn.configure(text="Teardown stubs", command=self._teardown, state=tk.NORMAL)
        self._action_tip.text = (
            "Remove temporary stubs created earlier. Symlink/copy stubs only when "
            "verified; then prune empty parent folders (stops if siblings remain)."
        )
        self.status_var.set("Blender apply done. Click Teardown stubs to remove temporary links.")

    def _create_stubs(self) -> None:
        pairs = self._pairs_from_rows()
        if not pairs:
            messagebox.showwarning("Create stubs", "Set at least one modern path first.")
            return
        incomplete = [r["basename"] for r in self.rows if not r.get("modern_path")]
        if incomplete:
            if not messagebox.askyesno(
                "Create stubs",
                f"{len(incomplete)} row(s) have no modern path and will be skipped.\nContinue?",
            ):
                return

        mode = self.stub_mode.get() or "copy"
        if mode == "copy":
            if not messagebox.askyesno(
                "Copy stubs",
                "This copies full .blend files to the archaic paths, then deletes "
                "those copies on teardown if they still match what was written.\n\n"
                "That is destructive — a mistake can overwrite or remove the wrong "
                "file. Continue?",
            ):
                return

        self.status_var.set("Creating stubs…")
        self.action_btn.configure(state=tk.DISABLED)
        self.update_idletasks()

        ssh = self._ssh_payload()
        if mode in ("auto", "linux_ssh") and not (ssh.get("unc_to_posix") or {}):
            # Discover before create when maps are empty.
            samples = [p["modern_path"] for p in pairs] + [p["archaic_path"] for p in pairs]
            disc = auto_discover_maps(samples, preferred_host=ssh.get("host") or "")
            if disc.get("ok"):
                ssh = {"host": disc.get("host") or "", "unc_to_posix": disc.get("unc_to_posix") or {}}
                self.ssh_host.set(ssh["host"])
                self.ssh_map_var.set(self._format_maps(ssh["unc_to_posix"]))
            elif mode == "linux_ssh":
                self.action_btn.configure(state=tk.NORMAL)
                messagebox.showerror("Create stubs", disc.get("message") or "Need UNC→POSIX maps")
                return

        if ssh.get("host"):
            save_ssh_config({"host": ssh["host"], "unc_to_posix": ssh.get("unc_to_posix") or {}})

        result = run_symlinker(
            "create",
            pairs,
            self.session_dir,
            stub_mode=mode,
            ssh=ssh,
            subst_drives=self.subst_drives.get(),
        )
        failed = result.get("failed") or []
        created = result.get("created") or []
        if not result.get("ok") and not created:
            self.action_btn.configure(state=tk.NORMAL)
            detail = result.get("error") or ""
            if failed:
                detail = "; ".join(
                    f"{os.path.basename(f.get('archaic_path',''))}: {f.get('message')}" for f in failed[:3]
                )
            messagebox.showerror(
                "Create stubs",
                detail or f"Failed ({len(failed)}). Check SSH maps / permissions.",
            )
            self.status_var.set("Stub create failed.")
            return

        # Only keep pairs Windows can actually load (created list already excludes fails).
        created_arch = {
            (c.get("archaic_path") or "").replace("/", "\\").upper() for c in created
        }
        ready_pairs = [
            p
            for p in pairs
            if (p.get("archaic_path") or "").replace("/", "\\").upper() in created_arch
        ]
        if failed:
            detail = "\n".join(
                f"{os.path.basename(f.get('archaic_path') or '?')}: {f.get('message')}"
                for f in failed[:5]
            )
            messagebox.showwarning(
                "Partial stubs",
                f"Created {len(created)}, failed {len(failed)}.\n{detail}\n\n"
                "Failed rows are excluded from Remap. Fix SSH maps / share access, "
                "re-create those stubs, then Revert + Remap in Blender.",
            )
        if not created:
            self.action_btn.configure(state=tk.NORMAL)
            self.status_var.set("No stubs visible to Windows — nothing to Remap.")
            return

        self.session["pairs"] = ready_pairs
        self.session["status"] = STATUS_STUBS_READY
        self.session["stub_mode"] = mode
        self.session["subst_drives"] = bool(self.subst_drives.get())
        self.session["message"] = f"created={len(created)} failed={len(failed)}"
        self.session["search_roots"] = list(self.search_roots)
        save_session(self.session_file, self.session)
        self._set_phase_waiting_blender()

    def _start_poll(self) -> None:
        if self._poll_after:
            self.after_cancel(self._poll_after)
        self._poll_session()

    def _poll_session(self) -> None:
        data = read_json(self.session_file) or {}
        status = data.get("status")
        if status == STATUS_APPLY_DONE:
            self.session = data
            self._set_phase_teardown_ready()
            return
        if status == STATUS_DONE:
            self.destroy()
            return
        self._poll_after = self.after(1500, self._poll_session)

    def _confirm_apply_done(self) -> None:
        data = load_session(self.session_file)
        if data.get("status") != STATUS_APPLY_DONE:
            n = int(data.get("remapped_count") or 0)
            if n <= 0:
                if not messagebox.askyesno(
                    "Confirm",
                    "Blender has not reported a successful rempath yet "
                    "(remapped_count=0).\n\n"
                    "Teardown now will remove stubs while libraries may still "
                    "point at archaic paths.\n\nProceed anyway?",
                ):
                    return
            elif not messagebox.askyesno(
                "Confirm",
                "Session is not apply_done yet. Mark apply done and proceed to teardown?",
            ):
                return
            data["status"] = STATUS_APPLY_DONE
            save_session(self.session_file, data)
        self.session = data
        self._set_phase_teardown_ready()

    def _teardown(self) -> None:
        pairs = list(self.session.get("pairs") or self._pairs_from_rows())
        self.status_var.set("Removing stubs…")
        self.action_btn.configure(state=tk.DISABLED)
        self.update_idletasks()
        result = run_symlinker(
            "teardown",
            pairs,
            self.session_dir,
            stub_mode=self.session.get("stub_mode") or self.stub_mode.get() or "copy",
            ssh=self._ssh_payload(),
            subst_drives=bool(self.session.get("subst_drives")),
        )
        failed = result.get("failed") or []
        self.session["status"] = STATUS_DONE
        self.session["message"] = result.get("error") or f"removed={len(result.get('removed') or [])}"
        save_session(self.session_file, self.session)
        if failed:
            detail = "\n".join(
                f"{os.path.basename(f.get('archaic_path') or '?')}: {f.get('message')}"
                for f in failed[:5]
            )
            messagebox.showwarning("Teardown", f"Some stubs failed to remove ({len(failed)}).\n{detail}")
        else:
            messagebox.showinfo("Teardown", "Stubs removed. You can close this window.")
        self.destroy()

    def _on_close(self) -> None:
        status = (read_json(self.session_file) or {}).get("status")
        if status in (STATUS_STUBS_READY, STATUS_APPLY_DONE):
            if not messagebox.askyesno(
                "Close wizard?",
                "Stubs may still exist. Close without teardown?\n"
                "(You can reopen via Symlink Propagation if the session file remains.)",
            ):
                return
        self.destroy()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DLM Symlink Propagation wizard")
    parser.add_argument("--session", required=True, help="Path to session.json")
    args = parser.parse_args(argv)
    crash_log = os.path.join(os.path.dirname(args.session) or ".", "wizard_crash.log")
    try:
        app = SymlinkPropagationApp(args.session)
        # Raise above other windows once; user can still alt-tab later.
        try:
            app.lift()
            app.attributes("-topmost", True)
            app.after(400, lambda: app.attributes("-topmost", False))
            app.focus_force()
        except tk.TclError:
            pass
        app.mainloop()
        return 0
    except Exception:
        import traceback

        try:
            with open(crash_log, "w", encoding="utf-8") as f:
                traceback.print_exc(file=f)
        except OSError:
            pass
        raise


if __name__ == "__main__":
    sys.exit(main())
