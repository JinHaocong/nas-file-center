from __future__ import annotations

from sqlalchemy.types import String, TypeDecorator


class FilesystemId(TypeDecorator[int]):
    """Persist non-negative filesystem IDs without SQLite signed-int overflow.

    Values are bound as prefixed hexadecimal text (for example ``u:a8``), not
    decimal text.  The non-numeric prefix is intentional: it prevents SQLite
    INTEGER-affinity columns in databases created by older releases from
    coercing a large unsigned value to REAL and losing precision.
    """

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value: int | str | None, dialect):  # noqa: ARG002
        if value is None:
            return None
        number = int(value)
        if number >= 0:
            return f"u:{number:x}"
        return f"s:{-number:x}"

    def process_result_value(self, value, dialect):  # noqa: ARG002
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            # Compatibility with an older SQLite row, if one exists. New
            # writes never use REAL for filesystem identifiers.
            return int(value)
        text = str(value)
        if text.startswith("u:"):
            return int(text[2:], 16)
        if text.startswith("s:"):
            return -int(text[2:], 16)
        return int(text)
