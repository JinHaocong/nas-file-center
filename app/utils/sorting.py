from __future__ import annotations

import re


def natural_sort_key(s: str) -> tuple:
    """Split string into digits and non-digits for natural alphanumeric sorting."""
    tokens = re.split(r"(\d+)", s.casefold())
    return tuple((0, int(token)) if token.isdigit() else (1, token) for token in tokens)


class _MaxHeapCandidate:
    __slots__ = ("sort_key", "val")

    def __init__(self, sort_key: tuple, val: tuple):
        self.sort_key = sort_key
        self.val = val

    def __lt__(self, other: _MaxHeapCandidate) -> bool:
        # Inverted comparison so heapq functions as a max-heap:
        # the element with the largest sort_key sits at heap[0].
        return self.sort_key > other.sort_key
