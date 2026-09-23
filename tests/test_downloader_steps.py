from app import downloader
from app.downloader import DownloadWizardStep


class TestWizardStepNavigation:
    """Verifies that navigation transitions allow bidirectional flow through wizard steps."""

    def test_transitions_back_from_confirm_to_bitrate(self):
        prev = downloader.determine_previous_step(DownloadWizardStep.CONFIRM)

        assert prev == DownloadWizardStep.BITRATE

    def test_transitions_back_to_subtitles_when_subtitles_exist(self):
        prev = downloader.determine_previous_step(
            DownloadWizardStep.BITRATE,
            subtitle_streams=[{"Index": 3}],
        )

        assert prev == DownloadWizardStep.SUBTITLES

    def test_transitions_back_to_audio_when_multiple_audio_tracks_exist_and_no_subtitles(self):
        prev = downloader.determine_previous_step(
            DownloadWizardStep.BITRATE,
            subtitle_streams=[],
            audio_streams=[{"Index": 1}, {"Index": 2}],
        )

        assert prev == DownloadWizardStep.AUDIO

    def test_transitions_back_to_episode_for_series(self):
        prev = downloader.determine_previous_step(
            DownloadWizardStep.BITRATE,
            category="Series",
            subtitle_streams=[],
            audio_streams=[{"Index": 1}],
            media_sources=[{"Id": "src1"}],
        )

        assert prev == DownloadWizardStep.EPISODE

    def test_transitions_back_to_item_for_movies(self):
        prev = downloader.determine_previous_step(
            DownloadWizardStep.BITRATE,
            category="Movies",
            subtitle_streams=[],
            audio_streams=[{"Index": 1}],
            media_sources=[{"Id": "src1"}],
        )

        assert prev == DownloadWizardStep.ITEM

    def test_determines_next_step_after_source_selection(self):
        # Multiple audio streams -> audio step
        assert (
            downloader.determine_next_step_after_source(
                audio_streams=[{"Index": 1}, {"Index": 2}],
                subtitle_streams=[],
            )
            == DownloadWizardStep.AUDIO
        )

        # Single audio, has subtitles -> subtitles step
        assert (
            downloader.determine_next_step_after_source(
                audio_streams=[{"Index": 1}],
                subtitle_streams=[{"Index": 3}],
            )
            == DownloadWizardStep.SUBTITLES
        )

        # Single audio, no subtitles -> bitrate step
        assert (
            downloader.determine_next_step_after_source(
                audio_streams=[{"Index": 1}],
                subtitle_streams=[],
            )
            == DownloadWizardStep.BITRATE
        )


class TestItemFormatting:
    """Verifies that item names and episode file names are formatted cleanly."""

    def test_formats_item_display_name_with_year(self):
        item = {"Name": "Dune", "ProductionYear": 2021}

        formatted = downloader.extract_item_display_name(item)

        assert formatted == "Dune [2021]"

    def test_formats_episode_filename_with_zero_padded_season_and_episode(self):
        episode = {"ParentIndexNumber": 3, "IndexNumber": 8, "Name": "Odcinek 8"}

        formatted = downloader.build_episode_filename(episode)

        assert formatted == "S03E08 Odcinek 8"
