from yaml import safe_load


def _human_readable_to_bytes(size: str) -> int:
    try:
        numeric_size = float(size[:-1])
        unit = size[-1]
    except ValueError:
        try:
          numeric_size = float(size[:-2])
          unit = size[-2:-1]
        except ValueError:
          raise ValueError("Can't convert %r to bytes" % size)

    unit = unit.upper()

    if unit == "G":
        bytes = numeric_size * 1073741824
    elif unit == "M":
        bytes = numeric_size * 1048576
    elif unit == "K":
        bytes = numeric_size * 1024
    else:
        bytes = numeric_size

    return int(bytes)


with open("config.yml", "r") as f:
    config = safe_load(f)

config["client"]["buffersize"] = _human_readable_to_bytes(config["client"].get("buffersize", "20M"))
config["client"]["keep_partials"] = config["client"].get("keep_partials", False)
config["client"]["prefer_h265"] = config["client"].get("prefer_h265", True)
