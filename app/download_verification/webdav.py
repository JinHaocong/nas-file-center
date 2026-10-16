"""Bounded, read-only WebDAV PROPFIND and byte-stream GET client.

The origin is operator-configured; remote paths cannot supply a URL or authority.
No redirects, proxy inheritance, HTTP compression, mutating WebDAV methods or
remote payload staging are permitted.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.request import Request, build_opener, HTTPHandler, HTTPSHandler, ProxyHandler, HTTPRedirectHandler
import xml.etree.ElementTree as ET


MAX_XML = 8 * 1024 * 1024
MAX_ENTRIES = 200_000
CHUNK = 4 * 1024 * 1024
_DAV = "{DAV:}"


class WebDAVError(ValueError):
    pass


def segment(raw: str) -> str:
    if (not isinstance(raw, str) or not raw or raw in (".", "..")
            or "/" in raw or "\\" in raw or "\x00" in raw
            or any(ord(c) < 32 for c in raw)):
        raise WebDAVError("Invalid WebDAV path component")
    return raw


def relative_parts(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or len(value) > 4096:
        raise WebDAVError("Invalid remote directory")
    if value in ("", "."):
        return ()
    return tuple(segment(part) for part in value.split("/"))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise WebDAVError("WebDAV redirect denied; original content must be proxied on the approved origin")


class WebDAVClient:
    def __init__(self, *, base_url: str, username: str, password_file: str,
                 allow_http: bool = False, opener=None):
        parsed = urlsplit(base_url)
        if (parsed.scheme not in ("http", "https") or
                (parsed.scheme == "http" and not allow_http) or
                not parsed.hostname or parsed.username or parsed.password or
                parsed.query or parsed.fragment or not parsed.path.endswith("/dav/")):
            raise WebDAVError("Configure one approved WebDAV /dav/ endpoint (HTTPS by default)")
        if not username or not password_file:
            raise WebDAVError("WebDAV read-only credentials must be configured")
        # Only open the configured secret path; never retain the password in a job/DB.
        secret = Path(password_file)
        if not secret.is_file():
            raise WebDAVError("WebDAV secret file is unavailable")
        if secret.stat().st_size > 4096:
            raise WebDAVError("WebDAV secret file is too large")
        password = secret.read_text(encoding="utf-8").rstrip("\r\n")
        token = base64.b64encode((username + ":" + password).encode("utf-8")).decode("ascii")
        self._authorization = "Basic " + token
        self.base = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        # Ignore proxy env to prevent accidental credential forwarding.
        self._opener = opener or build_opener(ProxyHandler({}), _NoRedirect(), HTTPHandler(), HTTPSHandler())

    def _url(self, parts: tuple[str, ...], *, directory: bool = False) -> str:
        path = "/".join(quote(segment(p), safe="") for p in parts)
        return self.base + path + ("/" if directory and parts else "")

    def _request(self, url: str, *, method: str, headers=None, data=None):
        parsed = urlsplit(url)
        root = urlsplit(self.base)
        if (parsed.scheme, parsed.netloc) != (root.scheme, root.netloc) or not parsed.path.startswith(root.path):
            raise WebDAVError("WebDAV request escaped the approved origin")
        h = {"Authorization": self._authorization, "Accept-Encoding": "identity"}
        h.update(headers or {})
        try:
            return self._opener.open(Request(url, data=data, method=method, headers=h), timeout=30)
        except (HTTPError, URLError, OSError) as exc:
            raise WebDAVError("WebDAV request unavailable (" + type(exc).__name__ + ")") from None

    def _href_parts(self, href: str) -> tuple[str, ...]:
        root = urlsplit(self.base)
        p = urlsplit(href)
        if p.scheme or p.netloc:
            if (p.scheme.lower(), p.netloc.lower()) != (root.scheme, root.netloc.lower()):
                raise WebDAVError("Cross-origin WebDAV href")
        if p.query or p.fragment or not p.path.startswith(root.path):
            raise WebDAVError("WebDAV href outside root")
        suffix = p.path[len(root.path):].rstrip("/")
        if not suffix:
            return ()
        decoded = []
        for raw in suffix.split("/"):
            part = unquote(raw, encoding="utf-8", errors="strict")
            if "%" in part and any(q in part.lower() for q in ("%2f", "%5c", "%00")):
                raise WebDAVError("Ambiguous double-encoded WebDAV href")
            decoded.append(segment(part))
        return tuple(decoded)

    def list_directory(self, parts: tuple[str, ...]) -> dict[tuple[str, ...], dict]:
        url = self._url(parts, directory=True)
        body = b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/><d:getcontentlength/><d:getetag/><d:getlastmodified/></d:prop></d:propfind>'
        with self._request(url, method="PROPFIND", headers={"Depth": "1", "Content-Type": "application/xml"}, data=body) as response:
            if response.status != 207:
                raise WebDAVError("WebDAV PROPFIND must return 207")
            raw = response.read(MAX_XML + 1)
        if len(raw) > MAX_XML or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise WebDAVError("Oversized or unsafe WebDAV XML")
        try:
            xml = ET.fromstring(raw)
        except ET.ParseError:
            raise WebDAVError("Malformed WebDAV multi-status") from None
        if xml.tag != _DAV + "multistatus":
            raise WebDAVError("Invalid WebDAV multi-status root")
        out: dict[tuple[str, ...], dict] = {}
        seen_self = False
        for entry in xml:
            if entry.tag != _DAV + "response":
                raise WebDAVError("Unexpected WebDAV multi-status child")
            href = entry.findtext(_DAV + "href")
            if not href:
                raise WebDAVError("Missing WebDAV href")
            child = self._href_parts(href)
            is_self = child == parts
            if is_self and seen_self:
                raise WebDAVError("Duplicate directory self entry")
            if not is_self and (len(child) != len(parts) + 1 or child[:len(parts)] != parts):
                raise WebDAVError("WebDAV Depth:1 returned an out-of-scope entry")
            if not is_self and child in out:
                raise WebDAVError("Duplicate WebDAV path")
            prop = None
            for ps in entry.findall(_DAV + "propstat"):
                status = ps.findtext(_DAV + "status") or ""
                if not status.startswith("HTTP/1.1 200 ") and not status.startswith("HTTP/1.0 200 "):
                    raise WebDAVError("WebDAV property access failed")
                if prop is not None:
                    raise WebDAVError("Ambiguous WebDAV property response")
                prop = ps.find(_DAV + "prop")
            if prop is None:
                raise WebDAVError("WebDAV property set missing")
            resource = prop.find(_DAV + "resourcetype")
            if resource is None:
                raise WebDAVError("WebDAV resource type missing")
            is_dir = resource.find(_DAV + "collection") is not None
            # No unknown DAV type may be silently interpreted as an ordinary directory.
            if any(child_type.tag != _DAV + "collection" for child_type in resource):
                raise WebDAVError("Unsupported WebDAV object")
            if is_self:
                if not is_dir:
                    raise WebDAVError("WebDAV collection self entry is not a directory")
                seen_self = True
                continue
            size = None
            if not is_dir:
                value = prop.findtext(_DAV + "getcontentlength")
                if value is None or not value.isdecimal():
                    raise WebDAVError("WebDAV regular file size missing")
                size = int(value)
            out[child] = {"kind": "directory" if is_dir else "file",
                          "size": size,
                          "etag": prop.findtext(_DAV + "getetag"),
                          "mtime": prop.findtext(_DAV + "getlastmodified")}
        if not seen_self:
            raise WebDAVError("WebDAV collection did not return self entry")
        return out

    def manifest(self, root: tuple[str, ...], checkpoint=lambda: None) -> dict[str, dict]:
        result: dict[str, dict] = {}
        stack = [root]
        visited = 0
        while stack:
            directory = stack.pop()
            for path, meta in self.list_directory(directory).items():
                rel = "/".join(path[len(root):])
                if rel in result or len(result) >= MAX_ENTRIES:
                    raise WebDAVError("Duplicate or over-limit remote inventory")
                result[rel] = meta
                visited += 1
                if visited % 100 == 0:
                    checkpoint()
                if meta["kind"] == "directory":
                    stack.append(path)
        return result

    def sha256(self, path: tuple[str, ...], expected_size: int, checkpoint=lambda: None) -> str:
        with self._request(self._url(path), method="GET") as response:
            if response.status != 200 or response.headers.get("Content-Encoding", "identity").lower() != "identity" or response.headers.get("Content-Range"):
                raise WebDAVError("Remote GET is not an original full 200-byte representation")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) != expected_size):
                raise WebDAVError("Remote GET Content-Length mismatch")
            hashed = hashlib.sha256()
            size = 0
            while True:
                block = response.read(CHUNK)
                if not block:
                    break
                size += len(block)
                if size > expected_size:
                    raise WebDAVError("Remote GET exceeds advertised size")
                hashed.update(block)
                checkpoint()
        if size != expected_size:
            raise WebDAVError("Remote GET incomplete")
        return hashed.hexdigest()
