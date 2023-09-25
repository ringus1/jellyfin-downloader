from yaml import safe_load
from .utils import human_readable_to_bytes


with open("config.yml", "r") as f:
    config = safe_load(f)

config["client"]["buffersize"] = human_readable_to_bytes(config["client"].get("buffersize", "20M"))
config["client"]["keep_partials"] = config["client"].get("keep_partials", False)
config["client"]["prefer_h265"] = config["client"].get("prefer_h265", True)
