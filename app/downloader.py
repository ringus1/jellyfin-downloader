import aiohttp
import asyncio
import backoff
import hashlib
import m3u8
import os
import socket
import subprocess
import uuid

from .exceptions import ProcessInterrupted
from .settings import config
from .utils import (
    ACTION_BACK,
    ACTION_EXIT,
    ACTION_NONE,
    ACTION_SEARCH_AGAIN,
    human_readable_to_bytes,
    item_by_id,
    prompt_choice_menu,
    resolve_ffmpeg_path,
    sanitize_path_component,
)
from .version import __version__
from contextlib import suppress
from datetime import datetime
from enum import StrEnum
from jellyfin_apiclient_python import JellyfinClient
from tqdm import tqdm
from urllib.parse import parse_qsl, urlparse

APP_NAME = "JellyfinDownloader"
USER = config["authentication"]["username"]
PASS = config["authentication"]["pass"]
SERVER_HOST = config["server"]["url"]
CONNECTIONS = config["client"]["connections"]
DUMP_EVERY = config["client"]["buffersize"]
TIMEOUT_CONFIG = aiohttp.client.ClientTimeout(total=180, connect=30, sock_connect=30, sock_read=180)
KEEP_PARTIALS = config["client"]["keep_partials"]
DOWNLOAD_DIR = config["client"]["download_dir"]


class DownloadWizardStep(StrEnum):
    """Enumeration of distinct steps in the interactive download wizard."""

    CATEGORY = "category"
    SEARCH = "search"
    ITEM = "item"
    SEASON = "season"
    EPISODE = "episode"
    SOURCE = "source"
    AUDIO = "audio"
    SUBTITLES = "subtitles"
    BITRATE = "bitrate"
    CONFIRM = "confirm"


def extract_item_display_name(item: dict) -> str:
    """Extract display name with production year from a Jellyfin item dictionary."""
    item_name = item.get("Name", "Unknown")
    production_year = item.get("ProductionYear", "Unknown")
    return f"{item_name} [{production_year}]"


def build_episode_filename(episode: dict) -> str:
    """Format episode filename with SxxExx convention."""
    season_number = str(episode.get("ParentIndexNumber", 0)).zfill(2)
    episode_number = str(episode.get("IndexNumber", 0)).zfill(2)
    episode_title = episode.get("Name", "")
    return f"S{season_number}E{episode_number} {episode_title}".strip()


def determine_previous_step(
    current_step: str,
    category: str | None = None,
    subtitle_streams: list | None = None,
    audio_streams: list | None = None,
    media_sources: list | None = None,
) -> DownloadWizardStep:
    """Determine the previous navigation step in the download wizard."""
    subtitle_streams = subtitle_streams or []
    audio_streams = audio_streams or []
    media_sources = media_sources or []

    match current_step:
        case DownloadWizardStep.CONFIRM:
            return DownloadWizardStep.BITRATE

        case DownloadWizardStep.BITRATE:
            if subtitle_streams:
                return DownloadWizardStep.SUBTITLES
            if len(audio_streams) > 1:
                return DownloadWizardStep.AUDIO
            if len(media_sources) > 1:
                return DownloadWizardStep.SOURCE
            return DownloadWizardStep.EPISODE if category == "Series" else DownloadWizardStep.ITEM

        case DownloadWizardStep.SUBTITLES:
            if len(audio_streams) > 1:
                return DownloadWizardStep.AUDIO
            if len(media_sources) > 1:
                return DownloadWizardStep.SOURCE
            return DownloadWizardStep.EPISODE if category == "Series" else DownloadWizardStep.ITEM

        case DownloadWizardStep.AUDIO:
            if len(media_sources) > 1:
                return DownloadWizardStep.SOURCE
            return DownloadWizardStep.EPISODE if category == "Series" else DownloadWizardStep.ITEM

        case DownloadWizardStep.SOURCE:
            return DownloadWizardStep.EPISODE if category == "Series" else DownloadWizardStep.ITEM

        case DownloadWizardStep.EPISODE:
            return DownloadWizardStep.SEASON

        case DownloadWizardStep.SEASON:
            return DownloadWizardStep.ITEM

        case DownloadWizardStep.ITEM:
            return DownloadWizardStep.SEARCH

        case _:
            return DownloadWizardStep.CATEGORY


def determine_next_step_after_source(
    audio_streams: list | None = None,
    subtitle_streams: list | None = None,
) -> DownloadWizardStep:
    """Determine the next step after a media source is selected."""
    audio_streams = audio_streams or []
    subtitle_streams = subtitle_streams or []

    if len(audio_streams) > 1:
        return DownloadWizardStep.AUDIO
    if subtitle_streams:
        return DownloadWizardStep.SUBTITLES
    return DownloadWizardStep.BITRATE


