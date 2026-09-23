import asyncio
import glob
import os
import pickle
import shutil
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.downloader import Downloader
from app.exceptions import ProcessInterrupted
from app.settings import config
from app.utils import ACTION_BACK, choice_menu, resolve_ffmpeg_path

DOWNLOAD_DIR = config["client"]["download_dir"]


def verify_prerequisites() -> bool:
    """Verify that external dependencies (FFmpeg) are available before executing downloads."""
    ffmpeg_cmd = config.get("client", {}).get("ffmpeg_path", "ffmpeg")
    resolved_ffmpeg = resolve_ffmpeg_path(ffmpeg_cmd)

    if not shutil.which(resolved_ffmpeg) and not os.path.exists(resolved_ffmpeg):
        print(f"Error: FFmpeg was not found on your system (checked: '{ffmpeg_cmd}').")
        print("FFmpeg is required to merge and remux downloaded HLS streams into an MP4 file.")
        print("\nHow to install FFmpeg:")
        print("  Windows:")
        print("    Option 1: winget install Gyan.FFmpeg")
        print("    Option 2: Place ffmpeg.exe in the same folder as this application")
        print("    Option 3: Specify 'ffmpeg_path' in config.yml (under client:)")
        print("  Linux:")
        print("    sudo apt-get install ffmpeg (or distribution package manager)")
        return False

    return True


check_prerequisites = verify_prerequisites


def save_session_state(downloader: "Downloader"):
    """Persist downloader state to a .session file for resuming interrupted downloads."""
    client = downloader.client
    downloader.client = None
    session_file_path = f"{downloader.output_video_file}.session"

    with open(session_file_path, "wb") as file_stream:
        pickle.dump(downloader, file_stream)

    downloader.client = client


save_session = save_session_state


def find_saved_sessions(download_directory: str) -> list[str]:
    """Search for existing .session files in the download directory."""
    return glob.glob(f"{download_directory}/**/*.session", recursive=True)


def load_saved_session(session_path: str) -> Downloader | None:
    """Load and unpickle a saved downloader session."""
    try:
        with open(session_path, "rb") as file_stream:
            downloader: Downloader = pickle.load(file_stream)
            return downloader
    except (pickle.UnpicklingError, OSError, EOFError, AttributeError) as exc:
        print(f"Failed to open selected session '{session_path}': {exc}")
        return None


async def run_app():
    """Main application lifecycle orchestrating session resumption, selection, and downloading."""
    if not verify_prerequisites():
        return

    saved_sessions = find_saved_sessions(DOWNLOAD_DIR)
    active_downloader: Downloader | None = None
    resume = False

    if saved_sessions:
        resume_prompt = input("Detected previous run(s), resume? [Y/n] ").strip().lower()
        if resume_prompt != "n":
            selected_session = choice_menu(
                saved_sessions,
                title="Choose session to resume",
                extra_options=[("[Start new download]", ACTION_BACK)],
                allow_back=False,
            )

            if selected_session == ACTION_BACK:
                resume = False
            elif selected_session is None:
                print("Cancelled, closing...")
                return
            else:
                active_downloader = load_saved_session(selected_session)
                if active_downloader is None:
                    return
                resume = True

    if active_downloader is None:
        active_downloader = Downloader()

    active_downloader.initialize()

    if not resume:
        try:
            await active_downloader.choose_item()
        except (KeyboardInterrupt, ProcessInterrupted):
            print("Cancelled, closing...")
            return

        save_session_state(active_downloader)

    try:
        await active_downloader.start_session(resume=resume)
        await active_downloader.download_subtitles()
        await active_downloader.download_files()
    except (KeyboardInterrupt, ProcessInterrupted):
        print("Interrupted, closing...")
    finally:
        active_downloader.report_stop()
        print("Finished")


if __name__ == "__main__":
    try:
        asyncio.run(run_app())
    except KeyboardInterrupt:
        pass
