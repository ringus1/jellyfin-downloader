from jellyfin_apiclient_python import JellyfinClient
from datetime import datetime
from tqdm import tqdm
from urllib.parse import urlparse, urlunparse, parse_qsl
from typing import Optional, Union

import m3u8
import asyncio
import aiohttp
import backoff
import socket
import uuid
import hashlib
import os

from .settings import config
from .utils import human_readable_to_bytes, item_by_id, choice_menu


APP_NAME = "JellyfinDownloader"
USER = config["authentication"]["username"]
PASS = config["authentication"]["pass"]
SERVER_HOST = config["server"]["url"]
CONNECTIONS = config["client"]["connections"]
DUMP_EVERY = config["client"]["buffersize"]
TIMEOUT_CONFIG = aiohttp.client.ClientTimeout(total=180, connect=30, sock_connect=30, sock_read=180)
KEEP_PARTIALS = config["client"]["keep_partials"]
DOWNLOAD_DIR = config["client"]["download_dir"]


def backoff_msg(details):
    args = details["args"]
    filename = args[1].split("/")[-1].split("?")[0]
    # print("Backing off {wait:0.1f} seconds after {tries} tries for file {filename}".format(
    #     wait=details["wait"], filename=filename, tries=details["tries"]))


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

        self.download_path = DOWNLOAD_DIR
        self.output_filename = None

        self.partials_path = os.path.join(self.download_path, "partials")
        os.makedirs(self.partials_path, exist_ok=True)

    @property
    def output_video_file(self):
        return os.path.join(self.download_path, f"{self.output_filename}.mp4")

    @property
    def output_subtitle_file(self):
        return os.path.join(self.download_path, f"{self.output_filename}.srt")

    @property
    def status_file(self):
        return os.path.join(self.download_path, f"{self.output_filename}.status")

    @classmethod
    def get_profile(
        cls,
        video_bitrate: int,
        is_remote: bool = False,
        force_transcode: bool = True,
        h265: bool = False
    ):
        # if video_bitrate is None:
        #     if is_remote:
        #         video_bitrate = settings.remote_kbps
        #     else:
        #         video_bitrate = settings.local_kbps
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
            "ResponseProfiles": [
                {
                    "Type": "Video",
                    "Container": "m4v",
                    "MimeType": "video/mp4"
                }
            ],
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
                # Jellyfin currently refuses to serve these subtitle types as external.
                {"Format": "pgssub", "Method": "Embed"},
                # {
                #    "Format": "pgssub",
                #    "Method": "External"
                # },
                {"Format": "dvdsub", "Method": "Embed"},
                {"Format": "dvbsub", "Method": "Embed"},
                # {
                #    "Format": "dvdsub",
                #    "Method": "External"
                # },
                {"Format": "pgs", "Method": "Embed"},
                # {
                #    "Format": "pgs",
                #    "Method": "External"
                # }
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
            "VolumeLevel": 0
        }
        if nowplaying:
            pd["NowPlayingQueue"] = [{"Id": self.item["Id"], "PlaylistItemId": "playlistItem0"}]
        if update:
            pd["EventName"] = "timeupdate"
        return pd

    def initialize(self):
        client = JellyfinClient()
        client.config.app(
            APP_NAME,
            '0.0.1',
            socket.gethostname(),
            hashlib.md5(str(uuid.getnode()).encode()).hexdigest()
        )
        client.config.data["auth.ssl"] = True

        client.auth.connect_to_address(SERVER_HOST)
        client.auth.login(SERVER_HOST, USER, PASS)

        credentials = client.auth.credentials.get_credentials()
        server = credentials["Servers"][0]
        server["username"] = USER
        client.authenticate({"Servers": [server]}, discover=False)
        self.client = client

    async def choose_item(self):
        categories = ["Movies", "Series"]
        category = choice_menu(categories)

        term = input("Provide search term: ")

        items = self.client.jellyfin.search_media_items(
            term=term, media=category)["Items"]
        if not items:
            print("Nothing matched your criteria")
            raise RuntimeError

        def _get_item_name(item):
            production_year = item.get("ProductionYear", "Unknown")
            return f'{item["Name"]} [{production_year}]'

        self.item = choice_menu(items, _get_item_name)
        self.iteminfo = self.client.jellyfin.get_item(self.item["Id"])

        self.download_path = os.path.join(self.download_path, category)
        self.output_filename = _get_item_name(self.item)

        if category == "Series":
            seasons = self.client.jellyfin.get_seasons(self.iteminfo["Id"])
            season = choice_menu(seasons["Items"], lambda s: s["Name"], title="Choose season")

            episodes = self.client.jellyfin.get_season(self.iteminfo["Id"], season["Id"])
            episode = choice_menu(episodes["Items"], lambda s: s["Name"], title="Choose episode")
            self.iteminfo = self.client.jellyfin.get_item(episode["Id"])

            self.download_path = os.path.join(self.download_path, _get_item_name(self.item), season["Name"])
            self.output_filename = episode["Name"]
            self.info = episode

        os.makedirs(self.download_path, exist_ok=True)

        source = self.iteminfo["MediaSources"][0]
        sid = None
        aid = None
        if len(self.iteminfo['MediaSources']) > 1:
            source = choice_menu(self.iteminfo["MediaSources"], lambda s: s["Name"], title="Choose version")

        audio_streams = [stream for stream in source["MediaStreams"] if stream["Type"] == "Audio"]
        if len(audio_streams) > 1:
            audio_stream = choice_menu(audio_streams, lambda s: f'[{s.get("Language", "und")}] {s["DisplayTitle"]}', title="Choose audio")
            aid = audio_stream["Index"]
        subtitle_streams = [stream for stream in source["MediaStreams"] if stream["Type"] == "Subtitle"]
        if subtitle_streams:
            subtitle_stream = choice_menu(subtitle_streams, lambda s: f'[{s.get("Language", "und")}] {s["DisplayTitle"]}', title="Pick subtitles")
            sid = subtitle_stream["Index"]

        bitrate = input("Provide bitrate [K/M]: ")
        if not bitrate.endswith(("K", "M")):
            bitrate += "K"
        bitrate = human_readable_to_bytes(bitrate)

        self.profile = self.get_profile(video_bitrate=bitrate, h265=config["client"]["prefer_h265"])
        self.info = self.client.jellyfin.get_play_info(
            source["Id"], self.profile, aid=aid, sid=sid, start_time_ticks=0)
        self.media_source = item_by_id(self.info['MediaSources'], source["Id"])

        self.expected_size_mb = round((
            self.media_source["Size"] * min(
                self.profile['MaxStreamingBitrate'], self.media_source["Bitrate"]
            ) / self.media_source["Bitrate"]
        ) / (1024 * 1024), 2)
        proceed = input(f"Estimating transcoded file to be around {self.expected_size_mb} MB. Proceed? [Y/n] ")
        if proceed == "n":
            raise KeyboardInterrupt("Interrupting")

        if sid is not None:
            try:
                self.subtitle_url = SERVER_HOST + self.media_source['MediaStreams'][sid]['DeliveryUrl']
            except KeyError:
                pass

        self.transcode_url = SERVER_HOST + self.info["MediaSources"][0]["TranscodingUrl"]
        self.base_url = self.transcode_url.rsplit("/", maxsplit=1)[0]

        r, _ = await self.download(self.transcode_url)
        master_m3u8_obj = m3u8.loads(await r.text())

        r, _ = await self.download(self.base_url + "/" + master_m3u8_obj.playlists[0].uri)
        self.m3u8_obj = m3u8.loads(await r.text())

    def _validate_transcode_url(self, url) -> bool:
        ignored_params = ("DeviceId", "PlaySessionId", "api_key")
        def _filtered_params(query_params: bytes):
            return "&".join([
                f"{k}={v}"
                for k, v in parse_qsl(query_params)
                if k not in ignored_params
            ])

        def _unparse(p, query):
            return urlunparse([
                p.scheme, p.netloc, p.path,
                p.params, query, p.fragment])

        p_current = urlparse(self.transcode_url)
        p_current_query = _filtered_params(p_current.query)

        p_url = urlparse(url)
        p_url_query = _filtered_params(p_url.query)

        return _unparse(p_current, p_current_query) == _unparse(p_url, p_url_query)

    def _resume_download(self) -> int:
        try:
            with open(self.status_file, "r") as f:
                transcode_url, idx = f.readlines()
        except FileNotFoundError:
            return 0
        if self._validate_transcode_url(transcode_url):
            confirm = input("There is incomplete session for this item, resume? [Y/n]")
            if confirm == "n":
                return 0
            return int(idx)

    def _save_download_status(self, current_idx: int):
        with open(self.status_file, "w") as f:
            f.write(self.transcode_url + "\n" + str(current_idx))

    def _cleanup_tmps(self):
        os.rename(f"{self.output_video_file}.part", self.output_video_file)
        os.remove(self.status_file)

    async def download_subtitles(self):
        if not self.subtitle_url:
            return

        response, _ = await self.download(self.subtitle_url)
        self._save(None, await response.text(), filepath=self.output_subtitle_file)

    async def download_files(self):
        self.started_at = datetime.utcnow()

        try:
            init_file = self.base_url + "/" + self.m3u8_obj.segment_map[0].uri
        except (AttributeError, IndexError):
            init_file = None
        init_buffer = b''
        files = [self.base_url + "/" + uri for uri in self.m3u8_obj.files]
        part_file_path = f"{self.output_video_file}.part"

        print("Starting session")
        if os.path.exists(self.output_video_file):
            confirm = input("File already exists, overwrite? [y/N] ")
            if confirm != "y":
                return

        self.client.jellyfin.session_playing(data=self.get_playdata(nowplaying=True))

        current_idx = self._resume_download()
        self._save_download_status(current_idx)
        all_files = len(files)
        expected_size = self.expected_size_mb
        initial_size = 0

        if current_idx:
            initial_size = os.path.getsize(part_file_path) / (1024 * 1024)

        with tqdm(
            total=expected_size,
            unit="MB",
            initial=initial_size,
            # bar_format='{l_bar}{bar}| {n_fmt:0.2f}/{total_fmt:0.2f} [{elapsed}<{remaining}, {rate_fmt}{postfix}]'
        ) as pbar:
            def pbar_update(buffer: bytes):
                pbar.update(len(buffer) / (1024 * 1024))

            if init_file:
                async with aiohttp.ClientSession(
                    raise_for_status=True,
                    timeout=TIMEOUT_CONFIG
                ) as session:
                    _, init_buffer = await self.download(init_file, session)

            async with aiohttp.ClientSession(
                raise_for_status=True,
                timeout=TIMEOUT_CONFIG
            ) as session:
                _, bigbuffer = await self.download(files[current_idx], session)
                current_idx += 1
            bigbuffer = init_buffer + bigbuffer

            async with aiohttp.ClientSession(
                headers={"X-Buffer-Only": "true"},
                timeout=TIMEOUT_CONFIG,
                raise_for_status=True
            ) as session:
                while current_idx < all_files:
                    buffers = await asyncio.gather(
                        *[asyncio.create_task(self.download(files[idx], session, idx=idx))
                        for idx in range(
                            current_idx,
                            min(current_idx + self.parallel, all_files))]
                    )
                    current_idx += self.parallel

                    buffers.sort(key=lambda i: i[0])
                    for _, _, buffer in buffers:
                        bigbuffer += init_buffer + buffer

                    if len(bigbuffer) > DUMP_EVERY:
                        with open(part_file_path, "ab") as f:
                            f.write(bigbuffer)
                        self._save_download_status(current_idx)
                        pbar_update(bigbuffer)
                        bigbuffer = b''

                    self.report_progress()
        self._cleanup_tmps()

    def report_progress(self):
        # print("Progress update")
        self.client.jellyfin.session_progress(data=self.get_playdata(update=True))

    def report_stop(self):
        print("Reporting finish")
        self.client.jellyfin.session_stop(data=self.get_playdata(nowplaying=True))

    def _save(self, url: Optional[str], data: Union[bytes, str], dir: Optional[str] = None, filepath: Optional[str] = None):
        mode = "wb" if isinstance(data, bytes) else "w"
        if not filepath:
            filepath = os.path.join(dir, url.split("/")[-1].split("?")[0])
        with open(filepath, mode) as f:
            f.write(data)

    @backoff.on_exception(
        backoff.expo,
        (aiohttp.ClientError, aiohttp.client.ClientConnectionError),
        on_backoff=backoff_msg,
        max_time=60,
        max_tries=7)
    async def download(self, url: str, session: "aiohttp.ClientSession" = None, *, idx = None):
        async def _inner(session: "aiohttp.ClientSession"):
            async with session.get(url) as response:
                data = await response.read()
                if KEEP_PARTIALS:
                    self._save(url, data, self.partials_path)
                if idx:
                    return idx, response, data
                return response, data

        if session is None:
            async with aiohttp.ClientSession(
                raise_for_status=True,
                timeout=TIMEOUT_CONFIG
            ) as session:
                return await _inner(session)
        else:
            return await _inner(session)
