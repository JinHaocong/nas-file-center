"""Exercise web authorization against a local stand-in for the official CLI."""
import os
from pathlib import Path
import sys
import time

from fastapi.testclient import TestClient
import pytest

from app.auth.password import hash_password
from app.config import Settings
from app.main import create_app
from app.models import User


ENDPOINT = "/api/settings/zspace-authorization"
ORIGIN = {"Origin": "http://testserver"}
CODE = "TEST-DATA-1234-ABCD"
AUTH_URL = "https://oauth.zconnect.cn/wbui/authorize?state=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb&client_id=ZspCli"


def _fake_cli(path: Path, *, auth_url: str, expires: int) -> None:
    path.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "session = Path(os.environ['ZSPACE_CLI_HOME']) / 'fixture-authorized'\n"
        "assert args[:2] == ['--profile', 'nfc-test']\n"
        "assert 'NFC_TEST_SECRET' not in os.environ\n"
        f"assert {CODE!r} not in ' '.join(args)\n"
        "if 'login' in args:\n"
        "    assert args[-3:] == ['login', '--no-open', '--auth-code-stdin']\n"
        "    session.with_name('fixture-pid').write_text(str(os.getpid()))\n"
        f"    print(json.dumps({{'event':'oauth_authorization','url':{auth_url!r},"
        f"'code_input':'stdin','expires_in':{expires}}}), flush=True)\n"
        "    code = sys.stdin.readline().strip()\n"
        f"    if code != {CODE!r}:\n"
        "        print(code, file=sys.stderr)\n"
        "        sys.exit(2)\n"
        "    session.touch()\n"
        "    print(json.dumps({'ok':True,'data':{'token':code}}))\n"
        "elif args[-1] == 'status':\n"
        "    print(json.dumps({'ok':True,'data':{'logged_in':session.exists()}}))\n"
        "else:\n"
        "    sys.exit(3)\n",
        encoding="utf-8",
    )
    path.chmod(0o700)


def _app(tmp_path: Path, *, auth_url: str = AUTH_URL, expires: int = 180):
    cli = (tmp_path / "cli").resolve()
    profile = (tmp_path / "profile").resolve()
    profile.mkdir(mode=0o700)
    data = (tmp_path / "data").resolve()
    data.mkdir()
    config = (tmp_path / "config").resolve()
    _fake_cli(cli, auth_url=auth_url, expires=expires)
    return create_app(Settings(
        _env_file=None, CONFIG_DIR=config, DATA_MOUNT=data,
        ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=data / "quarantine",
        INITIAL_ADMIN_USERNAME="admin", INITIAL_ADMIN_PASSWORD="test-password-123",
        MEDIA_ORGANIZER_ZSPACE_CLI=cli, MEDIA_ORGANIZER_ZSPACE_REMOTE_ROOT="/sata11/my/data",
        MEDIA_ORGANIZER_ZSPACE_PROFILE="nfc-test", MEDIA_ORGANIZER_ZSPACE_CLI_HOME=profile,
    ))


def _login(client: TestClient, name: str = "admin"):
    assert client.post("/api/auth/login", headers=ORIGIN, json={
        "username": name, "password": "test-password-123",
    }).status_code == 200


def test_admin_authorizes_worker_without_a_mapping_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("NFC_TEST_SECRET", "do-not-pass-to-cli")
    with TestClient(_app(tmp_path)) as client:
        assert client.get(ENDPOINT).status_code == 401
        _login(client)
        assert client.get(ENDPOINT).json() == {"status": "needs_login"}
        start = client.post(f"{ENDPOINT}/start", headers=ORIGIN)
        assert start.status_code == 200, start.text
        assert start.headers["Cache-Control"] == "no-store"
        authorization = start.json()
        assert authorization["url"] == AUTH_URL and 0 < authorization["expires_in"] <= 180
        result = client.post(f"{ENDPOINT}/complete", headers=ORIGIN, json={
            "id": authorization["id"], "code": CODE,
        })
        assert result.status_code == 200, result.text
        assert result.json() == {"status": "authorized"}
        assert CODE not in result.text
        assert client.get(ENDPOINT).json() == {"status": "authorized"}
        duplicate = client.post(f"{ENDPOINT}/complete", headers=ORIGIN, json={
            "id": authorization["id"], "code": CODE,
        })
        assert duplicate.status_code == 409 and CODE not in duplicate.text


