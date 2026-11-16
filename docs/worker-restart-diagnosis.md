# Diagnosing Worker interruptions in nas-file-center

> A task reporting `Worker restarted while job was running` does **not** prove
> that Docker actually restarted. It is a fail-closed recovery verdict for a
> previously running task after the active Worker changes or reacquires a lease.

## Architecture: what is fenced?

- API and Worker share `/config/app.db` (SQLite WAL mode).
- Worker renews its exclusive `task_lock` lease in a separate heartbeat
  thread (normally every 10 seconds).
- A lease is **invalid after 30 seconds**, and an expired/non-owner Worker
  must never renew or execute a filesystem mutation.
- SQLite permits one writer. Its configured busy timeout is 5 seconds;
  operations holding a write transaction can delay heartbeat renewals.
- Media-sort Plan generation now commits bounded batches and can resume
  after interruptions. Only a fully generated Plan becomes a `draft`;
  intermediate `building` Plans cannot Freeze/Validate/Execute.

## What changed in the heartbeat patch

A temporarily busy SQLite writer is distinguished from a confirmed invalid
Worker lease. The heartbeat thread logs contention and retries within ~1
second (or sooner for shorter test intervals), **without changing the lease
timeout**. When the database becomes writable, the lease is checked again
using the current time. A lease that has genuinely expired or changed owner
is still rejected, and the Worker fences itself.

The heartbeat also stays alive while an in-flight job finishes after a
graceful SIGTERM; a deployment may still force-kill the container when Docker's
stop grace period expires. Resumable jobs can then restart from committed
batches, but an abrupt crash remains observable in Docker events.

These logs expose details rather than silently swallowing transient errors:

- `heartbeat waiting on SQLite writer`: database write contention, not
  proof of a Docker restart
- `heartbeat resumed after ... writer contention`: contention resolved
- `heartbeat rejected: exclusive lease lost or expired`: lease rejection;
  Worker must not proceed with unowned work
- `Worker started ... pid=...` and `Worker stopping ... pid=...`: process
  lifecycle (distinguishes normal stop from unexpected absence of stop logs)
- `recovered interrupted tasks`: a new or reacquiring Worker handled
  unfinished tasks after ownership changed

## NAS / Komodo / Docker diagnostics

Run these on the NAS host, not in the web UI. The suggested container name
matches `compose.komodo.yaml`; adapt it if you renamed the service.

```bash
docker inspect -f 'Status={{.State.Status}} RestartCount={{.RestartCount}} OOMKilled={{.State.OOMKilled}} ExitCode={{.State.ExitCode}} StartedAt={{.State.StartedAt}} FinishedAt={{.State.FinishedAt}}' nas-file-center-worker

docker logs --timestamps --since 24h --tail 1000 nas-file-center-worker 2>&1 | grep -Ei 'heartbeat|lease|locked|worker started|worker stopping|recovered|error|exception'

docker events --since 24h --until 1m --filter container=nas-file-center-worker --format '{{.Time}} {{.Status}} {{.Actor.Attributes.name}}'

docker stats --no-stream nas-file-center-worker
```

For evidence of *past* OOM on a Linux NAS with appropriate permissions:

```bash
dmesg -T 2>/dev/null | grep -Ei 'out of memory|oom-killer|killed process|memory cgroup' | tail -50
```

Do not use `docker restart` or modify SQLite while a Plan is running just to
collect diagnostics. Export logs first; restart and image update terminate
running processes. A container replacement may reset `RestartCount`.

## How to interpret evidence

| Evidence | Likely explanation | Next action |
| --- | --- | --- |
| Exit code 137, `OOMKilled=true`, kernel OOM message | Memory pressure | Raise actual container memory limit / reduce parallel services; review NAS memory usage |
| Container `StartedAt` is new and `docker events` shows stop/recreate | Deployment or container lifecycle | Check Komodo rollout history and image updates |
| Same PID/container uptime, `heartbeat waiting on SQLite writer` | SQLite write contention | Verify `/config` storage latency, check for long transactions and active writers |
| `lease rejected` or worker change with no OOM | Lease ownership lost | Ensure exactly one Worker owns the same `/config`, inspect the heartbeat and DB logs |
| No heartbeat errors, Python traceback in worker logs | Application exception | Investigate stack trace and task ID, not just generic recovery message |

## Operational recommendations

1. **Keep the SQLite database under a low-latency local storage directory**
   (e.g. an SSD on the NAS); `/data` may be a large HDD pool but should not
   host the database by accident. In Komodo config, this is the `/config`
   bind mount.
2. Run one Worker against each shared `/config`. Do not scale Worker
   replicas without explicitly redesigning ownership.
3. Avoid redeploying/rebuilding the Worker during a very large Plan.
4. Use the updated batch-resumable Plan creator. Old failed tasks remain
   failed; regenerate from the existing completed preview or rescan if the
   source directory changed.
5. Preserve `/config/app.db`, the DB WAL/SHM files, and preview artifacts.
   Never delete them to clear a failed task. Ensure backups before changing
   deployment or storage layout.

A screenshot of the generic task error alone is not sufficient to identify
OOM, SQLite contention, or deployment restarts. Collect the Docker output and
logs for the time of the interruption before attributing a root cause.
