# Archive detection and file salvage (initial implementation)

Supported input signatures: ZIP, TAR (including gzip/xz/bzip2 TAR by conventional TAR suffix), 7z and RAR/RAR5. The first two use Python's bounded per-entry readers; the latter two are decoded through the system **libarchive** stream API. No extractor is permitted to choose output paths directly. The original archive is opened for reading only. This feature is best-effort **file salvage**, not archive repair.

## Deployment and permissions

The backend uses existing FastAPI, `WorkJob`, Worker/lease, Task Center, `ALLOWED_ROOTS` and `ALLOW_MUTATION`. No database schema migration is necessary. Runtime requires `libarchive13` on Debian for 7z/RAR reading and the existing Pillow image decoder. `libarchive` support depends on the installed package's decoders; no RAR/7z support is claimed until the target image is tested with fixtures.

**The default `/data:ro` mount remains unchanged.** To write a sibling result directory the Worker and API must have actual write permission to the archive's parent and `ALLOW_MUTATION=true`, explicitly authorized by the operator. Do not make the whole NAS writable just to enable this feature; use a limited NAS share/bind mount with access controls. When the parent is read-only the preflight reports `can_write=false` and starting is rejected. Permanent delete permission `ALLOW_DELETE` is not required; the module removes only its own temporary files.

Password submissions are accepted **only** if `/run/nfc-recovery-secrets` is a shared **tmpfs** mount in *both* API and Worker containers. Otherwise the API refuses password-bearing jobs (`PASSWORD_CHANNEL_UNAVAILABLE`). Never pass passwords in CLI arguments, ordinary volumes, environment, SQLite, task events or reports. This first implementation does not survive loss of ephemeral password memory on a restart: re-submit a new recovery task. Attach a small tmpfs-backed Docker volume explicitly in the operator's Compose/Komodo overlay (there are no persistent password files). The regular UI/Task API should never show the one-time secret token.

## Output, verification and limits

For `dir/Photos.7z`, create `dir/Photos.7z_恢复结果_<random>/`. Existing files are never overwritten. Keep usable entries within their relative directories and place failed/partial output in `_incomplete/`. Temporary `.nfc-part-*` files are removed when the handler exits; an abrupt process kill can leave such files, requiring the restart cleanup procedure described below. No `.tar` intermediate is retained if a verified inner TAR extraction produced entries; otherwise the readable TAR is retained as a potential final artifact. Reports are stored as metadata under `/config/archive-recovery-reports/<job-id>.json` (not alongside the source); use the page's download button to export them.

`integrity_passed` means the ZIP entry CRC was checked during a full read. `format_validated` means a full Pillow image decode completed without an original checksum. `unverified` means bytes were readable but there is no applicable original checksum or format validator. `incomplete` means bytes were partial or decode/checksum failed. `unrecovered` means a known entry was skipped or could not be read. TAR header checksum only validates header structure. Total entry count remains unknown when the archive directory cannot be trusted.

Per-job defaults: 10,000 files, 4 GiB total decoded bytes, 30 minutes, 32 name components, and at most one additional TAR layer. The Worker has its existing single-lease concurrency behavior. These are **cooperative** parsing limits; an individual libarchive C call is not separately preempted. Malicious nested archive bombs, pathological CPU/memory decoders and adversarial link races still require stronger sandboxing for untrusted multi-user inputs. For this reason, this initial implementation is intended for **trusted administrators handling untrusted archive files**, not general untrusted user uploads.

## Recovery boundary

- ZIP: intact central directory, plus conservative unencrypted local-header salvage when the directory cannot be parsed. Local header mode currently handles stored/deflate members with explicit sizes, **not data descriptors, AES or Zip64**.
- TAR: aligned USTAR header scanning with checksum, size, entry-kind and path validation. `.tar.gz/.tar.xz/.tar.bz2` use sequential library decoding; resynchronization *inside compressed streams* is not supported.
- 7z/RAR: libarchive streaming, preserving intact outputs after other entries fail where the decoder allows. For explicitly authorized password-protected **7z AES-256-CBC + LZMA2**, an additional CRC-validated, dictionary-reset salvage mode is now available in the limited scenarios described below. Missing multi-volume parts, arbitrary solid-state rebuilding and RAR Solid deep recovery are **not supported**. Password errors and corruption may be indistinguishable (`PASSWORD_OR_DATA_ERROR`).
- Source archive is never deleted or rewritten. A symlink/hardlink archive *entry* is not extracted. Both ordinary and partial published outputs have their status recorded.

