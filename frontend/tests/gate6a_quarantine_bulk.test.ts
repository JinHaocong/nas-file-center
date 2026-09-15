import test, { describe } from 'node:test';
import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { quarantineApi } from '../src/api/quarantine';
import { api } from '../src/api/client';
import {
  getBulkSelectableEntryIds,
  getBulkRestoreAvailability,
  isBulkPreviewFilterCurrent,
  isBulkPreviewSelectionCurrent,
} from '../src/components/quarantine/quarantine_rules';
import type { QuarantineEntry } from '../src/types';

const quarantineTypesSource = readFileSync(
  resolve(process.cwd(), 'src/types/quarantine.ts'),
  'utf8'
);


describe('Gate6-A quarantine bulk API contract', () => {
  test('bulkPreview posts exact restore selection and policy to frozen endpoint', async () => {
    let capturedUrl = '';
    let capturedPayload: unknown = null;
    const originalPost = api.post;
    api.post = (async (url: string, payload: unknown) => {
      capturedUrl = url;
      capturedPayload = payload;
      return {
        action: 'restore',
        entry_ids: [1, 3],
        eligible_count: 2,
        blocked_count: 0,
        items: [],
        preview_digest: 'preview-digest',
      };
    }) as typeof api.post;

    try {
      const payload = {
        action: 'restore' as const,
        entry_ids: [3, 1],
        conflict_policy: 'rename' as const,
      };
      const result = await quarantineApi.bulkPreview(payload);
      assert.strictEqual(capturedUrl, '/api/quarantine/bulk-preview');
      assert.deepStrictEqual(capturedPayload, payload);
      assert.strictEqual(result.preview_digest, 'preview-digest');
    } finally {
      api.post = originalPost;
    }
  });

  test('bulkPlan posts exact purge digest and irreversible confirmation to frozen endpoint', async () => {
    let capturedUrl = '';
    let capturedPayload: unknown = null;
    const originalPost = api.post;
    api.post = (async (url: string, payload: unknown) => {
      capturedUrl = url;
      capturedPayload = payload;
      return { id: 77, kind: 'quarantine-bulk-purge', status: 'draft' };
    }) as typeof api.post;

    try {
      const payload = {
        action: 'purge' as const,
        entry_ids: [7, 9],
        expected_preview_digest: 'digest-79',
        confirmation: 'DELETE' as const,
      };
      const result = await quarantineApi.bulkPlan(payload);
      assert.strictEqual(capturedUrl, '/api/quarantine/bulk-plan');
      assert.deepStrictEqual(capturedPayload, payload);
      assert.strictEqual(result.id, 77);
    } finally {
      api.post = originalPost;
    }
  });

  test('Gate6-A2 bulk preview type surface preserves advisory as separate informational fields', () => {
    const match = quarantineTypesSource.match(
      /export interface QuarantineBulkPreviewItem \{[\s\S]*?\n\}/
    );
    assert.ok(match);
    const block = match[0];
    assert.match(block, /purge_semantics\??:/);
    assert.match(block, /mutation_blockers\??:/);
    assert.match(block, /survivor_scope\??:/);
    assert.match(block, /survivor_status\??:/);
    assert.match(block, /hardlink_survivor_paths\??:/);
    assert.match(block, /independent_copy_paths\??:/);
  });

  test('resolveBulkFilteredEntryIds paginates current filters into explicit active ids', async () => {
    const originalGet = api.get;
    const urls: string[] = [];
    const makeEntry = (id: number, state: QuarantineEntry['state']): QuarantineEntry => ({
      id,
      original_path: `/data/${id}.bin`,
      quarantine_path: `/trash/${id}.bin`,
      task_id: null,
      plan_item_id: null,
      state,
      size: 1,
      hash: null,
      mtime_ns: 1,
      device: 1,
      inode: id,
      quarantined_at: null,
      expires_at: null,
      restored_at: null,
      purged_at: null,
      last_error: null,
      created_at: null,
      updated_at: null,
    });

    const firstPage = Array.from({ length: 500 }, (_, index) => makeEntry(index + 1, 'active'));
    firstPage[10] = makeEntry(11, 'restored');

    api.get = (async (url: string) => {
      urls.push(url);
      if (url.includes('page=1')) {
        return { items: firstPage, total: 501, page: 1, page_size: 500 };
      }
      return { items: [makeEntry(501, 'active')], total: 501, page: 2, page_size: 500 };
    }) as typeof api.get;

    try {
      const ids = await quarantineApi.resolveBulkFilteredEntryIds({ state: 'all', query: ' movie ' });
      assert.strictEqual(ids.length, 500);
      assert.strictEqual(ids.includes(11), false);
      assert.strictEqual(ids[ids.length - 1], 501);
      assert.deepStrictEqual(urls, [
        '/api/quarantine?page=1&page_size=500&query=movie',
        '/api/quarantine?page=2&page_size=500&query=movie',
      ]);
    } finally {
      api.get = originalGet;
    }
  });

  test('resolveBulkFilteredEntryIds fails closed when active selection exceeds 5000', async () => {
    const originalGet = api.get;
    const makeEntry = (id: number): QuarantineEntry => ({
      id,
      original_path: `/data/${id}.bin`,
      quarantine_path: `/trash/${id}.bin`,
      task_id: null,
      plan_item_id: null,
      state: 'active',
      size: 1,
      hash: null,
      mtime_ns: 1,
      device: 1,
      inode: id,
      quarantined_at: null,
      expires_at: null,
      restored_at: null,
      purged_at: null,
      last_error: null,
      created_at: null,
      updated_at: null,
    });

    api.get = (async (url: string) => {
      const parsed = new URL(url, 'http://testserver');
      const page = Number(parsed.searchParams.get('page') || '1');
      const start = (page - 1) * 500 + 1;
      const remaining = 5001 - start + 1;
      const count = Math.max(0, Math.min(500, remaining));
      const items = Array.from({ length: count }, (_, index) => makeEntry(start + index));
      return { items, total: 5001, page, page_size: 500 };
    }) as typeof api.get;

    try {
      await assert.rejects(
        () => quarantineApi.resolveBulkFilteredEntryIds({ state: 'active' }),
        /5000/
      );
    } finally {
      api.get = originalGet;
    }
  });
});

