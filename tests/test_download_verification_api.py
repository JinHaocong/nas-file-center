"""Authenticated queue and durable read-only verification reports."""
import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models import WorkJob
from app.download_verification.models import DownloadVerificationRun


def test_admin_only_queue_and_secret_never_in_job_payload(tmp_path):
    data = tmp_path / 'data'
    config = tmp_path / 'config'
    data.mkdir()
    config.mkdir()
    source = data / 'Downloaded'
    source.mkdir()
    secret = tmp_path / 'webdav-pass'
    secret.write_text('highly-private-webdav-password')
    settings = Settings(_env_file=None, CONFIG_DIR=str(config), DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=str(data / '.trash'),
        ALLOW_MUTATION=False, ALLOW_DELETE=False,
        DOWNLOAD_VERIFY_WEBDAV_BASE_URL='https://dav.example/dav/',
        DOWNLOAD_VERIFY_WEBDAV_USER='readonly',
        DOWNLOAD_VERIFY_WEBDAV_PASSWORD_FILE=str(secret),
        INITIAL_ADMIN_USERNAME='admin', INITIAL_ADMIN_PASSWORD='test-password-123')
    with TestClient(create_app(settings)) as client:
        url = '/api/download-verifications'
        assert client.post(url, json={'remote_root': '', 'local_root': str(source)}).status_code == 401
        client.headers.update({'Origin': 'http://testserver'})
        assert client.post('/api/auth/login', json={'username': 'admin',
            'password': 'test-password-123'}).status_code == 200
        assert client.get(url + '/configuration').json()['configured'] is True
        queued = client.post(url, json={'remote_root': 'PikPak/Movies', 'local_root': str(source)})
        assert queued.status_code == 202, queued.text
        run_id = queued.json()['id']
        detail = client.get(url + '/' + str(run_id))
        assert detail.status_code == 200
        assert detail.json()['result'] == 'INCOMPLETE'
        assert detail.json()['job_status'] == 'queued'
        assert client.get(url + '/' + str(run_id) + '/items').json()['items'] == []
        with client.app.state.service.SessionLocal() as session:
            run = session.get(DownloadVerificationRun, run_id)
            job = session.get(WorkJob, run.work_job_id)
            assert job.kind == 'download-verify-webdav'
            assert json.loads(job.state_json) == {'run_id': run_id}
            assert 'highly-private-webdav-password' not in job.state_json
        assert client.post(url, json={'remote_root': '../escape', 'local_root': str(source)}).status_code == 422
        assert client.post(url, json={'remote_root': '', 'local_root': str(tmp_path)}).status_code == 422
        assert client.post(url, json={'remote_root': '', 'local_root': str(source),
                                      'password': 'injected'}).status_code == 422