## Required release acceptance

Local generated fixtures cover ZIP/TAR corruption and path safety. **Real encrypted 7z, RAR3/RAR5, host zfuse write permissions, process kill/worker restart cleanup, image Docker build and end-to-end authentication must be checked on the exact candidate before production deployment.** Don't infer these from local Python unit tests.
Worker restart cleanup validates the exact task-owned output directory identity and removes only `.nfc-part-<24hex>` names. Directly cancelled queued tasks also retire any pending one-time tmpfs credential and remove their empty result directory. In a filesystem race or a blocked permission situation, cleanup fails closed rather than deleting foreign files.


## Experimental AES-256-CBC / LZMA2 7z deep recovery

Enable the existing **deep recovery** option and supply the archive password using the shared tmpfs credential channel. The system first attempts normal libarchive streaming; then, only for supported 7z layouts, it runs an independent AES/LZMA2 salvage reader. The original archive is never modified, intermediate decrypted bytes live only in bounded process memory, and output is published through the same no-follow, no-clobber directory-descriptor writer.

This deep reader parses and CRC-checks the 7z start/next header (raw or a simple unencrypted LZMA2-encoded header). It accepts a **single packed stream, one folder, linear AES -> LZMA2 decoder graph** with intact file names, per-file unpacked sizes, CRC32 values and a bounded LZMA2 dictionary. It derives the AES-256 key from UTF-16LE password, salt and 7z SHA256 iteration parameters (up to 2^20 rounds, or the special no-hash mode), and decrypts the packed stream using CBC with the archive IV. No password, key, decrypted stream, or intermediate TAR is stored in SQLite or written to a work file.

LZMA2 chunk framing allows per-chunk uncompressed lengths to be tracked even when one chunk's compressed payload is damaged. At a later **dictionary reset** (control 0x01 or 0xE0..0xFF), the decoder can be restarted. The engine publishes a file only if its entire known unpacked span lies within an independently decodable reset segment and **matches the archive's original per-file CRC32 and exact length**. If framing headers are themselves destroyed, a bounded 8 MiB search attempts to identify later reset segments: without reliable original offsets it publishes **only a complete segment whose length and CRC32 match a whole known file**. It does not guess file boundaries or treat a valid LZMA2 frame as proof of intact contents. CRC32 validates consistency with the archive's metadata; it is **not cryptographic authentication**.

Limits: 8 GiB encrypted pack bytes scanned per task; at most 32 MiB unpacked data retained per independently restarted segment; at most 8 MiB extra scan after loss of framing, plus the shared 10,000-file, 4 GiB published output and 30-minute limits. Cancellation and worker-lease checks are reused. Results include `aes_lzma2_deep.status`, `recovered`, `reset_points`, `rejected_segments` and optional `resync_scan`; unsupported cases include a machine-readable reason such as `ENCRYPTED_OR_COMPLEX_7Z_HEADER`, `NOT_AES_LZMA2_LINEAR_FOLDER` or `NO_PER_FILE_CRCS`.

**Not supported:** encrypted 7z file-name headers; multiple folders/packed streams; additional BCJ/Delta/BCJ2 filter graphs; arbitrary LZMA2 state reconstruction without a genuine reset; CRC-less files; very large reset segments; AES modes other than the documented 7z AES-CBC coder; truncated/missing multi-volume data; RAR deep recovery. Even a supported archive with a correct password may have **no** recoverable post-damage files if no suitable independent reset exists. Never claim full-archive recovery from a single successfully decoded chunk.

Synthetic encrypted 7z fixtures cover CBC corruption, header/framing corruption, recovery past reset, encoded metadata header, wrong password, original CRC requirements, Unicode passwords, bounded scans, traversal protection, and conflict-free publication. **Real 7-Zip-generated encrypted archives and NAS deployment still require independent acceptance** before production use.

## PASSWORD_CHANNEL_UNAVAILABLE — shared tmpfs troubleshooting (Stage 5E-AF)

