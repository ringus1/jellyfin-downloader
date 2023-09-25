# JellyfinDownloader

JellyfinDownloader is a Python script designed to simplify the process of downloading transcoded media files from a Jellyfin server. It utilizes asyncio to enable parallel downloads using multiple connections, supports resumable sessions, and provides an interactive menu for selecting titles to download. Please note that this tool currently supports **only transcoded files**, and it is recommended to have the `ffmpeg` binary available on your system for seamless merging of HLS streams.

## Motivation

Most clients, including web client are typically only capable of downloading untranscoded files and lack support for downloading external subtitles. This script addresses both needs for whenever you would like to keep 4K videos on the server, but occassionally need smaller files when having slower bandwidth or mobile network with transfer limitations.

## Features

- Efficiently download transcoded media files from Jellyfin.
- Supports resumable download sessions for convenience.
- Interactive menu for selecting specific titles to download.
- Seamless merging of downloaded HLS streams with the `ffmpeg` binary.

## Prerequisites

Before using JellyfinDownloader, ensure that you have the following prerequisites installed on your system:

- Python 3.x (https://www.python.org/downloads/)
- [Poetry](https://python-poetry.org/docs/#installation) for dependency management.
- `ffmpeg` (https://ffmpeg.org/download.html)

## Installation

1. Clone this repository to your local machine:

   ```shell
   git clone https://github.com/ringus1/jellyfin-downloader.git
   ```

2. Change to the project directory:

   ```shell
   cd jellyfin-downloader
   ```

3. Install the required Python dependencies using Poetry:

   ```shell
   poetry install
   ```

## Usage

1. Create configuration file `config.yml`, when running the first time (see [config.example.yml](config.example.yml))

2. Run the script:

   ```shell
   poetry run python jellyfin_downloader.py
   ```

3. Select the titles you want to download from the interactive menu.

4. The script will start downloading the selected titles using multiple connections for faster downloads.

## Resuming Downloads

If a download session is interrupted, you can resume it by re-running the script. The script will detect the existing download session and offer to resume it.

## Disclaimer

JellyfinDownloader is provided as-is and without any warranty. Use it responsibly and ensure that you have the legal rights to download the media files you select.

## License

This project is licensed under the [MIT License](LICENSE). Feel free to modify and distribute it as needed, but please provide attribution to the original project.

## Contributing

If you find issues or have suggestions for improvements, please feel free to open an issue or create a pull request. Your contributions are welcome!

---

Enjoy using JellyfinDownloader to enhance your media downloading capabilities from your Jellyfin server! If you have any questions or encounter any issues, please don't hesitate to reach out for assistance.
