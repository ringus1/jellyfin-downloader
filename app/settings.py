import os
import sys

from .utils import human_readable_to_bytes
from typing import Any
from yaml import YAMLError, safe_load


def locate_config_file() -> str:
    """Locate the path to config.yml.

    Checks the current working directory first, and if running in a
    frozen PyInstaller environment, checks the folder containing the executable.
    """
    if os.path.exists("config.yml"):
        return "config.yml"

    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        exe_config = os.path.join(exe_dir, "config.yml")
        if os.path.exists(exe_config):
            return exe_config

        return exe_config

    return "config.yml"


find_config_file = locate_config_file


def load_and_validate_configuration(config_file_path: str) -> dict[str, Any]:
    """Load configuration from a YAML file and validate boundary constraints."""
    if not os.path.exists(config_file_path):
        print(f"Error: Configuration file '{config_file_path}' was not found.")
        print("Please create 'config.yml' (refer to config.example.yml) before running.")
        sys.exit(1)

    try:
        with open(config_file_path, encoding="utf-8") as file_stream:
            parsed_config = safe_load(file_stream)
    except YAMLError as yaml_error:
        print(f"Error: Failed to parse configuration file '{config_file_path}': {yaml_error}")
        sys.exit(1)

    if not isinstance(parsed_config, dict):
        print(
            f"Error: Configuration file '{config_file_path}' must define a YAML dictionary mapping."
        )
        sys.exit(1)

    if "client" not in parsed_config or not isinstance(parsed_config["client"], dict):
        parsed_config["client"] = {}

    client_section = parsed_config["client"]
    raw_buffer_size = client_section.get("buffersize", "20M")
    client_section["buffersize"] = human_readable_to_bytes(raw_buffer_size)
    client_section["keep_partials"] = bool(client_section.get("keep_partials", False))
    client_section["prefer_h265"] = bool(client_section.get("prefer_h265", True))

    return parsed_config


config_path = locate_config_file()
config = load_and_validate_configuration(config_path)
