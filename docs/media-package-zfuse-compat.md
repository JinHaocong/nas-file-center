# ZOS/FUSE media-package publication and recovery

Keep all real media directory names and paths in private Komodo variables. Do not commit them to GitHub.

## Failure and fallback

An unsupported atomic directory NOREPLACE rename, followed by an unproven plain rename, used to stop a fully staged package with Errno 95. Plain os.rename must never be used without positive no-clobber proof.

The new fallback requires same-device identities and an active Worker lease. It first exclusively creates an unused target directory, persists a group ownership witness bound to the original frozen manifest checksum and job ID, then publishes each file using an exclusive hardlink. It does not copy or transcode media. It writes a completed-publication witness only after verifying every target file's device/inode/size/mtime. It retires staged hardlinks only after all final bindings are present and verified, and removes the hidden witnesses only after the staging directory is empty and removed.

The compatibility path is not an atomic whole-directory publication: while a hidden publication witness exists, the final group may still be incomplete. A foreign target, missing or altered witness, unknown file, symbolic link, failed fsync, or differing file identity must stop recovery. A crash between mkdir and creating the ownership witness can leave an empty unmarked target, which must not be adopted automatically.

## Isolated capability check on the actual NAS mount

Run inside the Worker container only after confirming `/data` is the expected container-visible, writable NAS mount:

```bash
docker exec nas-file-center-worker python -m app.batch.media_package_zfuse_probe --parent /data --ack-scratch-write
```

The probe creates a randomly named `.nfc-media-fs-probe-*` scratch directory under the selected mount. It uses only tiny synthetic files to verify directory fsync, O_EXCL file marker fsync, exclusive mkdir, hardlink no-overwrite, source-link retirement and cleanup. Unexpected entries or changed identities are never automatically deleted. Exit 0 with `compatible: true` is required before even considering live recovery. A positive result is not proof against later firmware changes or concurrent external modifications.

## Existing failed jobs

Before recovery, back up the dataset or take a storage snapshot. Keep the failed WorkJob, original frozen manifests and preview reports in CONFIG_DIR, and all `.nfc-media_package-stage-*` directories. Never restart a fresh sort over the same partially staged resource package.

Use the failed-job inspector's explicit recovery control only when the error matches the narrowly allowlisted publication failures. It queues a new job under an explicit confirmation, retains the original failed job as audit, and reuses its original staging namespace and immutable manifest. Missing or altered frozen evidence stops recovery. After success, independently run a read-only preview and compare the expected file totals and path mapping.

## Deployment

API and Worker must use the same image and privately configured `MEDIA_PACKAGE_ROOT`. Committing to GitHub, publishing to Docker Hub, and Komodo Resource Sync do not themselves redeploy running containers. Do not redeploy during active file operations.
