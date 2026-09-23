import inquirer

from app import utils
from pytest_mock import MockerFixture


class TestChoiceMenuSelection:
    """Verifies that terminal choice menus properly build labels, options, and return selected values."""

    def test_returns_selected_item_value(self, mocker: MockerFixture):
        items = [{"Name": "First Movie"}, {"Name": "Second Movie"}]
        mocker.patch.object(
            inquirer,
            "prompt",
            autospec=True,
            return_value={"choice": "First Movie"},
        )

        chosen = utils.prompt_choice_menu(items, name=lambda x: x["Name"])

        assert chosen == items[0]

    def test_handles_back_action_and_extra_options(self, mocker: MockerFixture):
        items = ["Option A", "Option B"]
        mocker.patch.object(
            inquirer,
            "prompt",
            autospec=True,
            return_value={"choice": "[<- Back]"},
        )

        chosen = utils.prompt_choice_menu(
            items,
            allow_back=True,
            back_label="[<- Back]",
            extra_options=[("[None]", utils.ACTION_NONE)],
        )

        assert chosen == utils.ACTION_BACK

    def test_disambiguates_duplicate_labels_cleanly(self):
        items = ["Action", "Action", "Action"]

        mapping, labels, first_label = utils.build_choice_labels_and_mapping(items)

        assert labels == ["Action", "Action (2)", "Action (3)"]
        assert mapping["Action"] == "Action"
        assert mapping["Action (2)"] == "Action"
        assert mapping["Action (3)"] == "Action"
        assert first_label == "Action"

    def test_handles_keyboard_interrupt_gracefully(self, mocker: MockerFixture):
        items = ["Item 1"]
        mocker.patch.object(
            inquirer,
            "prompt",
            autospec=True,
            side_effect=KeyboardInterrupt(),
        )

        chosen = utils.prompt_choice_menu(items)

        assert chosen is None
