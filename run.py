import asyncio
from app.downloader import Downloader


async def run_app():
    d = Downloader()
    d.initialize()

    try:
        await d.choose_item()
    except (KeyboardInterrupt, ):
        print("Interrupted, closing...")
        return

    try:
        await d.download_subtitles()
        await d.download_files()
    except KeyboardInterrupt:
        print("Interrupted, closing...")
    finally:
        d.report_stop()
        print("Finished")


if __name__ == "__main__":
    asyncio.run(run_app())
