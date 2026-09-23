import os
import re
import subprocess
import sys

__version__ = "0.0.0"


def normalize_version(raw_version: str) -> str:
    """Normalize a version string by stripping leading 'v' and extra spaces."""
    version = raw_version.strip()
    if version.startswith("v") or version.startswith("v."):
        version = re.sub(r"^v\.?", "", version)
    return version


def resolve_version() -> str:
    """Resolve current application version from environment, git tag, or static fallback."""
    # 1. Explicit override via custom environment variable
    explicit_version = os.environ.get("JELLYFIN_DOWNLOADER_VERSION", "").strip()
    if explicit_version:
        return normalize_version(explicit_version)

    # 2. GitHub Actions ref name (e.g. 'v1.2.3' on release tag pushes)
    github_ref = os.environ.get("GITHUB_REF_NAME", "").strip()
    if github_ref and (github_ref.startswith("v") or re.match(r"^\d+\.\d+", github_ref)):
        return normalize_version(github_ref)

    # 3. In frozen standalone binaries, use the baked-in static version
    if getattr(sys, "frozen", False):
        return __version__

    # 4. Attempt to resolve from git tag if available in development
    try:
        result = subprocess.run(
            ["git", "describe", "--tags"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            raw_git_tag = result.stdout.strip()
            return normalize_version(raw_git_tag)
    except (OSError, subprocess.SubprocessError):
        pass

    # 5. Default static version
    return __version__


__version__ = resolve_version()
