# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

"""Handoff between DLM and the Symlink Propagation wizard / native symlinker."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from typing import Any


HANDOFF_DIR_NAME = "dlm_path_stubs"
SESSION_NAME = "session.json"
PAYLOAD_NAME = "payload.json"
RESULT_NAME = "result.json"
MANIFEST_NAME = "manifest.json"

# opened → stubs_ready → apply_done → done
STATUS_OPENED = "opened"
STATUS_STUBS_READY = "stubs_ready"
STATUS_APPLY_DONE = "apply_done"
STATUS_DONE = "done"


def addon_scripts_dir() -> str:
    """Directory containing scripts/ inside the addon."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")


def wizard_script_path() -> str:
    return os.path.join(addon_scripts_dir(), "symlink_propagation.py")


def symlinker_script_path() -> str:
    return os.path.join(addon_scripts_dir(), "path_symlinker.py")


def handoff_dir(create: bool = True) -> str:
    """Temp directory for session / stubs (survives blend revert)."""
    base = os.path.join(tempfile.gettempdir(), HANDOFF_DIR_NAME)
    if create:
        os.makedirs(base, exist_ok=True)
    return base


def session_path() -> str:
    return os.path.join(handoff_dir(), SESSION_NAME)


def payload_path() -> str:
    return os.path.join(handoff_dir(), PAYLOAD_NAME)


def result_path() -> str:
    return os.path.join(handoff_dir(), RESULT_NAME)


def manifest_path() -> str:
    return os.path.join(handoff_dir(), MANIFEST_NAME)


def write_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def read_json(path: str) -> Any | None:
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_session() -> dict[str, Any] | None:
    data = read_json(session_path())
    return data if isinstance(data, dict) else None


def save_session(data: dict[str, Any]) -> str:
    path = session_path()
    data = dict(data)
    data["updated_at"] = time.time()
    write_json(path, data)
    return path


def clear_session() -> None:
    path = session_path()
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def create_session(
    missing: list[dict[str, Any]],
    blend_filepath: str = "",
    search_roots: list[str] | None = None,
) -> dict[str, Any]:
    """Start a new wizard session from missing library entries."""
    session = {
        "status": STATUS_OPENED,
        "blend_filepath": blend_filepath or "",
        "missing": missing,
        "pairs": [],
        "search_roots": list(search_roots or []),
        "wizard_pid": None,
        "created_at": time.time(),
        "updated_at": time.time(),
        "message": "",
    }
    save_session(session)
    return session


def set_session_status(status: str, **updates: Any) -> dict[str, Any] | None:
    session = load_session()
    if not session:
        return None
    session["status"] = status
    session.update(updates)
    save_session(session)
    return session


def session_pairs() -> list[dict[str, Any]]:
    session = load_session()
    if not session:
        return []
    return list(session.get("pairs") or [])


def build_payload(action: str, pairs: list[dict[str, Any]]) -> dict[str, Any]:
    """Build create/teardown payload for path_symlinker.py."""
    stub_pairs = []
    for p in pairs:
        if action == "create" and not p.get("modern_path"):
            continue
        stub_pairs.append(
            {
                "archaic_path": p["archaic_path"],
                "modern_path": p.get("modern_path", ""),
                "kind": p.get("kind", "library"),
                "stub_mode": "native",
                "needs_stub": True,
            }
        )
    return {
        "action": action,
        "pairs": stub_pairs,
        "manifest_path": manifest_path(),
        "result_path": result_path(),
    }


def write_payload(payload: dict[str, Any]) -> str:
    path = payload_path()
    rp = result_path()
    if os.path.isfile(rp):
        try:
            os.remove(rp)
        except OSError:
            pass
    write_json(path, payload)
    return path


