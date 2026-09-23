import os
import sys

from .utils import human_readable_to_bytes
from typing import Any
from yaml import YAMLError, safe_dump, safe_load

DEFAULT_CONFIG_TEMPLATE = """\
server:
  url: http://localhost:8096

authentication:
  username: aaa
  pass: bbb

client:
  connections: 1
  buffersize: 10M
  keep_partials: false
  prefer_h265: true
  download_dir: downloads
  ffmpeg_path: ffmpeg
"""


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


def get_config_example_content() -> str:
    """Retrieve template content for config.example.yml from bundle, repo, or fallback."""
    candidate_paths: list[str] = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidate_paths.append(os.path.join(sys._MEIPASS, "config.example.yml"))
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidate_paths.append(os.path.join(exe_dir, "config.example.yml"))

    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate_paths.append(os.path.join(parent_dir, "config.example.yml"))
    candidate_paths.append("config.example.yml")

    for path in candidate_paths:
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return f.read()
            except OSError:
                pass

    return DEFAULT_CONFIG_TEMPLATE


def generate_example_config_file(target_example_path: str) -> bool:
    """Generate config.example.yml at the target location if not already present."""
    if os.path.exists(target_example_path):
        return True
    try:
        parent_dir = os.path.dirname(target_example_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        content = get_config_example_content()
        with open(target_example_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except OSError as err:
        print(f"Warning: Could not create template '{target_example_path}': {err}")
        return False


def setup_interactive_configuration(target_config_path: str) -> bool:
    """Prompt the user interactively to configure server and credentials, writing config.yml."""
    print("\n--- Jellyfin Downloader Setup ---")
    try:
        server_url = (
            input("Jellyfin Server URL [http://localhost:8096]: ").strip()
            or "http://localhost:8096"
        )
        username = ""
        while not username:
            username = input("Username: ").strip()
            if not username:
                print("Username cannot be empty.")

        import getpass

        try:
            password = getpass.getpass("Password: ")
        except Exception:
            password = input("Password: ")

        download_dir = input("Download directory [downloads]: ").strip() or "downloads"
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        return False

    new_config = {
        "server": {
            "url": server_url,
        },
        "authentication": {
            "username": username,
            "pass": password,
        },
        "client": {
            "connections": 1,
            "buffersize": "10M",
            "keep_partials": False,
            "prefer_h265": True,
            "download_dir": download_dir,
            "ffmpeg_path": "ffmpeg",
        },
    }

    try:
        parent_dir = os.path.dirname(target_config_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        header = "# Jellyfin Downloader Configuration\n\n"
        yaml_content = safe_dump(new_config, sort_keys=False)
        with open(target_config_path, "w", encoding="utf-8") as f:
            f.write(header + yaml_content)
        return True
    except OSError as err:
        print(f"Error: Unable to write configuration to '{target_config_path}': {err}")
        return False


def load_and_validate_configuration(config_file_path: str) -> dict[str, Any]:
    """Load configuration from a YAML file and validate boundary constraints."""
    if not os.path.exists(config_file_path):
        target_dir = os.path.dirname(config_file_path)
        example_path = (
            os.path.join(target_dir, "config.example.yml") if target_dir else "config.example.yml"
        )

        if sys.stdin.isatty():
            print(f"Configuration file '{config_file_path}' was not found.")
            try:
                choice = (
                    input("Would you like to configure it interactively now? [Y/n]: ")
                    .strip()
                    .lower()
                )
            except (KeyboardInterrupt, EOFError):
                print("\nAborted.")
                sys.exit(1)

            if choice in ("", "y", "yes"):
                if setup_interactive_configuration(config_file_path):
                    print(f"Configuration saved to '{config_file_path}'.\n")
                else:
                    sys.exit(1)
            else:
                generate_example_config_file(example_path)
                print(f"Created template '{example_path}'.")
                print(
                    f"Please create '{config_file_path}' (refer to '{example_path}') before running."
                )
                sys.exit(0)
        else:
            print(f"Error: Configuration file '{config_file_path}' was not found.")
            generate_example_config_file(example_path)
            print(f"Please create '{config_file_path}' (refer to '{example_path}') before running.")
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
    client_section["connections"] = int(client_section.get("connections", 1))
    raw_buffer_size = client_section.get("buffersize", "20M")
    client_section["buffersize"] = human_readable_to_bytes(raw_buffer_size)
    client_section["keep_partials"] = bool(client_section.get("keep_partials", False))
    client_section["prefer_h265"] = bool(client_section.get("prefer_h265", True))

    return parsed_config


config_path = locate_config_file()
config = load_and_validate_configuration(config_path)
