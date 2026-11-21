#!/usr/bin/env bash
# #403: GitHub Actions only; all data are synthetic under a disposable /tmp.
# No NAS bind, production config, media or credentials are read.
set -Eeuo pipefail
if [[ "$GITHUB_ACTIONS" != "true" ]]; then
  echo "CI-only synthetic test; do not run on NAS" >&2
  exit 2
fi
command -v setpriv >/dev/null
: "$GITHUB_RUN_ID"
: "$GITHUB_RUN_ATTEMPT"
repo="$(cd "$(dirname "$0")/.." && pwd)"
scratch="$(mktemp -d /tmp/nfc-v16-preview-crossuid-XXXXXXXX)"
cleanup() {
  if [[ "$scratch" == /tmp/nfc-v16-preview-crossuid-* ]]; then
    sudo rm -rf -- "$scratch"
  fi
}
trap cleanup EXIT INT TERM
chmod 0755 "$scratch"
# The hosted runner's checkout is private to UID 1001; never chmod it.
# Give the disposable UIDs only a read-only source copy in private CI scratch.
cp -a "$repo/app" "$scratch/app"
cd "$scratch"
config="$scratch/config"
media="$scratch/data"
mkdir -p "$media/Collection/NO.001" "$config"
printf 'mock-image-1\n' > "$media/Collection/NO.001/photo.JpG"
printf 'mock-video-1\n' > "$media/Collection/NO.001/video.Mp4"
sudo chown 10002:10000 "$config"
sudo chmod 2770 "$config"
sudo mkdir "$config/reports" "$config/backups" "$config/logs" "$config/home"
sudo chown 10002:10000 "$config/"{reports,backups,logs,home}
sudo chmod 2770 "$config/"{reports,backups,logs,home}
py="$(command -v python)"

sudo -n env "NFC_SHARED_CONFIG_GID=10000" "PYTHONPATH=$scratch" \
  "NFC_SYNTH_CONFIG=$config" "NFC_SYNTH_MEDIA=$media" \
  setpriv --reuid=10002 --regid=10000 --clear-groups "$py" - <<'PY'
import json, os, pathlib, stat
from types import SimpleNamespace
from sqlalchemy import text
from app.db import create_engine_and_session
from app.batch.media_organizer_jobs import MediaOrganizerPreviewHandler, report_files, mapping_report_root
root=pathlib.Path(os.environ["NFC_SYNTH_CONFIG"])
data=pathlib.Path(os.environ["NFC_SYNTH_MEDIA"])
engine,_=create_engine_and_session(root/"app.db")
with engine.begin() as c:
    c.execute(text("CREATE TABLE cross_uid_test (value TEXT NOT NULL)"))
    c.execute(text("INSERT INTO cross_uid_test (value) VALUES ('synthetic-handoff')"))
engine.dispose()
assert stat.S_IMODE((root/"app.db").stat().st_mode)==0o660
settings=SimpleNamespace(reports_dir=root/"reports",allowed_roots=[data],
    quarantine_root=data/".trash",media_package_root=None)
job=SimpleNamespace(id=4318,state_json=json.dumps({"selection":str(data/"Collection")}))
class Context:
    def checkpoint(self,**_kwargs): pass
MediaOrganizerPreviewHandler().run(job,Context(),settings)
a,b=report_files(settings,4318)
mapping_root=mapping_report_root(settings,4318)
assert stat.S_IMODE(a.stat().st_mode)==0o640
assert stat.S_IMODE(b.stat().st_mode)==0o640
assert stat.S_IMODE(mapping_root.stat().st_mode)==0o2770
assert a.stat().st_gid==b.stat().st_gid==10000
print("WORKER_UID_10002_PREVIEW_AND_SQLITE_OK")
PY

sudo -n env "NFC_SHARED_CONFIG_GID=10000" "PYTHONPATH=$scratch" \
  "NFC_SYNTH_CONFIG=$config" "NFC_SYNTH_MEDIA=$media" \
  setpriv --reuid=10001 --regid=10000 --clear-groups "$py" - <<'PY'
import os,pathlib,stat
from types import SimpleNamespace
from sqlalchemy import text
from app.db import create_engine_and_session
from app.batch.media_organizer_jobs import (
    PREVIEW_KIND,get_media_organizer_preview,get_media_organizer_mapping,
)
root=pathlib.Path(os.environ["NFC_SYNTH_CONFIG"])
data=pathlib.Path(os.environ["NFC_SYNTH_MEDIA"])
settings=SimpleNamespace(reports_dir=root/"reports",allowed_roots=[data],
    quarantine_root=data/".trash",media_package_root=None,
    media_organizer_execution_enabled=False,allow_mutation=False,allow_delete=False)
