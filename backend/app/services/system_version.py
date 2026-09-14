"""Answers QUALITY_OBSERVABILITY.md's previously-unanswerable audit question:
"¿qué versión del sistema generó este informe?" -- only possible now that the
project is a git repository (Fase 9). Resolution order:

1. SYSTEM_VERSION env var -- for containers built without a .git directory
   (the common case: most Dockerfiles don't COPY .git), set this at build
   time from CI (e.g. `--build-arg SYSTEM_VERSION=$(git rev-parse --short HEAD)`).
2. `git rev-parse --short HEAD` against the running checkout, if .git is present.
3. "unknown" -- never silently mislabel a report with the wrong version.
"""
import subprocess
from functools import lru_cache
from pathlib import Path

from app.config.settings import get_settings


@lru_cache
def get_system_version() -> str:
    settings = get_settings()
    if settings.system_version:
        return settings.system_version

    project_root = Path(__file__).resolve().parents[3]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            commit = result.stdout.strip()
            dirty = subprocess.run(
                ["git", "status", "--porcelain"], cwd=project_root, capture_output=True, text=True, timeout=5
            )
            suffix = "-dirty" if dirty.returncode == 0 and dirty.stdout.strip() else ""
            return f"{commit}{suffix}"
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"
