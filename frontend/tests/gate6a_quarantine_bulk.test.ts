import test, { describe } from 'node:test';
import assert from 'node:assert';

import { quarantineApi } from '../src/api/quarantine';
import { api } from '../src/api/client';
import {
  getBulkSelectableEntryIds,
  getBulkRestoreAvailability,
  isBulkPreviewSelectionCurrent,
} from '../src/components/quarantine/quarantine_rules';
import type { QuarantineEntry } from '../src/types';


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
});