class Session:
    def __enter__(self): return self
    def __exit__(self,*_args): return None
    def get(self,_model,_id): return SimpleNamespace(
        kind=PREVIEW_KIND,status="completed",state_json="{}",
        error_text=None,progress_current=1,progress_total=1,progress_message="done")
result=get_media_organizer_preview(lambda: Session(),settings,4318)
assert result["status"]=="completed",result
assert result["summary"]["ready_count"]==1,result
ready=next(item for item in result["units"] if item["status"]=="ready")
assert ready["mapping_id"] and ready["total_files"]==2,ready
mapping=get_media_organizer_mapping(
    lambda: Session(),settings,4318,ready["mapping_id"],page=1,page_size=5)
assert mapping["total_moves"]==2,mapping
assert len(mapping["moves"])==2
assert {r["kind"] for r in mapping["moves"]}=={"P","V"}
engine,_=create_engine_and_session(root/"app.db")
with engine.begin() as c:
    assert c.execute(text("SELECT value FROM cross_uid_test")).scalar_one()=="synthetic-handoff"
    c.execute(text("INSERT INTO cross_uid_test VALUES ('api-visible')"))
engine.dispose()
assert stat.S_IMODE((root/"app.db").stat().st_mode)==0o660
print("API_UID_10001_READS_WORKER_PREVIEW_MAPPING_AND_DB_OK")
PY

sudo -n env "NFC_SHARED_CONFIG_GID=10000" "PYTHONPATH=$scratch" \
  "NFC_SYNTH_CONFIG=$config" \
  setpriv --reuid=10002 --regid=10000 --clear-groups "$py" - <<'PY'
import os,pathlib
from sqlalchemy import text
from app.db import create_engine_and_session
engine,_=create_engine_and_session(pathlib.Path(os.environ["NFC_SYNTH_CONFIG"])/"app.db")
with engine.begin() as c:
    rows=c.execute(text("SELECT value FROM cross_uid_test ORDER BY rowid")).scalars().all()
    assert rows==["synthetic-handoff","api-visible"],rows
engine.dispose()
print("WORKER_SEES_API_COMMIT_OK")
PY

sudo -n env "NFC_SYNTH_CONFIG=$config" \
  setpriv --reuid=10003 --regid=10003 --clear-groups "$py" - <<'PY'
import os,pathlib
folder=pathlib.Path(os.environ["NFC_SYNTH_CONFIG"])
try:
    (folder/"app.db").open("rb")
except PermissionError:
    print("FOREIGN_UID_CONFIG_READ_DENIED")
else:
    raise AssertionError("untrusted UID could read shared SQLite")
PY

[[ "$(cat "$media/Collection/NO.001/photo.JpG")" == 'mock-image-1' ]]
[[ "$(cat "$media/Collection/NO.001/video.Mp4")" == 'mock-video-1' ]]
[[ "$(find "$media" -type f | wc -l)" -eq 2 ]]

# The observed root:root / 0755 deployment shape must fail without writes.
sudo mkdir "$scratch/legacy-root-owned"
sudo chmod 0755 "$scratch/legacy-root-owned"
sudo chown 0:0 "$scratch/legacy-root-owned"
sudo -n env "NFC_SHARED_CONFIG_GID=10000" "PYTHONPATH=$scratch" \
  "NFC_SYNTH_LEGACY=$scratch/legacy-root-owned" \
  setpriv --reuid=10002 --regid=10000 --clear-groups "$py" - <<'PY'
import os,pathlib
from app.db import create_engine_and_session
legacy=pathlib.Path(os.environ["NFC_SYNTH_LEGACY"])/"app.db"
try:
    create_engine_and_session(legacy)
except PermissionError as err:
    assert "SHARED_CONFIG" in str(err),err
    assert not legacy.exists()
    print("ROOT_0755_LEGACY_CONFIG_FAILS_CLOSED")
else:
    raise AssertionError("root-owned legacy config was accepted")
PY
echo "PASS_REAL_CROSS_UID_PREVIEW_DB_AND_LEGACY_GUARD_NO_NAS"
