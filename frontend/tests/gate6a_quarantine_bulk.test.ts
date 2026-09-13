import test, { describe } from 'node:test';
import assert from 'node:assert';

import { quarantineApi } from '../src/api/quarantine';
import { api } from '../src/api/client';


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
