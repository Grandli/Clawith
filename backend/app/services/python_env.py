"""Utilities for resolving agent Python runtime and execution env."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Mapping

from loguru import logger


def _backend_root() -> Path:
    # backend/app/services/python_env.py -> backend/
    return Path(__file__).resolve().parents[2]


def _resolve_python_candidate(path: Path) -> Path | None:
    """Normalize a user-provided path into a runnable python executable."""
    # 1) Direct executable path
    if path.is_file() and os.access(path, os.X_OK):
        return path

    # 2) User accidentally points to activate script
    if path.name in {"activate", "activate.csh", "activate.fish"}:
        for sibling in ("python", "python3"):
            candidate = path.with_name(sibling)
            if candidate.exists() and os.access(candidate, os.X_OK):
                return candidate

    # 3) User points to venv root or bin/Scripts directory
    dir_candidate = path if path.is_dir() else None
    if dir_candidate:
        candidates = [
            dir_candidate / "bin" / "python",
            dir_candidate / "bin" / "python3",
            dir_candidate / "Scripts" / "python.exe",
            dir_candidate / "python",
            dir_candidate / "python3",
        ]
        for candidate in candidates:
            if candidate.exists() and os.access(candidate, os.X_OK):
                return candidate

    return None


def resolve_agent_python_bin() -> str:
    """Resolve python executable used by agent code execution.

    Priority:
    1) AGENT_PYTHON_BIN env setting (absolute or backend-relative path)
    2) backend/.venv/bin/python
    3) python3 from PATH
    """
    configured = os.environ.get("AGENT_PYTHON_BIN", "").strip()
    backend_root = _backend_root()

    if configured:
        configured_path = Path(configured)
        if not configured_path.is_absolute():
            configured_path = (backend_root / configured_path).resolve()
        resolved = _resolve_python_candidate(configured_path)
        if resolved:
            return str(resolved)
        logger.warning(f"[PythonEnv] AGENT_PYTHON_BIN is invalid/non-executable: {configured_path}")

    default_venv_python = backend_root / ".venv" / "bin" / "python"
    if default_venv_python.exists() and os.access(default_venv_python, os.X_OK):
        return str(default_venv_python)

    return shutil.which("python3") or "python3"


def build_agent_exec_env(base_env: Mapping[str, str], home: Path | None = None) -> dict[str, str]:
    """Build subprocess env with backend venv preferred in PATH."""
    env = dict(base_env)
    python_bin = resolve_agent_python_bin()
    python_path = Path(python_bin)

    # Prefer selected interpreter's venv bin when available.
    # For backend/.venv/bin/python this makes `python` in bash scripts
    # also resolve to the same venv.
    if python_path.parent.name == "bin" and (python_path.parent.parent / "pyvenv.cfg").exists():
        venv_root = python_path.parent.parent
        env["VIRTUAL_ENV"] = str(venv_root)
        old_path = env.get("PATH", "")
        env["PATH"] = f"{python_path.parent}{os.pathsep}{old_path}" if old_path else str(python_path.parent)

    if home is not None:
        env["HOME"] = str(home)

    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env
