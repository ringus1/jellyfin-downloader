import asyncio
import pickle
import os
import glob
from simple_term_menu import TerminalMenu

from app.settings import config
from app.downloader import Downloader

DOWNLOAD_DIR = config["client"]["download_dir"]


def save_session(downloader: "Downloader"):
    client = downloader.client
    downloader.client = None
    with open(f"{downloader.output_video_file}.session", 'wb') as file:
        pickle.dump(downloader, file)
    downloader.client = client


async def run_app():
    old_sessions = glob.glob(f"{DOWNLOAD_DIR}/**/*.session", recursive=True)

    d = None
    resume = False
    if old_sessions:
        resume = input("Detected previous run(s), resume? [Y/n] ") != "n"
        if resume:
            session = old_sessions[TerminalMenu([session for session in old_sessions]).show()]
            try:
                with open(session, "rb") as f:
                    d = pickle.load(f)
            except Exception as e:
                print(f"Failed to open selected session: {e}")
                return

    if d is None:
        d = Downloader()

    d.initialize()

    if not resume:
        try:
            await d.choose_item()
        except (KeyboardInterrupt, ):
            print("Interrupted, closing...")
            return
        save_session(d)

    try:
        await d.download_subtitles()
        await d.download_files()
        os.remove(f"{d.output_video_file}.session")
    except KeyboardInterrupt:
        print("Interrupted, closing...")
    finally:
        d.report_stop()
        print("Finished")


if __name__ == "__main__":
    asyncio.run(run_app())
