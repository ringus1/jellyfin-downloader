from app import utils


class TestFilenameSanitization:
    """Verifies that filename sanitization handles special characters safely across operating systems."""

    def test_replaces_colons_and_slashes_with_spaced_hyphen(self):
        input_title = "Special Ops: Lioness/Sezon 3"
        sanitized_title = utils.sanitize_path_component(input_title)

        assert sanitized_title == "Special Ops - Lioness - Sezon 3"

    def test_strips_prohibited_characters_on_windows_and_linux(self):
        input_title = 'Movie <Title>: "The Return" [2024] ? * |'
        sanitized_title = utils.sanitize_path_component(input_title)

        assert "<" not in sanitized_title
        assert ">" not in sanitized_title
        assert '"' not in sanitized_title
        assert "?" not in sanitized_title
        assert "*" not in sanitized_title
        assert "|" not in sanitized_title
        assert "Movie" in sanitized_title
        assert "The Return" in sanitized_title

    def test_handles_empty_or_none_inputs_gracefully(self):
        assert utils.sanitize_path_component("") == ""
        assert utils.sanitize_path_component(None) == ""

    def test_preserves_unicode_musical_and_accented_characters(self):
        unicode_title = "Intro ♪ - Zażółć gęślą jaźń"
        sanitized_title = utils.sanitize_path_component(unicode_title)

        assert "♪" in sanitized_title
        assert "Zażółć gęślą jaźń" in sanitized_title