When a 7z/ZIP/etc. format and space preflight succeeds but a password-bearing Start returns `PASSWORD_CHANNEL_UNAVAILABLE: configure shared tmpfs`, the API does not see its approved tmpfs at `/run/nfc-recovery-secrets`. This is a **deployment prerequisite**, not a password mismatch; the failed request does not enqueue a job. The read-only `/api/archive-recovery/check` now returns `password_channel_available`, an **API-side mount observation only**. True does not attest that the Worker uses the same mount; a missing/false field disables password-bearing Start in the UI. Existing server authorization remains mandatory. Without a password, existing permission/dependency restrictions apply.

### Operator-controlled setup (never performed by CI or the development assistant)

1. For standard Compose, merge the already-existing `compose.archive-recovery-secrets.yaml` overlay. For Komodo, merge `compose.komodo.archive-recovery-secrets.yaml` into the actual deployed stack. Resolve and review both the API and Worker service mounts **before** any redeploy.
2. Both services must mount exactly the **same** `nfc_recovery_secrets` named volume at `/run/nfc-recovery-secrets`, backed by `type: tmpfs`, `device: tmpfs` and `o: size=1m,mode=0700`. Separate service-local `tmpfs:` mounts are not a shared channel. Do not replace this with ordinary disk-backed bind mounts or persisted volumes.
3. Read-only configuration checks: `docker compose -f compose.yaml -f compose.archive-recovery-secrets.yaml config` or `docker compose -f compose.komodo.yaml -f compose.komodo.archive-recovery-secrets.yaml config` (as applicable). An authorized operator may perform a controlled stack redeploy; inspect the running API **and Worker** mounts afterwards, and click the UI 检测 again.
4. Do not put passwords in `.env`, `/config`, SQLite, container logs, process arguments or screenshots. No password is sent during the check. Keep ALLOWED_ROOTS, ALLOW_MUTATION, limited archive parent write access and all Worker lease safeguards. This does not authorize actual NAS recovery or waive independent real-NAS acceptance.


## Folder selection, output path and password tmpfs are separate concerns (Stage 5E-AG)

Changing the archive source folder in the UI now clears the selected archive, typed password and previous check result; Start also requires the check response to name the **currently** selected source path. This prevents an old positive preflight from authorizing a different archive. The API's path, permission and tmpfs checks remain authoritative.

Current recovery results are created as unique sibling directories beside the **source archive** on its existing writable mount. They are not placed in a configurable central recovery root. A host directory such as `.nas-file-center-archive-recovery` under the NAS File Center config directory may be reserved as a future, separately scoped workspace, but adding a bind mount for it today does **not** redirect output or enable encrypted recovery.

The actual password handoff uses only the named tmpfs-backed `nfc_recovery_secrets` volume mounted at `/run/nfc-recovery-secrets` in both API and Worker. A conventional host folder, disk bind mount, two independent container `tmpfs:` entries, or the existing quarantine directory cannot replace that shared memory channel. Operators must review the resolved Compose/Komodo configuration and running mounts; code merge alone does not modify the NAS deployment.

## Browser WorkJob continuity (Stage 5E-AH)

The recovery page tracks its latest started WorkJob using a validated, non-secret `/archive-recovery?task=<positive-safe-integer>` URL parameter. Only a successful Start response sets the WorkJob ID. Refreshing or navigating back to that URL re-reads the **existing authorized Task API**; the URL must never contain a password, one-time credential or source archive payload. A manual URL task ID does not authorize task mutation, bypass backend permissions or start new recovery.

Selecting a different archive, editing the source path or changing folders clears source-bound password and preflight authorization but **does not dismiss** the running/completed Task ID, cancellation link or report evidence. While a task is tracked the UI blocks another Check/Start. After `completed`, `failed` or `cancelled` the operator can explicitly click “开始下一次恢复” to clear the monitor and source/preflight for a new session. The previous Task record remains in Task Center, and this UI action does not cancel or delete it. No new Worker/NAS behavior was introduced.

A separate 390px/1280px × light/dark/system synthetic Chromium matrix exercises GET-only running and completed Task details, source/folder switching, reload continuity and explicit terminal acknowledgement. All API writes and external destinations are denied, including recovery Check/Start/Cancel. This does **not** establish encrypted 7z acceptance or actual NAS deployment.
