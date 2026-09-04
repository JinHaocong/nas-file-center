from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterator, TextIO


@dataclass(frozen=True)
class ParsedGroup:
    content_hash: str
    file_size: int
    files: tuple[Path, ...]


def _get(mapping: dict[str, Any], *names: str):
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def stream_json_array(stream: TextIO, chunk_size: int = 65536) -> Iterator[Any]:
    """Stream JSON objects from an array in a text stream with bounded buffer memory."""
    decoder = json.JSONDecoder()
    buffer = ""

    # Read until finding the start of array '['
    found_start = False
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        buffer += chunk
        bracket_pos = buffer.find("[")
        if bracket_pos != -1:
            buffer = buffer[bracket_pos + 1:]
            found_start = True
            break

    if not found_start:
        raise ValueError("No JSON array '[' found in report")

    while True:
        buffer = buffer.lstrip(" \t\r\n,")
        while not buffer:
            chunk = stream.read(chunk_size)
            if not chunk:
                raise ValueError("Unexpected EOF: JSON array was not closed with ']'")
            buffer = chunk.lstrip(" \t\r\n,")

        if buffer.startswith("]"):
            return

        while True:
            try:
                obj, end_idx = decoder.raw_decode(buffer)
                yield obj
                buffer = buffer[end_idx:]
                break
            except json.JSONDecodeError as err:
                chunk = stream.read(chunk_size)
                if not chunk:
                    raise ValueError(f"Unexpected EOF in JSON object: {err}") from err
                buffer += chunk


def stream_fclones_groups(stream: TextIO, chunk_size: int = 65536) -> Iterator[dict[str, Any]]:
    """
    Streamingly parse duplicate groups from top-level "groups" array in an fclones report.
    Enforces:
    1. Top-level must be a JSON object starting with '{' and ending with '}'
    2. Locates top-level "groups" key, ensuring its value is an array starting with '['
    3. Strict JSON separator validation:
       - Rejects missing commas, leading commas, double commas, and trailing commas
       - Both at top-level object level and inside 'groups' array
    4. Rejects duplicate top-level 'groups' keys
    5. Bounded-memory streaming of groups array elements
    6. Fails if top-level closing '}' is missing, if trailing garbage exists, or if 'groups' key is missing.
    """
    decoder = json.JSONDecoder()
    buffer = ""

    def fill_buffer() -> bool:
        nonlocal buffer
        chunk = stream.read(chunk_size)
        if not chunk:
            return False
        buffer += chunk
        return True

    def consume_whitespace() -> None:
        nonlocal buffer
        while True:
            buffer = buffer.lstrip(" \t\r\n")
            if buffer:
                return
            if not fill_buffer():
                return

    consume_whitespace()
    if not buffer or not buffer.startswith("{"):
        raise ValueError("Report must be a top-level JSON object starting with '{'")
    buffer = buffer[1:]  # skip '{'

    found_groups = False
    obj_state = "expect_key_or_end"

    while True:
        consume_whitespace()
        if not buffer:
            raise ValueError("Unexpected EOF: top-level object was not closed with '}'")

        if obj_state == "expect_key_or_end":
            if buffer.startswith("}"):
                buffer = buffer[1:]
                break
            if buffer.startswith(","):
                raise ValueError("Leading comma in top-level JSON object")
        elif obj_state == "expect_comma_or_end":
            if buffer.startswith("}"):
                buffer = buffer[1:]
                break
            if not buffer.startswith(","):
                raise ValueError("Missing comma between keys in top-level JSON object")
            buffer = buffer[1:]  # skip ','
            consume_whitespace()
            if not buffer:
                raise ValueError("Unexpected EOF after comma in top-level JSON object")
            if buffer.startswith(","):
                raise ValueError("Double comma in top-level JSON object")
            if buffer.startswith("}"):
                raise ValueError("Trailing comma in top-level JSON object")
            obj_state = "expect_key"
        elif obj_state == "expect_key":
            if buffer.startswith(","):
                raise ValueError("Double comma in top-level JSON object")
            if buffer.startswith("}"):
                raise ValueError("Trailing comma before '}' in top-level JSON object")

        # Read key
        while True:
            try:
                key, end_idx = decoder.raw_decode(buffer)
                buffer = buffer[end_idx:]
                break
            except json.JSONDecodeError:
                if not fill_buffer():
                    raise ValueError("Unexpected EOF while reading key in top-level JSON object")

        if not isinstance(key, str):
            raise ValueError(f"Invalid non-string key in top-level object: {key}")

        # Consume ':'
        consume_whitespace()
        while not buffer.startswith(":"):
            if not fill_buffer():
                raise ValueError(f"Unexpected EOF waiting for ':' after key '{key}' in top-level object")
            consume_whitespace()
        buffer = buffer[1:]  # consume ':'
        consume_whitespace()

        if key == "groups":
            if found_groups:
                raise ValueError("Duplicate top-level 'groups' key in report")
            found_groups = True

            while not buffer:
                if not fill_buffer():
                    raise ValueError("Unexpected EOF before 'groups' array opening bracket '['")
            if not buffer.startswith("["):
                raise ValueError(f"'groups' value must be a JSON array starting with '[', got '{buffer[:10]}'")
            buffer = buffer[1:]  # consume '['

            # Stream groups array with strict separator checking
            array_state = "expect_value_or_end"

            while True:
                consume_whitespace()
                if not buffer:
                    raise ValueError("Unexpected EOF: 'groups' array was not closed with ']'")

                if array_state == "expect_value_or_end":
                    if buffer.startswith("]"):
                        buffer = buffer[1:]  # consume ']'
                        break
                    if buffer.startswith(","):
                        raise ValueError("Leading comma in 'groups' array")
                elif array_state == "expect_comma_or_end":
                    if buffer.startswith("]"):
                        buffer = buffer[1:]  # consume ']'
                        break
                    if not buffer.startswith(","):
                        raise ValueError("Missing comma between items in 'groups' array")
                    buffer = buffer[1:]  # consume ','
                    consume_whitespace()
                    if not buffer:
                        raise ValueError("Unexpected EOF after comma in 'groups' array")
                    if buffer.startswith(","):
                        raise ValueError("Double comma in 'groups' array")
                    if buffer.startswith("]"):
                        raise ValueError("Trailing comma in 'groups' array")
                    array_state = "expect_value"
                elif array_state == "expect_value":
                    if buffer.startswith(","):
                        raise ValueError("Double comma in 'groups' array")
                    if buffer.startswith("]"):
                        raise ValueError("Trailing comma before ']' in 'groups' array")

                # Decode item
                while True:
                    try:
                        item, end_idx = decoder.raw_decode(buffer)
                        yield item
                        buffer = buffer[end_idx:]
                        array_state = "expect_comma_or_end"
                        break
                    except json.JSONDecodeError as err:
                        if not fill_buffer():
                            raise ValueError(f"Unexpected EOF in JSON object inside 'groups': {err}") from err

        else:
            # Skip non-groups top-level value
            while True:
                try:
                    val, end_idx = decoder.raw_decode(buffer)
                    buffer = buffer[end_idx:]
                    break
                except json.JSONDecodeError:
                    if not fill_buffer():
                        raise ValueError(f"Unexpected EOF while parsing value for key '{key}'")

        obj_state = "expect_comma_or_end"

    if not found_groups:
        raise ValueError("No top-level 'groups' key found in report")

    # After '}', only whitespace is permitted until EOF
    while True:
        if not fill_buffer():
            break
    if buffer.strip():
        raise ValueError(f"Unexpected trailing data after top-level JSON object: {buffer.strip()[:50]}")


