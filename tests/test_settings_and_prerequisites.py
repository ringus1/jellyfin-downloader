import jellyfin_downloader
import os
import shutil
import sys

from app import settings
from pytest_mock import MockerFixture


class TestConfigLocation:
    """Verifies that config.yml is located properly in CWD and next to frozen executable."""

    def test_finds_config_in_current_working_directory(self, mocker: MockerFixture):
        mocker.patch.object(
            os.path, "exists", autospec=True, side_effect=lambda p: p == "config.yml"
        )

        located = settings.locate_config_file()

        assert located == "config.yml"

    def test_finds_config_next_to_executable_when_frozen(self, mocker: MockerFixture):
        mocker.patch.object(sys, "frozen", True, create=True)
        mocker.patch.object(sys, "executable", "D:\\portable\\jellyfin-downloader.exe")

        expected_adjacent = os.path.join("D:\\portable", "config.yml")

        def mock_exists(p: str) -> bool:
            return p == expected_adjacent

        mocker.patch.object(os.path, "exists", autospec=True, side_effect=mock_exists)

        located = settings.locate_config_file()

        assert located == expected_adjacent


class TestPrerequisiteVerification:
    """Verifies that system prerequisites (FFmpeg) are validated correctly before execution."""

    def test_returns_true_when_ffmpeg_is_installed(self, mocker: MockerFixture):
        mocker.patch.object(shutil, "which", autospec=True, return_value="/usr/bin/ffmpeg")

        assert jellyfin_downloader.verify_prerequisites() is True

    def test_returns_false_when_ffmpeg_is_missing(self, mocker: MockerFixture):
        mocker.patch.object(shutil, "which", autospec=True, return_value=None)
        mocker.patch.object(os.path, "exists", autospec=True, return_value=False)

        assert jellyfin_downloader.verify_prerequisites() is False
