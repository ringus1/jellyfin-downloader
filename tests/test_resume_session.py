from app.downloader import Downloader
from pytest_mock import MockerFixture


class TestTranscodeUrlValidation:
    """Verifies that resume URL validation correctly handles ephemeral parameters and reordering."""

    def test_matches_identical_parameters_with_different_ephemeral_tokens_and_order(self):
        downloader = Downloader()
        downloader.transcode_url = (
            "https://server.test/videos/1234/master.m3u8?"
            "MediaSourceId=src1&VideoCodec=h264&AudioCodec=aac&VideoBitrate=3000000&"
            "PlaySessionId=session_A&ApiKey=token_A&DeviceId=dev_A&Tag=tag_A"
        )

        stored_url = (
            "https://server.test/videos/1234/master.m3u8?"
            "ApiKey=token_B&AudioCodec=aac&Tag=tag_B&VideoBitrate=3000000&"
            "DeviceId=dev_B&PlaySessionId=session_B&MediaSourceId=src1&VideoCodec=h264"
        )

        assert downloader.validate_transcode_url(stored_url) is True

    def test_rejects_url_with_different_video_quality_or_stream(self):
        downloader = Downloader()
        downloader.transcode_url = (
            "https://server.test/videos/1234/master.m3u8?"
            "MediaSourceId=src1&VideoCodec=h264&VideoBitrate=5000000"
        )

        # Different bitrate
        stored_url = (
            "https://server.test/videos/1234/master.m3u8?"
            "MediaSourceId=src1&VideoCodec=h264&VideoBitrate=2000000"
        )

        assert downloader.validate_transcode_url(stored_url) is False

    def test_rejects_url_with_different_video_item_path(self):
        downloader = Downloader()
        downloader.transcode_url = "https://server.test/videos/1234/master.m3u8?MediaSourceId=src1"
        stored_url = "https://server.test/videos/5678/master.m3u8?MediaSourceId=src1"

        assert downloader.validate_transcode_url(stored_url) is False

    def test_returns_false_when_current_transcode_url_is_none(self):
        downloader = Downloader()
        downloader.transcode_url = None

        assert (
            downloader.validate_transcode_url("https://server.test/videos/1234/master.m3u8")
            is False
        )


class TestLoadResumeState:
    """Verifies reading saved progress index from status file."""

    def test_returns_index_without_prompting_when_resuming_existing_session(
        self, tmp_path, mocker: MockerFixture
    ):
        downloader = Downloader()
        downloader.transcode_url = "https://server.test/videos/item1/master.m3u8?MediaSourceId=src1"
        status_file = tmp_path / "test.status"
        status_file.write_text(f"{downloader.transcode_url}\n15\n", encoding="utf-8")
        mocker.patch.object(Downloader, "status_file", str(status_file), create=True)
        mock_input = mocker.patch("builtins.input")

        idx = downloader.load_resume_state(resume=True)

        assert idx == 15
        mock_input.assert_not_called()

    def test_prompts_user_when_resume_flag_is_false(self, tmp_path, mocker: MockerFixture):
        downloader = Downloader()
        downloader.transcode_url = "https://server.test/videos/item1/master.m3u8?MediaSourceId=src1"
        status_file = tmp_path / "test.status"
        status_file.write_text(f"{downloader.transcode_url}\n8\n", encoding="utf-8")
        mocker.patch.object(Downloader, "status_file", str(status_file), create=True)
        mocker.patch("builtins.input", return_value="y")

        idx = downloader.load_resume_state(resume=False)

        assert idx == 8

    def test_returns_zero_when_user_declines_resume(self, tmp_path, mocker: MockerFixture):
        downloader = Downloader()
        downloader.transcode_url = "https://server.test/videos/item1/master.m3u8?MediaSourceId=src1"
        status_file = tmp_path / "test.status"
        status_file.write_text(f"{downloader.transcode_url}\n8\n", encoding="utf-8")
        mocker.patch.object(Downloader, "status_file", str(status_file), create=True)
        mocker.patch("builtins.input", return_value="n")

        idx = downloader.load_resume_state(resume=False)

        assert idx == 0

    def test_returns_zero_when_status_file_is_missing(self, tmp_path, mocker: MockerFixture):
        downloader = Downloader()
        downloader.transcode_url = "https://server.test/videos/item1/master.m3u8?MediaSourceId=src1"
        missing_status_file = tmp_path / "nonexistent.status"
        mocker.patch.object(Downloader, "status_file", str(missing_status_file), create=True)

        idx = downloader.load_resume_state(resume=True)

        assert idx == 0

    def test_returns_zero_when_transcode_parameters_mismatch(self, tmp_path, mocker: MockerFixture):
        downloader = Downloader()
        downloader.transcode_url = "https://server.test/videos/item1/master.m3u8?VideoBitrate=4000"
        status_file = tmp_path / "test.status"
        status_file.write_text(
            "https://server.test/videos/item1/master.m3u8?VideoBitrate=1000\n10\n",
            encoding="utf-8",
        )
        mocker.patch.object(Downloader, "status_file", str(status_file), create=True)

        idx = downloader.load_resume_state(resume=True)

        assert idx == 0
