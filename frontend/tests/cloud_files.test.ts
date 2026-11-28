import assert from 'node:assert/strict';
import test from 'node:test';

import { cloudFilesApi, type CloudTransfer, type CloudTransferFile } from '../src/api/cloudFiles';
import { displaySpeed, estimateOpenListSpeed, nativeTransferPage } from '../src/pages/CloudFiles/presentation';

const jobId = 'rclone.example-instance.90071992547409933';

test('the native file API preserves a multi-select with provider names and task IDs intact', async context => {
  const calls: { url: URL; method: string | undefined; body: unknown }[] = [];
  context.mock.method(globalThis, 'fetch', async (input: string, init?: RequestInit) => {
    calls.push({ url: new URL(input, 'https://nas.invalid'), method: init?.method,
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined });
    return Response.json({ id: jobId });
  });
  const batch = {
    provider: 'rclone' as const, remote: 'PikPak WebDAV', path: '共享 & 视频/片段 + 动画',
    names: ['说明.pdf', '项目文件'], destination: '/data/Download/新项目',
  };
  await cloudFilesApi.entries(batch.provider, batch.remote, batch.path);
  const accepted = await cloudFilesApi.start(batch);
  assert.ok('id' in accepted);
  await cloudFilesApi.cancel(accepted.id);
  await cloudFilesApi.remove(accepted.id);
  assert.equal(calls[0].url.pathname, '/api/cloud-files/entries');
  assert.equal(calls[0].url.searchParams.get('remote'), 'PikPak WebDAV');
  assert.equal(calls[0].url.searchParams.get('path'), batch.path);
  assert.deepEqual(calls[1].body, batch);
  assert.equal(accepted.id, jobId);
  assert.equal(calls[2].url.pathname, '/api/cloud-files/transfers/' + jobId + '/cancel');
  assert.equal(calls[3].url.pathname, '/api/cloud-files/transfers/' + jobId);
  assert.deepEqual(calls.map(call => call.method), ['GET', 'POST', 'POST', 'DELETE']);
});

test('a selection made entirely of existing files returns a skip receipt without a task ID', async context => {
  const skipped = { native_ids: [], submitted_count: 0, skipped_names: ['说明.pdf'] };
  context.mock.method(globalThis, 'fetch', async () => Response.json(skipped, { status: 202 }));
  const receipt = await cloudFilesApi.start({
    provider: 'rclone', remote: 'PikPak', path: '', names: skipped.skipped_names, destination: '/data/Download',
  });
  assert.equal('id' in receipt, false);
  assert.deepEqual(receipt, skipped);
});

test('OpenList individual file estimates use byte deltas and preserve missing measurements', () => {
  const receipt: CloudTransfer = {
    id: 'openlist.task-a', provider: 'openlist', remote: null, path: 'source',
    destination: '/data/Download', names: ['目录'], status: 'running',
    progress: null, speed: null, error: null, created_at: '2026-11-28T02:00:00Z',
    native_ids: ['task-a'], files: [], can_cancel: true, can_delete: false,
  };
  const file: CloudTransferFile = {
    name: '目录/相册.png', status: 'running', progress: 25, bytes: 4096, total_bytes: 16384, speed: null,
  };
  const previous = { ...receipt, files: [{ ...file, bytes: 2048 }] };
  const current = { ...receipt, files: [file] };
  const estimated = estimateOpenListSpeed(previous, current, 2000);
  assert.equal(estimated.files[0].speed, 1024);
  assert.equal(displaySpeed(estimated.files[0].speed, estimated.files[0].speed_estimated), '1.00 KB/s（估算）');
  assert.equal(estimated.speed, 1024);
  assert.equal(displaySpeed(null), '—');

  const reset = { ...current, files: [{ ...file, bytes: 1024 }] };
  assert.equal(estimateOpenListSpeed(previous, reset, 2000).files[0].speed, null);
  assert.equal(estimateOpenListSpeed(previous, current, 16_000).files[0].speed, null);
  assert.equal(estimateOpenListSpeed(previous, { ...current, id: 'different' }, 2000).files[0].speed, null);
  assert.equal(estimateOpenListSpeed(previous, { ...current, provider: 'rclone' }, 2000).files[0].speed, null);
});

test('native provider links keep a reverse proxy prefix and omit unsafe addresses', () => {
  assert.equal(nativeTransferPage('openlist', 'https://nas.invalid/list/'), 'https://nas.invalid/list/@manage/tasks/copy');
  assert.equal(nativeTransferPage('rclone', 'https://nas.invalid/clone/'), 'https://nas.invalid/clone/transfers');
  assert.equal(nativeTransferPage('rclone', 'javascript:alert(1)'), undefined);
  assert.equal(nativeTransferPage('openlist', 'https://user:secret@nas.invalid/'), undefined);
});
