import os
import sys

from app import utils
from pytest_mock import MockerFixture


class TestFFmpegBinaryResolution:
    """Verifies that FFmpeg is correctly located in packaged, portable, and system environments."""

    def test_prefers_bundled_binary_when_frozen_with_meipass(self, mocker: MockerFixture):
        mocker.patch.object(sys, "frozen", True, create=True)
        mocker.patch.object(sys, "_MEIPASS", "C:\\temp_meipass", create=True)

        expected_binary = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        expected_path = os.path.join("C:\\temp_meipass", expected_binary)

        def mock_exists(path: str) -> bool:
            return path == expected_path

        mocker.patch.object(os.path, "exists", autospec=True, side_effect=mock_exists)

        resolved = utils.resolve_ffmpeg_path("custom_ffmpeg")

        assert resolved == expected_path

    def test_prefers_adjacent_binary_when_frozen_without_meipass(self, mocker: MockerFixture):
        mocker.patch.object(sys, "frozen", True, create=True)
        if hasattr(sys, "_MEIPASS"):
            mocker.delattr(sys, "_MEIPASS")
        mocker.patch.object(sys, "executable", "C:\\app_dir\\jellyfin-downloader.exe")

        expected_binary = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        expected_path = os.path.join("C:\\app_dir", expected_binary)

        def mock_exists(path: str) -> bool:
            return path == expected_path

        mocker.patch.object(os.path, "exists", autospec=True, side_effect=mock_exists)

        resolved = utils.resolve_ffmpeg_path("custom_ffmpeg")

        assert resolved == expected_path

    def test_falls_back_to_configured_command_in_development(self, mocker: MockerFixture):
        if hasattr(sys, "frozen"):
            mocker.delattr(sys, "frozen")

        resolved = utils.resolve_ffmpeg_path("custom_ffmpeg")

        assert resolved == "custom_ffmpeg"
