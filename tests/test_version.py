import os
import subprocess
import sys

from app.version import normalize_version, resolve_version
from pytest_mock import MockerFixture


class TestVersionNormalization:
    """Verifies that version tags from git or environment are normalized into valid semantic versions."""

    def test_strips_leading_v_from_tag(self):
        assert normalize_version("v1.2.3") == "1.2.3"

    def test_strips_leading_v_dot_from_tag(self):
        assert normalize_version("v.2.0.1") == "2.0.1"

    def test_preserves_clean_semver_without_prefix(self):
        assert normalize_version("0.1.0") == "0.1.0"

    def test_trims_whitespace_around_tag(self):
        assert normalize_version("   v1.0.5 \n") == "1.0.5"


class TestVersionResolution:
    """Verifies resolution precedence: explicit env var > GitHub ref tag > frozen static > git tag > default."""

    def test_prefers_explicit_env_override(self, mocker: MockerFixture):
        mocker.patch.dict(
            os.environ, {"JELLYFIN_DOWNLOADER_VERSION": "v3.0.0", "GITHUB_REF_NAME": "v2.0.0"}
        )

        resolved = resolve_version()

        assert resolved == "3.0.0"

    def test_uses_github_ref_name_when_set(self, mocker: MockerFixture):
        mocker.patch.dict(
            os.environ, {"JELLYFIN_DOWNLOADER_VERSION": "", "GITHUB_REF_NAME": "v1.5.0"}
        )

        resolved = resolve_version()

        assert resolved == "1.5.0"

    def test_uses_frozen_baked_version_without_querying_git(self, mocker: MockerFixture):
        mocker.patch.dict(os.environ, {"JELLYFIN_DOWNLOADER_VERSION": "", "GITHUB_REF_NAME": ""})
        mocker.patch.object(sys, "frozen", True, create=True)
        mock_run = mocker.patch("subprocess.run")

        resolved = resolve_version()

        mock_run.assert_not_called()
        assert isinstance(resolved, str)
        assert len(resolved) > 0

    def test_resolves_git_tag_in_development(self, mocker: MockerFixture):
        mocker.patch.dict(os.environ, {"JELLYFIN_DOWNLOADER_VERSION": "", "GITHUB_REF_NAME": ""})
        if hasattr(sys, "frozen"):
            mocker.delattr(sys, "frozen")

        mock_result = subprocess.CompletedProcess(
            args=["git", "describe", "--tags"], returncode=0, stdout="v2.1.4\n"
        )
        mocker.patch("subprocess.run", return_value=mock_result)

        resolved = resolve_version()

        assert resolved == "2.1.4"

    def test_falls_back_when_git_fails(self, mocker: MockerFixture):
        mocker.patch.dict(os.environ, {"JELLYFIN_DOWNLOADER_VERSION": "", "GITHUB_REF_NAME": ""})
        if hasattr(sys, "frozen"):
            mocker.delattr(sys, "frozen")

        mock_result = subprocess.CompletedProcess(
            args=["git", "describe", "--tags"],
            returncode=128,
            stdout="",
            stderr="fatal: not a git repo",
        )
        mocker.patch("subprocess.run", return_value=mock_result)

        resolved = resolve_version()

        assert resolved == "0.0.0"
