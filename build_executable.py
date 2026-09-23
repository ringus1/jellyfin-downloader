"""Local build script for JellyfinDownloader standalone executable.

Usage:
    poetry run python build_executable.py
"""

import os
import shutil
import subprocess
import sys


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

    ensure_pyinstaller_available()
    stage_ffmpeg_binary_if_available()

    spec_file = "jellyfin-downloader.spec"
    if not os.path.exists(spec_file):
        print(f"Error: Spec file '{spec_file}' not found.")
        sys.exit(1)

    print("\nRunning PyInstaller build...")
    build_command = [sys.executable, "-m", "PyInstaller", spec_file, "--noconfirm"]
    build_result = subprocess.run(build_command)

    if build_result.returncode == 0:
        exe_ext = ".exe" if sys.platform == "win32" else ""
        output_binary_path = os.path.join("dist", f"jellyfin-downloader{exe_ext}")
        print("\n==========================================")
        print("BUILD SUCCEEDED!")
        print(f"Standalone executable created at: {os.path.abspath(output_binary_path)}")
        print("==========================================")
    else:
        print(f"\nBuild failed with exit code {build_result.returncode}.")
        sys.exit(build_result.returncode)


main = build_standalone_executable

if __name__ == "__main__":
    build_standalone_executable()