def test_authorization_is_bound_to_the_original_browser_session(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as first:
        _login(first)
        other = TestClient(app)
        _login(other)
        first_start = first.post(f"{ENDPOINT}/start", headers=ORIGIN).json()
        payload = {"id": first_start["id"], "code": CODE}
        assert first.post(f"{ENDPOINT}/complete", json=payload).status_code == 403
        assert other.post(f"{ENDPOINT}/start", headers=ORIGIN).status_code == 409
        assert other.post(f"{ENDPOINT}/complete", headers=ORIGIN, json=payload).status_code == 409
        assert other.delete(f"{ENDPOINT}/pending/{first_start['id']}", headers=ORIGIN).status_code == 409
        assert first.delete(f"{ENDPOINT}/pending/{first_start['id']}", headers=ORIGIN).status_code == 204
        assert first.post(f"{ENDPOINT}/complete", headers=ORIGIN, json=payload).status_code == 409
        assert other.post(f"{ENDPOINT}/start", headers=ORIGIN).status_code == 200


def test_validation_and_cli_errors_do_not_echo_a_submitted_secret(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        _login(client)
        start = client.post(f"{ENDPOINT}/start", headers=ORIGIN).json()
        invalid = "SECRET-UNTRUSTED\nCLI-INPUT"
        malformed = client.post(f"{ENDPOINT}/complete", headers=ORIGIN, json={
            "id": start["id"], "code": invalid,
        })
        assert malformed.status_code == 422 and "SECRET-UNTRUSTED" not in malformed.text
        rejected = client.post(f"{ENDPOINT}/complete", headers=ORIGIN, json={
            "id": start["id"], "code": "FAKE-FAIL-0000-0000",
        })
        assert rejected.status_code == 409 and "FAKE-FAIL" not in rejected.text
        assert client.get(ENDPOINT).json() == {"status": "needs_login"}
        assert client.post(f"{ENDPOINT}/start", headers=ORIGIN).status_code == 200


def test_member_cannot_view_or_start_authorization(tmp_path):
    app = _app(tmp_path)
    with app.state.service.SessionLocal.begin() as db:
        db.add(User(username="member", password_hash=hash_password("test-password-123"), role="member", is_active=True))
    with TestClient(app) as client:
        _login(client, "member")
        assert client.get(ENDPOINT).status_code == 403
        assert client.post(f"{ENDPOINT}/start", headers=ORIGIN).status_code == 403


def test_non_official_authorization_address_is_never_returned(tmp_path):
    with TestClient(_app(tmp_path, auth_url=AUTH_URL.replace("oauth.zconnect.cn", "other.invalid"))) as client:
        _login(client)
        start = client.post(f"{ENDPOINT}/start", headers=ORIGIN)
        assert start.status_code == 503 and "other.invalid" not in start.text


def test_unverified_cli_path_refuses_browser_authorization(tmp_path):
    app = _app(tmp_path)
    cli = tmp_path / "cli"
    replacement = cli.rename(tmp_path / "replacement")
    cli.symlink_to(replacement)
    with TestClient(app) as client:
        _login(client)
        assert client.get(ENDPOINT).json() == {"status": "unavailable"}
        assert client.post(f"{ENDPOINT}/start", headers=ORIGIN).status_code == 503
    assert not (tmp_path / "profile" / "fixture-pid").exists()


def test_pending_process_expires_even_without_a_followup_request(tmp_path):
    with TestClient(_app(tmp_path, expires=1)) as client:
        _login(client)
        authorization = client.post(f"{ENDPOINT}/start", headers=ORIGIN).json()
        pid = int((tmp_path / "profile" / "fixture-pid").read_text())
        deadline = time.monotonic() + 3
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            assert time.monotonic() < deadline, "expired authorization CLI is still running"
            time.sleep(0.05)
        rejected = client.post(f"{ENDPOINT}/complete", headers=ORIGIN, json={
            "id": authorization["id"], "code": CODE,
        })
        assert rejected.status_code == 409
        assert client.post(f"{ENDPOINT}/start", headers=ORIGIN).status_code == 200


def test_cancel_preserves_the_existing_worker_authorization_and_shutdown_reaps_cli(tmp_path):
    app = _app(tmp_path)
    profile = tmp_path / "profile"
    (profile / "fixture-authorized").touch()
    with TestClient(app) as client:
        _login(client)
        assert client.get(ENDPOINT).json() == {"status": "authorized"}
        start = client.post(f"{ENDPOINT}/start", headers=ORIGIN).json()
        assert client.delete(f"{ENDPOINT}/pending/{start['id']}", headers=ORIGIN).status_code == 204
        assert client.get(ENDPOINT).json() == {"status": "authorized"}
        assert client.post(f"{ENDPOINT}/start", headers=ORIGIN).status_code == 200
        pid = int((profile / "fixture-pid").read_text())
        os.kill(pid, 0)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert (profile / "fixture-authorized").exists()