def backoff_msg(details):
    _args = details["args"]
    _filename = _args[1].split("/")[-1].split("?")[0]


class Downloader:
    def __init__(self) -> None:
        self.client = None
        self.item = None
        self.profile = None
        self.info = None
        self.base_url = None
        self.subtitle_url = None
        self.transcode_url = None
        self.m3u8_obj = None
        self.started_at = None
        self.parallel = CONNECTIONS
        self.source_config = {}

        self.download_path = DOWNLOAD_DIR
        self.output_filename = None

        self.partials_path = os.path.join(self.download_path, "partials")

    @property
    def output_video_file(self) -> str:
        return os.path.join(self.download_path, f"{self.output_filename}.mp4")

    @property
    def output_subtitle_file(self) -> str:
        return os.path.join(self.download_path, f"{self.output_filename}.srt")

    @property
    def status_file(self) -> str:
        return os.path.join(self.download_path, f"{self.output_filename}.status")

    @classmethod
    def get_profile(
        cls,
        video_bitrate: int,
        is_remote: bool = False,
        force_transcode: bool = True,
        h265: bool = False,
    ):
        transcode_codecs = "h264,mpeg4,mpeg2video"
        if h265:
            transcode_codecs = "h265,hevc," + transcode_codecs
        audio_transcode_codecs = "aac,mp3,ac3,eac3,mp2,opus,flac,vorbis"
        profile = {
            "Name": "jellyfin-downloader",
            "MaxStreamingBitrate": video_bitrate,
            "MaxStaticBitrate": video_bitrate,
            "MusicStreamingTranscodingBitrate": 1920000,
            "TimelineOffsetSeconds": 5,
            "TranscodingProfiles": [
                {"Type": "Audio"},
                {
                    "Container": "mp4",
                    "Type": "Video",
                    "AudioCodec": "aac,mp3,ac3,eac3,mp2,opus,flac",
                    "VideoCodec": "av1,hevc,h264",
                    "Context": "Streaming",
                    "Protocol": "hls",
                    "MaxAudioChannels": "2",
                    "MinSegments": "1",
                    "BreakOnNonKeyFrames": True,
                },
                {
                    "Container": "ts",
                    "Type": "Video",
                    "Protocol": "hls",
                    "AudioCodec": audio_transcode_codecs,
                    "VideoCodec": transcode_codecs,
                    "MaxAudioChannels": "2",
                },
                {"Container": "jpeg", "Type": "Photo"},
            ],
            "DirectPlayProfiles": [{"Type": "Video"}, {"Type": "Audio"}, {"Type": "Photo"}],
            "ResponseProfiles": [{"Type": "Video", "Container": "m4v", "MimeType": "video/mp4"}],
            "ContainerProfiles": [],
            "CodecProfiles": [],
            "SubtitleProfiles": [
                {"Format": "srt", "Method": "External"},
                {"Format": "srt", "Method": "Embed"},
                {"Format": "ass", "Method": "External"},
                {"Format": "ass", "Method": "Embed"},
                {"Format": "sub", "Method": "Embed"},
                {"Format": "sub", "Method": "External"},
                {"Format": "ssa", "Method": "Embed"},
                {"Format": "ssa", "Method": "External"},
                {"Format": "smi", "Method": "Embed"},
                {"Format": "smi", "Method": "External"},
                {"Format": "pgssub", "Method": "Embed"},
                {"Format": "dvdsub", "Method": "Embed"},
                {"Format": "dvbsub", "Method": "Embed"},
                {"Format": "pgs", "Method": "Embed"},
            ],
        }
        if force_transcode:
            profile["DirectPlayProfiles"] = []
        return profile

    def get_playdata(self, *, nowplaying=False, update=False):
        pd = {
            "AudioStreamIndex": 1,
            "BufferedRanges": [{"start": 0, "end": 400000000000}],
            "CanSeek": False,
            "IsMuted": False,
            "IsPaused": False,
            "ItemId": self.item["Id"],
            "MaxStreamingBitrate": self.profile["MaxStreamingBitrate"],
            "MediaSourceId": self.info["MediaSources"][0]["Id"],
            "PlayMethod": "Transcode",
            "PlaySessionId": self.info["PlaySessionId"],
            "PlaybackRate": 10,
            "PlaybackStartTimeTicks": 10000 * int(self.started_at.timestamp()),
            "PlaylistItemId": "playlistItem0",
            "PositionTicks": 0,
            "RepeatMode": "RepeatNone",
            "ShuffledMode": "Sorted",
            "SubtitleStreamIndex": -1,
            "VolumeLevel": 0,
        }
        if nowplaying:
            pd["NowPlayingQueue"] = [{"Id": self.item["Id"], "PlaylistItemId": "playlistItem0"}]
        if update:
            pd["EventName"] = "timeupdate"
        return pd

    def initialize(self):
        os.makedirs(self.partials_path, exist_ok=True)

        client = JellyfinClient()
        client.config.app(
            APP_NAME,
            __version__,
            socket.gethostname(),
            hashlib.md5(str(uuid.getnode()).encode()).hexdigest(),
        )
        client.config.data["auth.ssl"] = True

        client.auth.connect_to_address(SERVER_HOST)
        client.auth.login(SERVER_HOST, USER, PASS)

        credentials = client.auth.credentials.get_credentials()
        server = credentials["Servers"][0]
        server["username"] = USER
        client.authenticate({"Servers": [server]}, discover=False)
        self.client = client

    def prompt_category_step(self) -> str:
        """Prompt user for media category (Movies or Series)."""
        categories = ["Movies", "Series"]
        category_choice = prompt_choice_menu(
            categories,
            title="Choose category",
            extra_options=[("[Exit]", ACTION_EXIT)],
        )
        if category_choice in (None, ACTION_EXIT):
            raise ProcessInterrupted("Cancelled by user")

        return category_choice

    def fetch_and_prompt_search_step(self, category: str) -> tuple[str | None, list[dict] | None]:
        """Prompt user for search term and fetch matching items from Jellyfin."""
        print(f"\nCategory: {category}")
        try:
            term_input = input("Provide search term (leave empty or 'b' to go back): ").strip()
        except (KeyboardInterrupt, EOFError) as exc:
            raise ProcessInterrupted("Cancelled by user") from exc

        if term_input.lower() in ("", "b", "back"):
            return ACTION_BACK, None

        try:
            search_response = self.client.jellyfin.search_media_items(
                term=term_input, media=category
            )
            items = search_response.get("Items", []) if isinstance(search_response, dict) else []
        except Exception as search_exc:
            print(f"Search failed: {search_exc}")
            return None, None

        if not isinstance(items, list) or not items:
            print(f"No items matched '{term_input}'. Please try again.")
            return None, None

        return term_input, items

    def prompt_item_step(self, items: list[dict], category: str) -> tuple[str | None, dict | None]:
        """Prompt user to select a movie or series item from search results."""
        item_choice = prompt_choice_menu(
            items,
            name=extract_item_display_name,
            title=f"Choose {category.lower()[:-1]}",
            extra_options=[
                ("[<- Search again]", ACTION_SEARCH_AGAIN),
                ("[<- Back to category]", ACTION_BACK),
            ],
        )
        if item_choice is None:
            raise ProcessInterrupted("Cancelled by user")

        if item_choice in (ACTION_SEARCH_AGAIN, ACTION_BACK):
            return item_choice, None

        return None, item_choice

    def fetch_and_prompt_season_step(self, series_item_id: str) -> tuple[str | None, dict | None]:
        """Fetch and prompt user to select a season for the chosen series."""
        seasons_data = self.client.jellyfin.get_seasons(series_item_id)
        seasons = seasons_data.get("Items", []) if isinstance(seasons_data, dict) else []

        if not isinstance(seasons, list) or not seasons:
            print("No seasons found for this series.")
            return ACTION_BACK, None

        season_choice = prompt_choice_menu(
            seasons,
            name=lambda s: s.get("Name", "Unknown season"),
            title="Choose season",
            allow_back=True,
            back_label="[<- Back to series]",
        )
        if season_choice is None:
            raise ProcessInterrupted("Cancelled by user")

        if season_choice == ACTION_BACK:
            return ACTION_BACK, None

        return None, season_choice

    def fetch_and_prompt_episode_step(
        self, series_item_id: str, season_id: str
    ) -> tuple[str | None, dict | None, dict | None]:
        """Fetch and prompt user to select an episode for the chosen season."""
        episodes_data = self.client.jellyfin.get_season(series_item_id, season_id)
        episodes = episodes_data.get("Items", []) if isinstance(episodes_data, dict) else []

        if not isinstance(episodes, list) or not episodes:
            print("No episodes found in this season.")
            return ACTION_BACK, None, None

        episode_choice = prompt_choice_menu(
            episodes,
            name=build_episode_filename,
            title="Choose episode",
            allow_back=True,
            back_label="[<- Back to seasons]",
        )
        if episode_choice is None:
            raise ProcessInterrupted("Cancelled by user")

        if episode_choice == ACTION_BACK:
            return ACTION_BACK, None, None

        episode_info = self.client.jellyfin.get_item(episode_choice["Id"])
        return None, episode_choice, episode_info

    def prompt_source_step(self, media_sources: list[dict]) -> tuple[str | None, dict | None]:
        """Prompt user to choose between multiple media source releases."""
        source_choice = prompt_choice_menu(
            media_sources,
            name=lambda s: s.get("Name", "Default"),
            title="Choose version",
            allow_back=True,
            back_label="[<- Back]",
        )
        if source_choice is None:
            raise ProcessInterrupted("Cancelled by user")

        if source_choice == ACTION_BACK:
            return ACTION_BACK, None

        return None, source_choice

    def prompt_audio_step(self, audio_streams: list[dict]) -> tuple[str | None, int | None]:
        """Prompt user to choose an audio track."""
        audio_choice = prompt_choice_menu(
            audio_streams,
            name=lambda s: f"[{s.get('Language', 'und')}] {s.get('DisplayTitle', 'Audio')}",
            title="Choose audio",
            allow_back=True,
            back_label="[<- Back]",
        )
        if audio_choice is None:
            raise ProcessInterrupted("Cancelled by user")

        if audio_choice == ACTION_BACK:
            return ACTION_BACK, None

        return None, audio_choice["Index"]

    def prompt_subtitle_step(self, subtitle_streams: list[dict]) -> tuple[str | None, int | None]:
        """Prompt user to choose a subtitle track or skip subtitles."""
        subtitle_choice = prompt_choice_menu(
            subtitle_streams,
            name=lambda s: f"[{s.get('Language', 'und')}] {s.get('DisplayTitle', 'Subtitle')}",
            title="Pick subtitles",
            allow_back=True,
            back_label="[<- Back]",
            extra_options=[("[None / No subtitles]", ACTION_NONE)],
        )
        if subtitle_choice is None:
            raise ProcessInterrupted("Cancelled by user")

        if subtitle_choice == ACTION_BACK:
            return ACTION_BACK, None

        if subtitle_choice == ACTION_NONE:
            return None, None

        return None, subtitle_choice["Index"]

    def prompt_bitrate_step(self) -> tuple[str | None, int | None]:
        """Prompt user for target transcode bitrate in bytes."""
        try:
            bitrate_input = input("Provide bitrate [K/M] (default: 8M, 'b' to go back): ").strip()
        except (KeyboardInterrupt, EOFError) as exc:
            raise ProcessInterrupted("Cancelled by user") from exc

        if bitrate_input.lower() in ("b", "back"):
            return ACTION_BACK, None

        if not bitrate_input:
            bitrate_input = "8M"

        if not bitrate_input.upper().endswith(("K", "M")):
            bitrate_input += "K"

        try:
            bitrate_bytes = human_readable_to_bytes(bitrate_input)
            return None, bitrate_bytes
        except ValueError:
            print("Invalid bitrate format. Example formats: 4000K, 8M")
            return None, None

    def prompt_confirmation_step(
        self,
        category: str,
        selected_item: dict,
        season: dict | None,
        episode: dict | None,
        bitrate: int,
        source: dict,
    ) -> tuple[str | None, str, str, float]:
        """Display target file path and estimated size, and request confirmation."""
        source_bitrate = source.get("Bitrate") or bitrate
        source_size = source.get("Size") or 0

        if source_bitrate and source_size:
            expected_size_mb = round(
                (
                    source_size
                    * min(self.profile["MaxStreamingBitrate"], source_bitrate)
                    / source_bitrate
                )
                / (1024 * 1024),
                2,
            )
        else:
            expected_size_mb = 0.0

        if category == "Series" and season and episode:
            series_folder = sanitize_path_component(extract_item_display_name(selected_item))
            season_folder = sanitize_path_component(season.get("Name", "Season"))
            episode_file = sanitize_path_component(build_episode_filename(episode))
            target_directory = os.path.join(DOWNLOAD_DIR, category, series_folder, season_folder)
            target_filename = episode_file
        else:
            item_file = sanitize_path_component(extract_item_display_name(selected_item))
            target_directory = os.path.join(DOWNLOAD_DIR, category)
            target_filename = item_file

        print(f"\nTarget path: {os.path.join(target_directory, f'{target_filename}.mp4')}")
        print(f"Estimated size: {expected_size_mb} MB")

        try:
            proceed = (
                input("Proceed with download? [Y/n/b] (Y: Yes, n: Abort, b: Go back): ")
                .strip()
                .lower()
            )
        except (KeyboardInterrupt, EOFError) as exc:
            raise ProcessInterrupted("Cancelled by user") from exc

        if proceed in ("b", "back"):
            return ACTION_BACK, target_directory, target_filename, expected_size_mb

        if proceed == "n":
            raise ProcessInterrupted("Cancelled by user")

        return None, target_directory, target_filename, expected_size_mb

    async def choose_item(self):
        """Interactive download wizard guiding user through item, media, and quality selection."""
        step = DownloadWizardStep.CATEGORY
        category: str | None = None
        items: list[dict] = []
        selected_item: dict | None = None
        iteminfo: dict | None = None
        season: dict | None = None
        episode: dict | None = None
        episode_info: dict | None = None
        media_sources: list[dict] = []
        source: dict | None = None
        audio_streams: list[dict] = []
        aid: int | None = None
        subtitle_streams: list[dict] = []
        sid: int | None = None
        bitrate: int | None = None

        while True:
            match step:
                case DownloadWizardStep.CATEGORY:
                    category = self.prompt_category_step()
                    step = DownloadWizardStep.SEARCH

                case DownloadWizardStep.SEARCH:
                    action, search_results = self.fetch_and_prompt_search_step(category)
                    if action == ACTION_BACK:
                        step = DownloadWizardStep.CATEGORY
                    elif search_results:
                        items = search_results
                        step = DownloadWizardStep.ITEM

                case DownloadWizardStep.ITEM:
                    action, chosen_item = self.prompt_item_step(items, category)
                    if action == ACTION_SEARCH_AGAIN:
                        step = DownloadWizardStep.SEARCH
                    elif action == ACTION_BACK:
                        step = DownloadWizardStep.CATEGORY
                    elif chosen_item:
                        selected_item = chosen_item
                        iteminfo = self.client.jellyfin.get_item(selected_item["Id"])
                        if category == "Series":
                            step = DownloadWizardStep.SEASON
                        else:
                            media_sources = iteminfo.get("MediaSources", [])
                            if not media_sources:
                                print("No media sources found for this item.")
                                step = DownloadWizardStep.ITEM
                                continue

                            source = media_sources[0]
                            audio_streams = [
                                s
                                for s in source.get("MediaStreams", [])
                                if s.get("Type") == "Audio"
                            ]
                            subtitle_streams = [
                                s
                                for s in source.get("MediaStreams", [])
                                if s.get("Type") == "Subtitle"
                            ]
                            aid = audio_streams[0]["Index"] if audio_streams else None
                            sid = None

                            if len(media_sources) > 1:
                                step = DownloadWizardStep.SOURCE
                            else:
                                step = determine_next_step_after_source(
                                    audio_streams, subtitle_streams
                                )

                case DownloadWizardStep.SEASON:
                    action, chosen_season = self.fetch_and_prompt_season_step(iteminfo["Id"])
                    if action == ACTION_BACK:
                        step = DownloadWizardStep.ITEM
                    elif chosen_season:
                        season = chosen_season
                        step = DownloadWizardStep.EPISODE

                case DownloadWizardStep.EPISODE:
                    action, chosen_ep, ep_info = self.fetch_and_prompt_episode_step(
                        iteminfo["Id"], season["Id"]
                    )
                    if action == ACTION_BACK:
                        step = DownloadWizardStep.SEASON
                    elif chosen_ep:
                        episode = chosen_ep
                        episode_info = ep_info
                        media_sources = episode_info.get("MediaSources", [])
                        if not media_sources:
                            print("No media sources found for this episode.")
                            step = DownloadWizardStep.EPISODE
                            continue

                        source = media_sources[0]
                        audio_streams = [
                            s for s in source.get("MediaStreams", []) if s.get("Type") == "Audio"
                        ]
                        subtitle_streams = [
                            s for s in source.get("MediaStreams", []) if s.get("Type") == "Subtitle"
                        ]
                        aid = audio_streams[0]["Index"] if audio_streams else None
                        sid = None

                        if len(media_sources) > 1:
                            step = DownloadWizardStep.SOURCE
                        else:
                            step = determine_next_step_after_source(audio_streams, subtitle_streams)

                case DownloadWizardStep.SOURCE:
                    action, chosen_source = self.prompt_source_step(media_sources)
                    if action == ACTION_BACK:
                        step = determine_previous_step(
                            DownloadWizardStep.SOURCE,
                            category,
                            subtitle_streams,
                            audio_streams,
                            media_sources,
                        )
                    elif chosen_source:
                        source = chosen_source
                        audio_streams = [
                            s for s in source.get("MediaStreams", []) if s.get("Type") == "Audio"
                        ]
                        subtitle_streams = [
                            s for s in source.get("MediaStreams", []) if s.get("Type") == "Subtitle"
                        ]
                        aid = audio_streams[0]["Index"] if audio_streams else None
                        sid = None
                        step = determine_next_step_after_source(audio_streams, subtitle_streams)

                case DownloadWizardStep.AUDIO:
                    action, chosen_aid = self.prompt_audio_step(audio_streams)
                    if action == ACTION_BACK:
                        step = determine_previous_step(
                            DownloadWizardStep.AUDIO,
                            category,
                            subtitle_streams,
                            audio_streams,
                            media_sources,
                        )
                    else:
                        aid = chosen_aid
                        step = (
                            DownloadWizardStep.SUBTITLES
                            if subtitle_streams
                            else DownloadWizardStep.BITRATE
                        )

                case DownloadWizardStep.SUBTITLES:
                    action, chosen_sid = self.prompt_subtitle_step(subtitle_streams)
                    if action == ACTION_BACK:
                        step = determine_previous_step(
                            DownloadWizardStep.SUBTITLES,
                            category,
                            subtitle_streams,
                            audio_streams,
                            media_sources,
                        )
                    else:
                        sid = chosen_sid
                        step = DownloadWizardStep.BITRATE

                case DownloadWizardStep.BITRATE:
                    action, chosen_bitrate = self.prompt_bitrate_step()
                    if action == ACTION_BACK:
                        step = determine_previous_step(
                            DownloadWizardStep.BITRATE,
                            category,
                            subtitle_streams,
                            audio_streams,
                            media_sources,
                        )
                    elif chosen_bitrate is not None:
                        bitrate = chosen_bitrate
                        self.profile = self.get_profile(
                            video_bitrate=bitrate, h265=config["client"]["prefer_h265"]
                        )
                        self.source_config = {
                            "source": source,
                            "aid": aid,
                            "sid": sid,
                        }
                        step = DownloadWizardStep.CONFIRM

                case DownloadWizardStep.CONFIRM:
                    action, target_dir, target_file, size_mb = self.prompt_confirmation_step(
                        category=category,
                        selected_item=selected_item,
                        season=season,
                        episode=episode,
                        bitrate=bitrate,
                        source=source,
                    )
                    if action == ACTION_BACK:
                        step = determine_previous_step(
                            DownloadWizardStep.CONFIRM,
                            category,
                            subtitle_streams,
                            audio_streams,
                            media_sources,
                        )
                        continue

                    self.expected_size_mb = size_mb
                    self.item = selected_item
                    if category == "Series":
                        self.iteminfo = episode_info
                        self.download_path = target_dir
                        self.output_filename = target_file
                        self.info = episode
                    else:
                        self.iteminfo = iteminfo
                        self.download_path = target_dir
                        self.output_filename = target_file

                    os.makedirs(self.download_path, exist_ok=True)
                    break

    async def start_session(self, *, resume: bool = False):
        source = self.source_config["source"]
        aid = self.source_config["aid"]
        sid = self.source_config["sid"]

        self.info = self.client.jellyfin.get_play_info(
            source["Id"], self.profile, aid=aid, sid=sid, start_time_ticks=0
        )
        self.media_source = item_by_id(self.info["MediaSources"], source["Id"])

        if self.media_source.get("Bitrate"):
            self.expected_size_mb = round(
                (
                    self.media_source["Size"]
                    * min(self.profile["MaxStreamingBitrate"], self.media_source["Bitrate"])
                    / self.media_source["Bitrate"]
                )
                / (1024 * 1024),
                2,
            )

        if not resume:
            print(f"Estimating transcoded file to be around {self.expected_size_mb} MB.")

        if sid is not None:
            try:
                self.subtitle_url = (
                    SERVER_HOST + self.media_source["MediaStreams"][sid]["DeliveryUrl"]
                )
            except KeyError:
                pass

        self.transcode_url = SERVER_HOST + self.info["MediaSources"][0]["TranscodingUrl"]
        self.base_url = self.transcode_url.rsplit("/", maxsplit=1)[0]

        r, _ = await self.download(self.transcode_url)
        master_m3u8_obj = m3u8.loads(await r.text())

        r, _ = await self.download(self.base_url + "/" + master_m3u8_obj.playlists[0].uri)
        self.m3u8_obj = m3u8.loads(await r.text())

    def validate_transcode_url(self, url: str) -> bool:
        """Validate if a stored resume URL matches current transcode parameters."""
        ignored_params = {
            "deviceid",
            "playsessionid",
            "api_key",
            "apikey",
            "tag",
            "livestreamid",
            "transcodereasons",
        }

        def extract_critical_params(query_str: str) -> dict[str, str]:
            return {
                k.lower(): v
                for k, v in parse_qsl(query_str, keep_blank_values=True)
                if k.lower() not in ignored_params
            }

        try:
            if not self.transcode_url:
                return False
            current_parsed = urlparse(self.transcode_url)
            target_parsed = urlparse(url)

            if current_parsed.path != target_parsed.path:
                return False

            params_current = extract_critical_params(current_parsed.query)
            params_target = extract_critical_params(target_parsed.query)

            return params_current == params_target
        except Exception:
            return False

    def load_resume_state(self, *, resume: bool = False) -> int:
        """Attempt to load last downloaded chunk index from status file."""
        try:
            with open(self.status_file, encoding="utf-8") as file_stream:
                lines = [line.strip() for line in file_stream if line.strip()]
            if len(lines) < 2:
                return 0
            transcode_url, index_line = lines[0], lines[1]
        except (FileNotFoundError, OSError):
            return 0

        if self.validate_transcode_url(transcode_url):
            if not resume:
                confirm = (
                    input("There is an incomplete session for this item, resume? [Y/n] ")
                    .strip()
                    .lower()
                )
                if confirm == "n":
                    return 0

            try:
                idx = int(index_line)
                return max(0, idx)
            except ValueError:
                return 0

        print(
            "Notice: Stored transcode parameters do not match current session. Starting fresh download."
        )
        return 0

    def save_resume_state(self, current_idx: int):
        """Save current transcode URL and chunk index to status file."""
        with open(self.status_file, "w", encoding="utf-8") as file_stream:
            file_stream.write(f"{self.transcode_url}\n{current_idx}")

    def remux_and_cleanup_download(self):
        """Remux downloaded HLS streams into an MP4 container and clean up temporary files."""
        part_file_path = f"{self.output_video_file}.part"
        configured_ffmpeg = config.get("client", {}).get("ffmpeg_path", "ffmpeg")
        ffmpeg_cmd = resolve_ffmpeg_path(configured_ffmpeg)

        commands = [ffmpeg_cmd, "-i", part_file_path, "-c", "copy", self.output_video_file]
        print(f"Remuxing file with: {' '.join(commands)}")

        try:
            result = subprocess.run(commands, capture_output=True, text=True)
            if result.returncode != 0:
                print(
                    f"Failed to remux final file into mp4 (exit code {result.returncode}). Error:\n{result.stderr}"
                )
                return

            with suppress(FileNotFoundError):
                os.remove(part_file_path)
            with suppress(FileNotFoundError):
                os.remove(self.status_file)
            with suppress(FileNotFoundError):
                os.remove(f"{self.output_video_file}.session")
        except (subprocess.SubprocessError, OSError) as exc:
            print(f"Failed to remux final file into mp4. See error:\n{exc}")

    async def download_subtitles(self):
        """Download subtitle file if available and persist it using UTF-8."""
        if not self.subtitle_url:
            return

        response, _ = await self.download(self.subtitle_url)
        subtitle_content = await response.text()
        self.save_file_content(None, subtitle_content, filepath=self.output_subtitle_file)

    async def download_files(self, *, resume: bool = False):
        """Execute parallel chunk download and assemble output file."""
        self.started_at = datetime.utcnow()

        try:
            init_file = self.base_url + "/" + self.m3u8_obj.segment_map[0].uri
        except (AttributeError, IndexError):
            init_file = None

        init_buffer = b""
        files = [self.base_url + "/" + uri for uri in self.m3u8_obj.files]
        part_file_path = f"{self.output_video_file}.part"

        print("Starting session")
        if os.path.exists(self.output_video_file):
            confirm = input("File already exists, overwrite? [y/N] ")
            if confirm != "y":
                return

        self.client.jellyfin.session_playing(data=self.get_playdata(nowplaying=True))

        current_idx = self.load_resume_state(resume=resume)
        all_files = len(files)
        expected_size = self.expected_size_mb
        initial_size = 0

        if current_idx:
            if not os.path.exists(part_file_path) or os.path.getsize(part_file_path) == 0:
                print(
                    "Notice: Partial download file missing or empty. Restarting download from beginning."
                )
                current_idx = 0
                with suppress(FileNotFoundError):
                    os.remove(part_file_path)
            else:
                initial_size = round(os.path.getsize(part_file_path) / (1024 * 1024), 2)
                print(
                    f"Resuming download from segment {current_idx}/{all_files} ({initial_size} MB downloaded)."
                )
        else:
            with suppress(FileNotFoundError):
                os.remove(part_file_path)

        self.save_resume_state(current_idx)

        if expected_size and initial_size > expected_size:
            expected_size = initial_size

        if current_idx >= all_files:
            print(f"All {all_files} segments already downloaded. Proceeding to remux.")
        else:
            bar_fmt = (
                "{percentage:3.0f}%|{bar}| {n:.2f}/{total_fmt} MB [{elapsed}<{remaining}, {rate_fmt}{postfix}]"
                if expected_size > 0
                else "{n:.2f} MB [{elapsed}, {rate_fmt}{postfix}]"
            )
            with tqdm(
                total=expected_size,
                unit="MB",
                initial=initial_size,
                bar_format=bar_fmt,
            ) as pbar:

                def pbar_update(buffer: bytes):
                    delta = len(buffer) / (1024 * 1024)
                    if pbar.total is not None and (pbar.n + delta > pbar.total):
                        pbar.total = round(pbar.n + delta, 2)
                    pbar.update(delta)

                if init_file:
                    async with aiohttp.ClientSession(
                        raise_for_status=True, timeout=TIMEOUT_CONFIG
                    ) as session:
                        _, init_buffer = await self.download(init_file, session)

                async with aiohttp.ClientSession(
                    raise_for_status=True, timeout=TIMEOUT_CONFIG
                ) as session:
                    _, bigbuffer = await self.download(files[current_idx], session)
                    current_idx += 1
                bigbuffer = init_buffer + bigbuffer

                async with aiohttp.ClientSession(
                    headers={"X-Buffer-Only": "true"},
                    timeout=TIMEOUT_CONFIG,
                    raise_for_status=True,
                ) as session:
                    while current_idx < all_files:
                        buffers = await asyncio.gather(
                            *[
                                asyncio.create_task(self.download(files[idx], session, idx=idx))
                                for idx in range(
                                    current_idx, min(current_idx + self.parallel, all_files)
                                )
                            ]
                        )
                        current_idx += self.parallel

                        buffers.sort(key=lambda i: i[0])
                        for _, _, buffer in buffers:
                            bigbuffer += init_buffer + buffer

                        if len(bigbuffer) > DUMP_EVERY:
                            with open(part_file_path, "ab") as f:
                                f.write(bigbuffer)
                            self.save_resume_state(min(current_idx, all_files))
                            pbar_update(bigbuffer)
                            bigbuffer = b""

                        self.report_progress()

                    if bigbuffer:
                        with open(part_file_path, "ab") as f:
                            f.write(bigbuffer)
                        self.save_resume_state(min(current_idx, all_files))
                        pbar_update(bigbuffer)
                        bigbuffer = b""

        self.remux_and_cleanup_download()

    def report_progress(self):
        self.client.jellyfin.session_progress(data=self.get_playdata(update=True))

    def report_stop(self):
        """Report session stop to Jellyfin server."""
        if self.client and self.info:
            print("Reporting finish")
            try:
                self.client.jellyfin.session_stop(data=self.get_playdata(nowplaying=True))
            except (aiohttp.ClientError, OSError) as exc:
                print(f"Warning: Failed to report stop to Jellyfin server: {exc}")

    def save_file_content(
        self,
        url: str | None,
        data: bytes | str,
        dir: str | None = None,
        filepath: str | None = None,
    ):
        """Save text or binary content to disk with proper encoding."""
        if not filepath:
            filename = sanitize_path_component(url.split("/")[-1].split("?")[0])
            filepath = os.path.join(dir, filename)

        if isinstance(data, str):
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(data)
        else:
            with open(filepath, "wb") as f:
                f.write(data)

    @backoff.on_exception(
        backoff.expo,
        (aiohttp.ClientError, aiohttp.client.ClientConnectionError),
        on_backoff=backoff_msg,
        max_time=60,
        max_tries=7,
    )
    async def download(
        self, url: str, session: aiohttp.ClientSession | None = None, *, idx: int | None = None
    ):
        async def _inner(session: aiohttp.ClientSession):
            async with session.get(url) as response:
                data = await response.read()
                if KEEP_PARTIALS:
                    self.save_file_content(url, data, self.partials_path)
                if idx:
                    return idx, response, data
                return response, data

        if session is None:
            async with aiohttp.ClientSession(
                raise_for_status=True, timeout=TIMEOUT_CONFIG
            ) as session:
                return await _inner(session)
        else:
            return await _inner(session)
