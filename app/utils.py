from simple_term_menu import TerminalMenu
from typing import Optional, Iterable, TypeVar, Callable

T = TypeVar('T')


def choice_menu(items: Iterable[T], name: Callable[[T], str] = lambda i: i, title: Optional[str] = None) -> Optional[T]:
    item_id = TerminalMenu([name(i) for i in items], title=title).show()
    return items[item_id]


def human_readable_to_bytes(size: str) -> int:
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


def item_by_id(items, id: str, *, key="Id"):
    return next(filter(lambda i: i.get(key) == id, items), None)