def parse_fclones_report_iter(path: Path | str, chunk_size: int = 65536) -> Iterator[ParsedGroup]:
    """Streamingly parse fclones JSON report group-by-group with bounded memory."""
    p = Path(path)
    with open(p, "r", encoding="utf-8") as f:
        for raw in stream_fclones_groups(f, chunk_size=chunk_size):
            if not isinstance(raw, dict):
                raise ValueError(f"Group item must be a JSON object, got {type(raw).__name__}")
            content_hash = _get(raw, "file_hash", "hash", "content_hash")
            file_size = _get(raw, "file_len", "size", "file_size", "len")
            files = _get(raw, "files", "paths", "members")
            if isinstance(files, dict):
                files = files.get("paths") or files.get("files")

            if not isinstance(content_hash, str) or not content_hash.strip():
                raise ValueError(f"Group content_hash must be a non-empty string, got {content_hash!r}")
            if not isinstance(file_size, int) or isinstance(file_size, bool) or file_size < 0:
                raise ValueError(f"Group file_size must be a non-negative integer, got {file_size!r}")
            if not isinstance(files, list):
                raise ValueError(f"Group files must be a list, got {type(files).__name__}")
            if len(files) < 2:
                raise ValueError(f"Duplicate group must contain at least 2 file paths, got {len(files)}")

            paths: list[Path] = []
            for p_entry in files:
                if not isinstance(p_entry, str) or not p_entry.strip():
                    raise ValueError(f"File path in duplicate group must be a non-empty string, got {p_entry!r}")
                paths.append(Path(p_entry))

            yield ParsedGroup(str(content_hash), int(file_size), tuple(paths))


def parse_fclones_report(path: Path | str) -> list[ParsedGroup]:
    """Legacy compatibility helper returning full list of ParsedGroup."""
    return list(parse_fclones_report_iter(path))
