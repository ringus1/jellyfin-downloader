from jellyfin_apiclient_python import JellyfinClient
from typing import Optional
from datetime import datetime
from contextlib import suppress
from tqdm import tqdm
from simple_term_menu import TerminalMenu

import requests
import m3u8
import asyncio
import aiohttp
import backoff
import socket
import uuid
import hashlib
import os

from .settings import config
from .helpers import human_readable_to_bytes, item_by_id


APP_NAME = "JellyfinDownloader"
USER = config["authentication"]["username"]
PASS = config["authentication"]["pass"]
SERVER_HOST = config["server"]["url"]
CONNECTIONS = config["client"]["connections"]
DUMP_EVERY = config["client"]["buffersize"]
TIMEOUT_CONFIG = aiohttp.client.ClientTimeout(total=180, connect=30, sock_connect=30, sock_read=180)
KEEP_PARTIALS = config["client"]["keep_partials"]


def backoff_msg(details):
    args = details["args"]
    filename = args[2].split("/")[-1].split("?")[0]
    # print("Backing off {wait:0.1f} seconds after {tries} tries for file {filename}".format(
    #     wait=details["wait"], filename=filename, tries=details["tries"]))


class Downloader:
    def __init__(self) -> None:
        self.client = None
        self.item = None
        self.profile = None
        self.info = None
        self.base_url = None
        self.m3u8_obj = None
        self.started_at = None
        self.parallel = CONNECTIONS

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
        audio_transcode_codecs = "aac,mp3,ac3,opus,flac,vorbis"
        profile = {
            "Name": "jellyfin-downloader",
            "MaxStreamingBitrate": video_bitrate,
            "MaxStaticBitrate": video_bitrate,
            "MusicStreamingTranscodingBitrate": 1920000,
            "TimelineOffsetSeconds": 5,
            "TranscodingProfiles": [
                {"Type": "Audio"},
                {
                    "Container": "ts",
                    "Type": "Video",
                    "Protocol": "hls",
                    "AudioCodec": audio_transcode_codecs,
                    "VideoCodec": transcode_codecs,
                    "MaxAudioChannels": "6",
                },
                {"Container": "jpeg", "Type": "Photo"},
            ],
            "DirectPlayProfiles": [{"Type": "Video"}, {"Type": "Audio"}, {"Type": "Photo"}],
            "ResponseProfiles": [],
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

    def choose_item(self, category="Videos"):
        term = input("Provide search term: ")

        items = self.client.jellyfin.search_media_items(
            term=term, media=category)["Items"]
        if not items:
            print("Nothing matched your criteria")
            raise RuntimeError

        choice = TerminalMenu([f'{item["Name"]} [{item["ProductionYear"]}]' for item in items]).show()

        self.item = items[choice]
        self.iteminfo = self.client.jellyfin.get_item(self.item["Id"])

        source_id = 0
        sid = None
        aid = None
        if len(self.iteminfo['MediaSources']) > 1:
            source_id = TerminalMenu([source["Name"] for source in self.iteminfo['MediaSources']], title="Choose version").show()
        source = self.iteminfo["MediaSources"][source_id]
        audio_streams = [stream for stream in source["MediaStreams"] if stream["Type"] == "Audio"]
        if len(audio_streams) > 1:
            choice = TerminalMenu([f'[{source["Language"]}] {source["DisplayTitle"]}' for source in audio_streams], title="Choose audio").show()
            aid = audio_streams[choice]["Index"]
        subtitle_streams = [stream for stream in source["MediaStreams"] if stream["Type"] == "Subtitle"]
        if subtitle_streams:
            choice = TerminalMenu([f'[{source["Language"]}] {source["DisplayTitle"]}' for source in subtitle_streams], title="Pick subtitles").show()
            sid = subtitle_streams[choice]["Index"]

        bitrate = input("Provide bitrate [K/M]: ")
        if not bitrate.endswith(("K", "M")):
            bitrate += "K"
        bitrate = human_readable_to_bytes(bitrate)

        self.profile = self.get_profile(video_bitrate=bitrate, h265=config["client"]["prefer_h265"])
        self.info = self.client.jellyfin.get_play_info(
            source["Id"], self.profile, aid=aid, sid=sid, start_time_ticks=0)
        media_source = item_by_id(self.info['MediaSources'], source["Id"])

        self.subtitle_url = None
        if sid is not None:
            try:
                self.subtitle_url = SERVER_HOST + media_source['MediaStreams'][sid]['DeliveryUrl']
            except KeyError:
                pass

        m3u8_url = SERVER_HOST + self.info["MediaSources"][0]["TranscodingUrl"]

        # print(m3u8_url)

        r = requests.get(m3u8_url, timeout=10)
        r.raise_for_status()

        self.base_url = m3u8_url.rsplit("/", maxsplit=1)[0]
        master_m3u8_obj = m3u8.loads(r.content.decode("utf-8"))

        r = requests.get(self.base_url + "/" + master_m3u8_obj.playlists[0].uri, timeout=10)
        r.raise_for_status()
        self.m3u8_obj = m3u8.loads(r.content.decode("utf-8"))

    async def download_subtitles(self):
        if not self.subtitle_url:
            return

        async with aiohttp.ClientSession(
            raise_for_status=True,
            timeout=TIMEOUT_CONFIG
        ) as session:
            _, data = await self.download_async(session, self.subtitle_url)
        with open("final.PL.srt", "wb") as f:
            f.write(data)

    async def download_files(self, *, limit=None):
        self.started_at = datetime.utcnow()
        files = [self.base_url + "/" + uri for uri in self.m3u8_obj.files]

        print("Starting session")
        self.client.jellyfin.session_playing(data=self.get_playdata(nowplaying=True))

        with suppress(FileNotFoundError):
            os.unlink("final.mp4")

        async with aiohttp.ClientSession(
            raise_for_status=True,
            timeout=TIMEOUT_CONFIG
        ) as session:
            _, bigbuffer = await self.download_async(session, files[0])

        start_idx = 1
        all_files = len(files)
        if limit and limit < all_files:
            all_files = limit

        with tqdm(total=100) as pbar:
            async with aiohttp.ClientSession(
                headers={"X-Buffer-Only": "true"},
                timeout=TIMEOUT_CONFIG,
                raise_for_status=True
            ) as session:
                while start_idx < all_files:
                    buffers = await asyncio.gather(
                        *[asyncio.create_task(self.download_async(session, files[idx], idx=idx))
                        for idx in range(start_idx, start_idx + self.parallel)]
                    )

                    buffers.sort(key=lambda i: i[0])
                    for _, buffer in buffers:
                        bigbuffer += buffer
                    if len(bigbuffer) > DUMP_EVERY:
                        # print("Dumping...")
                        with open("final.mp4", "ab") as f:
                            f.write(bigbuffer)
                        bigbuffer = b''

                    self.report_progress()
                    start_idx += self.parallel
                    pbar.update(100 * self.parallel / all_files)

    def report_progress(self):
        # print("Progress update")
        self.client.jellyfin.session_progress(data=self.get_playdata(update=True))

    def report_stop(self):
        print("Reporting finish")
        self.client.jellyfin.session_stop(data=self.get_playdata(nowplaying=True))

    @backoff.on_exception(
        backoff.expo,
        (aiohttp.ClientError, aiohttp.client.ClientConnectionError),
        on_backoff=backoff_msg,
        max_time=60,
        max_tries=7)
    async def download_async(self, session: "aiohttp.ClientSession", url: str, *, idx=None):
        async with session.get(url) as response:
            data = await response.read()
            if KEEP_PARTIALS:
                with open(os.path.join("downloads", url.split("/")[-1].split("?")[0]), "wb") as f:
                    f.write(data)
            return idx, data
