import asyncio
from app.downloader import Downloader


if __name__ == "__main__":
    d = Downloader()
    d.initialize()
    d.choose_item()
    try:
        asyncio.run(d.download_subtitles())
        asyncio.run(d.download_files())
    except KeyboardInterrupt:
        print("Interrupted, closing...")
    finally:
        d.report_stop()
        print("Finished")
