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


class TestConfigInitialization:
    """Verifies template generation and interactive setup when config.yml is absent."""

    def test_get_config_example_content_returns_template_when_files_absent(
        self, mocker: MockerFixture
    ):
        mocker.patch.object(os.path, "exists", return_value=False)
        content = settings.get_config_example_content()
        assert "server:" in content
        assert "http://localhost:8096" in content

    def test_generate_example_config_creates_file(self, tmp_path):
        target = tmp_path / "subdir" / "config.example.yml"
        assert not target.exists()

        result = settings.generate_example_config_file(str(target))

        assert result is True
        assert target.exists()
        assert "server:" in target.read_text(encoding="utf-8")

    def test_generate_example_config_preserves_existing_file(self, tmp_path):
        target = tmp_path / "config.example.yml"
        target.write_text("custom: content", encoding="utf-8")

        result = settings.generate_example_config_file(str(target))

        assert result is True
        assert target.read_text(encoding="utf-8") == "custom: content"

    def test_setup_interactive_configuration_writes_yaml(self, tmp_path, monkeypatch):
        target = tmp_path / "config.yml"
        inputs = iter(["http://jellyfin.local:8096", "alice", "my_downloads"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
        monkeypatch.setattr("getpass.getpass", lambda prompt="": "secretpass123")

        result = settings.setup_interactive_configuration(str(target))

        assert result is True
        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert "http://jellyfin.local:8096" in content
        assert "alice" in content
        assert "secretpass123" in content
        assert "my_downloads" in content
        assert "connections: 1" in content

    def test_load_and_validate_interactive_yes(self, tmp_path, mocker: MockerFixture, monkeypatch):
        config_path = str(tmp_path / "config.yml")
        mocker.patch.object(sys.stdin, "isatty", return_value=True)
        monkeypatch.setattr("builtins.input", lambda prompt="": "y")

        def fake_setup(target: str) -> bool:
            import yaml

            with open(target, "w", encoding="utf-8") as f:
                yaml.dump(
                    {
                        "server": {"url": "http://test:8096"},
                        "authentication": {"username": "u", "pass": "p"},
                        "client": {"buffersize": "10M"},
                    },
                    f,
                )
            return True

        mocker.patch.object(settings, "setup_interactive_configuration", side_effect=fake_setup)

        parsed = settings.load_and_validate_configuration(config_path)

        assert parsed["server"]["url"] == "http://test:8096"
        assert parsed["client"]["buffersize"] == 10 * 1024 * 1024
        assert parsed["client"]["connections"] == 1

    def test_load_and_validate_interactive_no_generates_template_and_exits(
        self, tmp_path, mocker: MockerFixture, monkeypatch
    ):
        import pytest

        config_path = str(tmp_path / "config.yml")
        example_path = tmp_path / "config.example.yml"
        mocker.patch.object(sys.stdin, "isatty", return_value=True)
        monkeypatch.setattr("builtins.input", lambda prompt="": "n")

        with pytest.raises(SystemExit) as exc_info:
            settings.load_and_validate_configuration(config_path)

        assert exc_info.value.code == 0
        assert example_path.exists()

    def test_load_and_validate_non_interactive_generates_template_and_exits(
        self, tmp_path, mocker: MockerFixture
    ):
        import pytest

        config_path = str(tmp_path / "config.yml")
        example_path = tmp_path / "config.example.yml"
        mocker.patch.object(sys.stdin, "isatty", return_value=False)

        with pytest.raises(SystemExit) as exc_info:
            settings.load_and_validate_configuration(config_path)

        assert exc_info.value.code == 1
        assert example_path.exists()
