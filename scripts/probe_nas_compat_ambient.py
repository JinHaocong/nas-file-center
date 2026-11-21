"""CI-only caller of the app's dormant NAS capability launcher.

The probe executes only inside a disposable Docker fixture. It tests the
real app.nas_compat_launcher drop/ambient implementation, not a second copy.
"""
import os
import sys

from app.nas_compat_launcher import _drop_to_worker


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("CI-only synthetic payload required")
    _drop_to_worker(10002, 10000)
    os.execv(sys.executable, [sys.executable, "-c", sys.argv[1]])