describe('Gate6-A quarantine bulk selection safety rules', () => {
  const entry = (id: number, state: QuarantineEntry['state']): QuarantineEntry => ({
    id,
    original_path: `/data/${id}.bin`,
    quarantine_path: `/trash/${id}.bin`,
    task_id: null,
    plan_item_id: null,
    state,
    size: 1,
    hash: null,
    mtime_ns: 1,
    device: 1,
    inode: id,
    quarantined_at: null,
    expires_at: null,
    restored_at: null,
    purged_at: null,
    last_error: null,
    created_at: null,
    updated_at: null,
  });

  test('only active quarantine rows are eligible for bulk selection', () => {
    const ids = getBulkSelectableEntryIds([
      entry(1, 'active'),
      entry(2, 'restored'),
      entry(3, 'purging'),
      entry(4, 'active'),
      entry(5, 'inconsistent'),
    ]);
    assert.deepStrictEqual(ids, [1, 4]);
  });

  test('bulk restore accepts only skip or rename and never manual target mode', () => {
    assert.deepStrictEqual(getBulkRestoreAvailability(false, 'skip'), { canRestore: true });
    assert.deepStrictEqual(getBulkRestoreAvailability(false, 'rename'), { canRestore: true });
    assert.strictEqual(getBulkRestoreAvailability(false, 'manual' as never).canRestore, false);
    assert.strictEqual(getBulkRestoreAvailability(true, 'skip').canRestore, false);
  });

  test('bulk preview remains current only for the same canonical selected id set', () => {
    assert.strictEqual(isBulkPreviewSelectionCurrent([3, 1], [1, 3]), true);
    assert.strictEqual(isBulkPreviewSelectionCurrent([1, 3], [1, 3, 5]), false);
    assert.strictEqual(isBulkPreviewSelectionCurrent([1, 3], [1]), false);
    assert.strictEqual(isBulkPreviewSelectionCurrent([1, 3], [1, 4]), false);
  });

  test('bulk preview filter identity changes only when active server-side filters change', () => {
    const previewFilter = { state: 'active', query: 'movie' };
    assert.strictEqual(isBulkPreviewFilterCurrent(previewFilter, { state: 'active', query: 'movie' }), true);
    assert.strictEqual(isBulkPreviewFilterCurrent(previewFilter, { state: 'all', query: 'movie' }), false);
    assert.strictEqual(isBulkPreviewFilterCurrent(previewFilter, { state: 'active', query: 'photo' }), false);
    assert.strictEqual(isBulkPreviewFilterCurrent(previewFilter, { state: 'active', query: ' movie ' }), true);
  });
});
