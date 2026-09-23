import inquirer
import os
import re
import sys

from collections.abc import Callable, Iterable
from pathvalidate import sanitize_filename
from typing import Any, TypeVar

T = TypeVar("T")

ACTION_BACK = "__ACTION_BACK__"
ACTION_NONE = "__ACTION_NONE__"
ACTION_SEARCH_AGAIN = "__ACTION_SEARCH_AGAIN__"
ACTION_EXIT = "__ACTION_EXIT__"


def resolve_ffmpeg_path(configured_cmd: str = "ffmpeg") -> str:
    """Resolve the executable path for FFmpeg.

    Checks the bundled PyInstaller directory (_MEIPASS), the directory
    adjacent to the executable, and falls back to the configured command or PATH.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundled_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        bundled_path = os.path.join(sys._MEIPASS, bundled_name)
        if os.path.exists(bundled_path):
            return bundled_path

    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        adjacent_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        adjacent_path = os.path.join(exe_dir, adjacent_name)
        if os.path.exists(adjacent_path):
            return adjacent_path

    return configured_cmd


get_ffmpeg_path = resolve_ffmpeg_path


def sanitize_path_component(name: str) -> str:
    """Sanitize a file or directory name component across platforms.

    Normalizes colons and slashes to ' - ' to prevent word collisions,
    then removes characters prohibited on target filesystems.
    """
    if not name:
        return ""

    normalized_name = re.sub(r"\s*[:/\\]\s*", " - ", str(name))
    return sanitize_filename(normalized_name, replacement_text="")


sanitize_name = sanitize_path_component


def build_choice_labels_and_mapping(
    items: Iterable[T],
    name_extractor: Callable[[T], str] = lambda item: str(item),
    allow_back: bool = False,
    back_label: str = "[<- Back]",
    extra_options: list[tuple[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[str], str | None]:
    """Build mapping of display labels to items, handling duplicates and action options."""
    choice_mapping: dict[str, Any] = {}
    choice_labels: list[str] = []

    if allow_back:
        choice_mapping[back_label] = ACTION_BACK
        choice_labels.append(back_label)

    if extra_options:
        for option_label, option_value in extra_options:
            choice_mapping[option_label] = option_value
            choice_labels.append(option_label)

    first_item_label: str | None = None
    for item in items:
        label = name_extractor(item)
        if label in choice_mapping:
            counter = 2
            while f"{label} ({counter})" in choice_mapping:
                counter += 1
            label = f"{label} ({counter})"

        choice_mapping[label] = item
        choice_labels.append(label)

        if first_item_label is None:
            first_item_label = label

    return choice_mapping, choice_labels, first_item_label


def determine_default_choice_label(
    choice_mapping: dict[str, Any],
    choice_labels: list[str],
    first_item_label: str | None,
    default: Any | None,
) -> str | None:
    """Determine which choice label should be selected by default."""
    if default is not None:
        for label, value in choice_mapping.items():
            if value == default:
                return label

    if first_item_label is not None:
        return first_item_label

    if choice_labels:
        return choice_labels[0]

    return None


def prompt_choice_menu(
    items: Iterable[T],
    name: Callable[[T], str] = lambda item: str(item),
    title: str = "",
    allow_back: bool = False,
    back_label: str = "[<- Back]",
    extra_options: list[tuple[str, Any]] | None = None,
    default: Any | None = None,
) -> Any | None:
    """Render an interactive terminal choice menu and return the selected item or action."""
    choice_mapping, choice_labels, first_item_label = build_choice_labels_and_mapping(
        items=items,
        name_extractor=name,
        allow_back=allow_back,
        back_label=back_label,
        extra_options=extra_options,
    )

    if not choice_labels:
        return None

    default_label = determine_default_choice_label(
        choice_mapping=choice_mapping,
        choice_labels=choice_labels,
        first_item_label=first_item_label,
        default=default,
    )

    questions = [
        inquirer.List(
            "choice",
            message=title,
            choices=choice_labels,
            default=default_label,
            carousel=True,
        )
    ]

    try:
        answers = inquirer.prompt(questions)
    except KeyboardInterrupt:
        return None

    if answers:
        return choice_mapping.get(answers["choice"])

    return None


choice_menu = prompt_choice_menu


def human_readable_to_bytes(size: str) -> int:
    try:
        numeric_size = float(size[:-1])
        unit = size[-1]
    except ValueError:
        try:
            numeric_size = float(size[:-2])
            unit = size[-2:-1]
        except ValueError as err:
            raise ValueError(f"Can't convert {size!r} to bytes") from err
    unit = unit.upper()
    if unit == "G":
        bytes_val = numeric_size * 1073741824
    elif unit == "M":
        bytes_val = numeric_size * 1048576
    elif unit == "K":
        bytes_val = numeric_size * 1024
    else:
        bytes_val = numeric_size
    return int(bytes_val)


def item_by_id(items, id: str, *, key="Id"):
    return next(filter(lambda i: i.get(key) == id, items), None)
