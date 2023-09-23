import asyncio
import pickle
import os
from app.downloader import Downloader


async def run_app():
    old_config = "download_config.pkl"

    d = None
    resume = False
    if os.path.exists(old_config):
        resume = input("Detected previous run, resume? [Y/n] ") != "n"
        if resume:
            try:
                with open(old_config, "rb") as f:
                    d = pickle.load(f)
            except Exception as e:
                resume = False
                print(e)
    if d is None:
        d = Downloader()

    d.initialize()

    if not resume:
        try:
            await d.choose_item()
        except (KeyboardInterrupt, ):
            print("Interrupted, closing...")
            return
        with open(old_config, 'wb') as file:
            pickle.dump(d, file)

    try:
        await d.download_subtitles()
        await d.download_files()
        os.remove(old_config)
    except KeyboardInterrupt:
        print("Interrupted, closing...")
    finally:
        d.report_stop()
        print("Finished")


if __name__ == "__main__":
    asyncio.run(run_app())
