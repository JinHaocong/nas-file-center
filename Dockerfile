# Stage 1: Build React Frontend
FROM node:22-bookworm-slim AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Fetch the pinned official fclones Linux release binary.
# Avoid compiling Rust and reaching crates.io during NAS image builds.
FROM python:3.12-slim-bookworm AS fclones-builder
ARG FCLONES_VERSION=0.35.0
ARG TARGETARCH=amd64
RUN FCLONES_VERSION="${FCLONES_VERSION}" TARGETARCH="${TARGETARCH}" python - <<'PY'
import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

version = os.environ["FCLONES_VERSION"]
arch = os.environ.get("TARGETARCH", "")
if version != "0.35.0":
    raise SystemExit(f"Unsupported unreviewed fclones version: {version}")
if arch != "amd64":
    raise SystemExit(f"Official pinned fclones binary is currently configured for linux/amd64, got {arch}")

expected_size = 1_965_008
expected_sha256 = "24631bca99e4c20707d12f24676e83a5f1169bd350924dd9852157b243246dff"
url = (
    f"https://github.com/pkolaczk/fclones/releases/download/v{version}/"
    f"fclones-{version}-linux-glibc-x86_64.tar.gz"
)
request = Request(url, headers={"User-Agent": "nas-file-center-build"})
archive_bytes = None
for attempt in range(5):
    try:
        with urlopen(request, timeout=120) as response:
            archive_bytes = response.read(expected_size + 1)
        break
    except (OSError, URLError, TimeoutError):
        if attempt == 4:
            raise
        time.sleep(5 * (attempt + 1))

if archive_bytes is None or len(archive_bytes) != expected_size:
    actual = None if archive_bytes is None else len(archive_bytes)
    raise SystemExit(f"fclones release archive size mismatch: expected {expected_size}, got {actual}")
actual_sha256 = hashlib.sha256(archive_bytes).hexdigest()
if actual_sha256 != expected_sha256:
    raise SystemExit(f"fclones release SHA256 mismatch: expected {expected_sha256}, got {actual_sha256}")

with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
    candidates = [
        member for member in archive.getmembers()
        if member.name.removeprefix("./") == "usr/bin/fclones"
    ]
    if len(candidates) != 1 or not candidates[0].isfile():
        raise SystemExit("Official fclones archive did not contain exactly one regular usr/bin/fclones")
    extracted = archive.extractfile(candidates[0])
    if extracted is None:
        raise SystemExit("Unable to read fclones executable")
    binary = extracted.read()

target = Path("/usr/local/bin/fclones")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(binary)
target.chmod(0o755)
reported = subprocess.check_output([str(target), "--version"], text=True).strip()
if reported != f"fclones {version}":
    raise SystemExit(f"fclones version mismatch: expected {version}, got {reported}")
print(f"Verified official fclones {version}: {len(archive_bytes)}-byte archive; binary={reported}")
print(f"Verified fclones release SHA256: {actual_sha256}")
PY

# Stage 3: Python Runtime
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CONFIG_DIR=/config \
    DATA_MOUNT=/data
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libarchive13 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=fclones-builder /usr/local/bin/fclones /usr/local/bin/fclones
COPY --from=frontend-builder /build/dist /app/frontend/dist
COPY pyproject.toml /app/pyproject.toml
COPY app /app/app
# Avoid an unnecessary pip upgrade download and tolerate slow package downloads.
RUN PIP_DEFAULT_TIMEOUT=120 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    python -m pip install .
RUN mkdir -p /config /data
# Non-root image fallback; Compose overrides the UID for the dedicated Worker.
# Host bind-mount permissions must be provisioned separately, never changed here.
USER 10001:10000
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