def spawn_symlinker(payload: dict[str, Any] | None = None, wait: bool = True, timeout: float = 600.0) -> dict[str, Any]:
    """Spawn scripts/path_symlinker.py; return result.json contents."""
    script = symlinker_script_path()
    if not os.path.isfile(script):
        return {
            "ok": False,
            "exit_code": 2,
            "error": f"Symlinker script missing: {script}",
            "created": [],
            "failed": [],
        }

    if payload is not None:
        write_payload(payload)

    cmd = [
        sys.executable,
        script,
        "--payload",
        payload_path(),
        "--result",
        result_path(),
        "--manifest",
        manifest_path(),
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=os.path.dirname(script),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception as e:
        return {"ok": False, "exit_code": 2, "error": str(e), "created": [], "failed": []}

    if not wait:
        return {"ok": True, "exit_code": None, "pid": proc.pid, "spawned": True}

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return {
            "ok": False,
            "exit_code": 2,
            "error": f"Symlinker timed out after {timeout}s",
            "created": [],
            "failed": [],
        }

    result = read_json(result_path()) or {}
    result.setdefault("exit_code", proc.returncode)
    result.setdefault("ok", proc.returncode == 0)
    if stdout:
        result["stdout"] = stdout[-4000:]
    if stderr:
        result["stderr"] = stderr[-4000:]
    if proc.returncode not in (0, 1) and "error" not in result:
        result["error"] = f"Symlinker exit {proc.returncode}"
    return result


def _python_has_tkinter(exe: str) -> bool:
    """True if *exe* can import tkinter (Blender's bundled Python usually cannot)."""
    if not exe or not os.path.isfile(exe):
        return False
    try:
        r = subprocess.run(
            [exe, "-c", "import tkinter"],
            capture_output=True,
            timeout=15,
        )
        return r.returncode == 0
    except Exception:
        return False


def python_for_wizard() -> str | None:
    """
    Prefer a host Python with tkinter over Blender's sys.executable.

    Blender's embedded interpreter ships without tkinter; the wizard needs it.
    """
    candidates: list[str] = []
    if os.name == "nt":
        candidates.extend(["py", "python", "python3"])
    else:
        candidates.extend(["python3", "python"])
    candidates.append(sys.executable)

    seen: set[str] = set()
    for c in candidates:
        key = c.lower()
        if key in seen:
            continue
        seen.add(key)
        if os.path.sep in c or (os.name == "nt" and ":" in c):
            exe = c
        else:
            import shutil

            exe = shutil.which(c) or ""
        if not exe:
            continue
        if os.path.basename(exe).lower() in ("py.exe", "py"):
            try:
                r = subprocess.run(
                    [exe, "-3", "-c", "import tkinter; import sys; print(sys.executable)"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if r.returncode == 0:
                    resolved = (r.stdout or "").strip().splitlines()[-1].strip()
                    if resolved and os.path.isfile(resolved):
                        return resolved
            except Exception:
                continue
            continue
        if _python_has_tkinter(exe):
            return exe
    return None


def _clean_env_for_wizard() -> dict[str, str]:
    """Drop Blender/debugpy PYTHON* vars so system Python does not inherit them."""
    env = dict(os.environ)
    drop_exact = {
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONEXECUTABLE",
        "BLENDER_SYSTEM_PYTHON",
        "PYTHONUSERBASE",
        "PYTHONBREAKPOINT",
    }
    for key in list(env.keys()):
        ku = key.upper()
        if key in drop_exact or ku.startswith("PYDEVD") or ku.startswith("DEBUGPY"):
            env.pop(key, None)
    env.setdefault("PYTHONUTF8", "1")
    return env


def _env_block(env: dict[str, str]) -> bytes:
    """Windows CreateProcess environment block (UTF-16LE)."""
    parts = [f"{k}={v}" for k, v in env.items()]
    return ("\0".join(parts) + "\0\0").encode("utf-16-le")


def _spawn_wizard_win(py: str, script: str, session: str, cwd: str, log_path: str) -> tuple[int, str | None]:
    """
    Launch via CreateProcessW to bypass debugpy's subprocess.Popen hook
    (VS Code / Blender debugger injects into children spawned through subprocess).
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32

    py_launch = py
    if py.lower().endswith("python.exe"):
        candidate = py[:-10] + "pythonw.exe"
        if os.path.isfile(candidate):
            py_launch = candidate

    cmd = subprocess.list2cmdline([py_launch, script, "--session", session])
    cmdline = ctypes.create_unicode_buffer(cmd)
    env_buf = ctypes.create_string_buffer(_env_block(_clean_env_for_wizard()))

    class STARTUPINFO(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    STARTF_USESHOWWINDOW = 0x00000001
    SW_SHOWNORMAL = 1
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_UNICODE_ENVIRONMENT = 0x00000400
    DETACHED_PROCESS = 0x00000008
    flags = CREATE_NEW_PROCESS_GROUP | CREATE_UNICODE_ENVIRONMENT | DETACHED_PROCESS

    si = STARTUPINFO()
    si.cb = ctypes.sizeof(STARTUPINFO)
    si.dwFlags = STARTF_USESHOWWINDOW
    si.wShowWindow = SW_SHOWNORMAL
    pi = PROCESS_INFORMATION()

    ok = kernel32.CreateProcessW(
        None,
        cmdline,
        None,
        None,
        False,
        flags,
        env_buf,
        cwd,
        ctypes.byref(si),
        ctypes.byref(pi),
    )
    if not ok:
        return 0, f"CreateProcessW failed (WinError {ctypes.GetLastError()})"
    pid = int(pi.dwProcessId)
    kernel32.CloseHandle(pi.hThread)
    kernel32.CloseHandle(pi.hProcess)
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"spawned pid={pid} exe={py_launch}\ncmd={cmd}\n")
    except OSError:
        pass
    return pid, None


def _process_cmdline(pid: int) -> str:
    """Best-effort command line for *pid*."""
    if os.name != "nt":
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                return f.read().decode("utf-8", errors="replace").replace("\x00", " ")
        except OSError:
            return ""
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


def spawn_wizard(wait: bool = False) -> dict[str, Any]:
    """Spawn the Symlink Propagation tkinter wizard (usually non-blocking)."""
    script = wizard_script_path()
    if not os.path.isfile(script):
        return {"ok": False, "error": f"Wizard script missing: {script}"}

    session = load_session()
    if not session:
        return {"ok": False, "error": "No session to hand to wizard"}

    py = python_for_wizard()
    if not py:
        return {
            "ok": False,
            "error": (
                "No Python with tkinter found. Install a system Python that includes tkinter "
                "(Blender's bundled Python does not)."
            ),
        }

    log_path = os.path.join(handoff_dir(), "wizard_stderr.log")
    cwd = os.path.dirname(script)
    session_file = session_path()

    if os.name == "nt" and not wait:
        pid, err = _spawn_wizard_win(py, script, session_file, cwd, log_path)
        if err or not pid:
            return {"ok": False, "error": err or "CreateProcess failed"}
        set_session_status(STATUS_OPENED, wizard_pid=pid, wizard_python=py)
        time.sleep(0.9)
        if not wizard_appears_running({"wizard_pid": pid}):
            err_tail = ""
            for path in (os.path.join(handoff_dir(), "wizard_crash.log"), log_path):
                if os.path.isfile(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            err_tail = f.read()[-2000:]
                    except OSError:
                        pass
                    if err_tail.strip():
                        break
            return {
                "ok": False,
                "error": (
                    f"Wizard process {pid} exited immediately. "
                    f"{err_tail or 'See wizard_crash.log in temp/dlm_path_stubs.'}"
                ),
                "pid": pid,
            }
        return {"ok": True, "pid": pid, "spawned": True, "python": py}

    cmd = [py, script, "--session", session_file]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=_clean_env_for_wizard(),
            start_new_session=True,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}

    set_session_status(STATUS_OPENED, wizard_pid=proc.pid, wizard_python=py)
    if wait:
        proc.wait()
        return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "pid": proc.pid}

    time.sleep(0.6)
    if proc.poll() is not None:
        return {
            "ok": False,
            "error": f"Wizard exited immediately (code {proc.returncode}). Python={py}.",
            "pid": proc.pid,
        }
    return {"ok": True, "pid": proc.pid, "spawned": True, "python": py}


def wizard_appears_running(session: dict[str, Any] | None = None) -> bool:
    """True only if wizard_pid is alive and its command line is our wizard script."""
    session = session if session is not None else load_session()
    if not session:
        return False
    pid = session.get("wizard_pid")
    if not pid:
        return False
    try:
        if os.name == "nt":
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
        else:
            os.kill(int(pid), 0)
    except Exception:
        return False

    cmdline = _process_cmdline(int(pid)).lower()
    if not cmdline:
        return False
    # pythonw.exe command lines still include the script path.
    return "symlink_propagation.py" in cmdline
