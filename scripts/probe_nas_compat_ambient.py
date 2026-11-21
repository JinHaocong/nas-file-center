"""CI-only disposable check using the real launcher and real scoped DAC gate."""
import os
import sys

from app.nas_compat_launcher import _drop_to_worker


_TEST_AFTER_EXEC = r'''
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from app.nas_compat_launcher import park_nas_compat_runtime, scoped_nas_compat_job, _capsets

park_nas_compat_runtime()
assert _capsets() == (0, 2, 0, 0xc2, 0)
assert not os.access("/data", os.W_OK, effective_ids=True)
job = SimpleNamespace(
    kind="media-organizer-preview", status="running", id=3,
    state_json=json.dumps({"execution_mode": "maintenance_window", "selection": "/data"}),
)
settings = SimpleNamespace(allowed_roots=[Path("/data")])
with scoped_nas_compat_job(job, settings):
    assert _capsets() == (0, 2, 2, 0xc2, 0)
    # A child process EXEC never inherits the DAC capability.
    child = subprocess.check_output([
        sys.executable, "-c",
        "print(next(x for x in open('/proc/self/status') if x.startswith('CapEff:')).split(':')[1].strip())"
    ], text=True).strip()
    assert int(child, 16) == 0
    exec(sys.argv[1])
assert _capsets() == (0, 2, 0, 0xc2, 0)
assert not os.access("/data", os.W_OK, effective_ids=True)
'''

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("CI-only synthetic payload required")
    _drop_to_worker(10002, 10000)
    os.execv(sys.executable, [sys.executable, "-c", _TEST_AFTER_EXEC, sys.argv[1]])
