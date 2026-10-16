"""Strict WebDAV download verification: no false-green cases."""
from __future__ import annotations

import io
import json
import hashlib
from pathlib import Path

import pytest

from app.download_verification.webdav import WebDAVClient, WebDAVError, relative_parts
from app.download_verification.engine import (
    VerificationError, diff_inventory, local_manifest, hash_local_file
)


def response_xml(entries):
    result = ['<d:multistatus xmlns:d="DAV:">']
    for href, kind, size in entries:
        prop = ('<d:resourcetype><d:collection/></d:resourcetype>' if kind == 'directory'
                else '<d:resourcetype/><d:getcontentlength>' + str(size) + '</d:getcontentlength>')
        result.append('<d:response><d:href>' + href + '</d:href><d:propstat><d:prop>' +
                      prop + '</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>')
    return (''.join(result) + '</d:multistatus>').encode()


class Response:
    def __init__(self, data, status=200, headers=None):
        self.body = io.BytesIO(data)
        self.status = status
        self.headers = headers or {}

    def read(self, n=-1):
        return self.body.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.body.close()


class Opener:
    def __init__(self, manifests, payloads):
        self.manifests = manifests
        self.payloads = payloads
        self.calls = []

    def open(self, request, timeout=None):
        self.calls.append((request.get_method(), request.full_url, request.get_header('Authorization')))
        if request.get_method() == 'PROPFIND':
            return Response(self.manifests[request.full_url], status=207)
        data = self.payloads[request.full_url]
        return Response(data, headers={'Content-Length': str(len(data))})


def configured(tmp_path, opener):
    secret = tmp_path / 'secret'
    secret.write_text('redacted-password\n')
    return WebDAVClient(base_url='https://dav.example/dav/', username='readonly',
                        password_file=str(secret), opener=opener)


def test_exact_webdav_tree_and_sha256(tmp_path):
    base = 'https://dav.example/dav/'
    opener = Opener({
        base: response_xml([( '/dav/', 'directory', None),
                            ('/dav/Album%20A/', 'directory', None)]),
        base + 'Album%20A/': response_xml([('/dav/Album%20A/', 'directory', None),
                                           ('/dav/Album%20A/01.mkv', 'file', 4)]),
    }, {base + 'Album%20A/01.mkv': b'abcd'})
    client = configured(tmp_path, opener)
    root = client.manifest(())
    assert set(root) == {'Album A', 'Album A/01.mkv'}
    assert client.sha256(('Album A', '01.mkv'), 4) == hashlib.sha256(b'abcd').hexdigest()
    assert set(method for method, _, _ in opener.calls) == {'GET', 'PROPFIND'}
    assert all(auth and auth.startswith('Basic ') for _, _, auth in opener.calls)


@pytest.mark.parametrize('href', [
    '/dav/A/../escape', '/dav/A/%2fsecret', '/dav/A/%5csecret', '/dav/A/%00',
    '/other/hello', 'https://evil.example/dav/A', '/dav/A/%252Fsecret',
])
def test_dangerous_href_fails_closed(tmp_path, href):
    base = 'https://dav.example/dav/'
    opener = Opener({base: response_xml([('/dav/', 'directory', None), (href, 'file', 3)])}, {})
    client = configured(tmp_path, opener)
    with pytest.raises(WebDAVError):
        client.manifest(())


def test_duplicate_entry_or_failed_propstat_is_not_complete(tmp_path):
    base = 'https://dav.example/dav/'
    sample = response_xml([('/dav/', 'directory', None), ('/dav/a', 'file', 1), ('/dav/a', 'file', 1)])
    with pytest.raises(WebDAVError, match='Duplicate'):
        configured(tmp_path, Opener({base: sample}, {})).manifest(())
    xml = response_xml([('/dav/', 'directory', None), ('/dav/a', 'file', 1)])
    xml = xml.replace(b'HTTP/1.1 200 OK', b'HTTP/1.1 403 Forbidden')
    with pytest.raises(WebDAVError):
        configured(tmp_path, Opener({base: xml}, {})).manifest(())


def test_denied_self_propstat_cannot_be_skipped(tmp_path):
    base = 'https://dav.example/dav/'
    xml = response_xml([('/dav/', 'directory', None), ('/dav/file', 'file', 3)])
    xml = xml.replace(b'HTTP/1.1 200 OK', b'HTTP/1.1 403 Forbidden', 1)
    with pytest.raises(WebDAVError, match='property access failed'):
        configured(tmp_path, Opener({base: xml}, {})).manifest(())


def test_missing_size_or_incomplete_get_fails_closed(tmp_path):
    base = 'https://dav.example/dav/'
    opener = Opener({base: response_xml([('/dav/', 'directory', None), ('/dav/a', 'file', 3)])},
                    {base + 'a': b'ab'})
    client = configured(tmp_path, opener)
    assert client.manifest(())['a']['size'] == 3
    with pytest.raises(WebDAVError, match='Content-Length mismatch|incomplete'):
        client.sha256(('a',), 3)


def test_path_and_directory_exactness_and_same_size_not_verified(tmp_path):
    (tmp_path / 'empty').mkdir()
    (tmp_path / 'a').write_bytes(b'abcd')
    manifest = local_manifest(tmp_path)
    assert manifest['empty']['kind'] == 'directory'
    r = {'empty': {'kind': 'directory', 'size': None}, 'a': {'kind': 'file', 'size': 4}}
    rows = diff_inventory(r, manifest)
    assert [row['status'] for row in rows] == ['PENDING_SHA256', 'DIRECTORY_MATCH']
    assert hash_local_file(tmp_path, 'a', 4) == hashlib.sha256(b'abcd').hexdigest()
    (tmp_path / 'a').write_bytes(b'WXYZ')
    assert hash_local_file(tmp_path, 'a', 4) == hashlib.sha256(b'WXYZ').hexdigest()
    (tmp_path / 'link').symlink_to(tmp_path / 'a')
    with pytest.raises(VerificationError):
        local_manifest(tmp_path)


def test_remote_input_rejects_absolute_and_parent_components():
    for raw in ('/absolute', 'A/../B', 'A//B', 'A/\\B', 'A/./B'):
        with pytest.raises(WebDAVError):
            relative_parts(raw)
