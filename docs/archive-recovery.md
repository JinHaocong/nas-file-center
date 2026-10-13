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
- 7z/RAR: libarchive streaming, preserving intact outputs after other entries fail where the decoder allows. AES/solid compressed stream recovery past damage, missing multi-volume parts and general decompressor-state rebuilding are **not supported**. Password errors and corruption may be indistinguishable (`PASSWORD_OR_DATA_ERROR`).
- Source archive is never deleted or rewritten. A symlink/hardlink archive *entry* is not extracted. Both ordinary and partial published outputs have their status recorded.

## Required release acceptance

Local generated fixtures cover ZIP/TAR corruption and path safety. **Real encrypted 7z, RAR3/RAR5, host zfuse write permissions, process kill/worker restart cleanup, image Docker build and end-to-end authentication must be checked on the exact candidate before production deployment.** Don't infer these from local Python unit tests.
Worker restart cleanup validates the exact task-owned output directory identity and removes only `.nfc-part-<24hex>` names. Directly cancelled queued tasks also retire any pending one-time tmpfs credential and remove their empty result directory. In a filesystem race or a blocked permission situation, cleanup fails closed rather than deleting foreign files.
