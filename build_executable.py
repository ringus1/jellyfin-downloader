"""Local build script for JellyfinDownloader standalone executable.

Usage:
    poetry run python build_executable.py
"""

import os
import re
import shutil
import subprocess
import sys


def resolve_build_version() -> str:
    """Determine the release version for this build from env or git tag."""
    # 1. Custom explicit env var
    explicit = os.environ.get("JELLYFIN_DOWNLOADER_VERSION", "").strip()
    if explicit:
        return re.sub(r"^v\.?", "", explicit)

    # 2. GitHub Actions ref name (e.g. 'v1.2.3' from tag push)
    github_ref = os.environ.get("GITHUB_REF_NAME", "").strip()
    if github_ref and (github_ref.startswith("v") or re.match(r"^\d+\.\d+", github_ref)):
        return re.sub(r"^v\.?", "", github_ref)

    # 3. Local git tag
    try:
        res = subprocess.run(
            ["git", "describe", "--tags"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return re.sub(r"^v\.?", "", res.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass

    # 4. Fallback to app/version.py or pyproject.toml
    version_file = os.path.join(os.path.dirname(__file__), "app", "version.py")
    if os.path.exists(version_file):
        with open(version_file, encoding="utf-8") as f:
            for line in f:
                if line.startswith("__version__ = "):
                    match = re.search(r'"([^"]+)"', line)
                    if match:
                        return match.group(1)
    return "0.0.0"


def update_version_file(version: str) -> None:
    """Write the target version into app/version.py so PyInstaller freezes it."""
    version_file = os.path.join(os.path.dirname(__file__), "app", "version.py")
    if not os.path.exists(version_file):
        return

    with open(version_file, encoding="utf-8") as f:
        content = f.read()

    updated = re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', content, count=1)
    with open(version_file, "w", encoding="utf-8") as f:
        f.write(updated)
    print(f"Set application version in app/version.py to: {version}")


def ensure_pyinstaller_available():
    """Verify that PyInstaller is installed or install it into the current Python environment."""
    try:
        import PyInstaller

        print(f"PyInstaller version {PyInstaller.__version__} detected.")
    except ImportError:
        print("PyInstaller not found. Installing into virtual environment...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def stage_ffmpeg_binary_if_available():
    """Copy system FFmpeg adjacent to spec file if not already present."""
    ffmpeg_target = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    if not os.path.exists(ffmpeg_target):
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            print(f"Found system FFmpeg at: {system_ffmpeg}")
            print(
                f"Copying {system_ffmpeg} to current directory to bundle it into the standalone binary..."
            )
            shutil.copy2(system_ffmpeg, ffmpeg_target)
        else:
            print("Note: No local or system ffmpeg found in PATH.")
            print("The built executable will rely on external FFmpeg at runtime.")


def build_standalone_executable():
    """Compile JellyfinDownloader into a standalone single-file binary using PyInstaller."""
    print("=== JellyfinDownloader Build Script ===")

    target_version = resolve_build_version()
    update_version_file(target_version)

    ensure_pyinstaller_available()
    stage_ffmpeg_binary_if_available()

    spec_file = "jellyfin-downloader.spec"
    if not os.path.exists(spec_file):
        print(f"Error: Spec file '{spec_file}' not found.")
        sys.exit(1)

    print(f"\nRunning PyInstaller build for version {target_version}...")
    build_command = [sys.executable, "-m", "PyInstaller", spec_file, "--noconfirm"]
    build_result = subprocess.run(build_command)

    if build_result.returncode == 0:
        exe_ext = ".exe" if sys.platform == "win32" else ""
        output_binary_path = os.path.join("dist", f"jellyfin-downloader{exe_ext}")
        print("\n==========================================")
        print("BUILD SUCCEEDED!")
        print(
            f"Standalone executable created at: {os.path.abspath(output_binary_path)} (v{target_version})"
        )
        print("==========================================")
    else:
        print(f"\nBuild failed with exit code {build_result.returncode}.")
        sys.exit(build_result.returncode)


if __name__ == "__main__":
    build_standalone_executable()
