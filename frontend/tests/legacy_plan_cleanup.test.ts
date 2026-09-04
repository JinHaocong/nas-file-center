import test, { describe } from 'node:test';
import assert from 'node:assert';
import { plansApi } from '../src/api/domain';
import { api } from '../src/api/client';

describe('Legacy Plan Cleanup: API Contract Tests', () => {
  const originalGet = api.get;
  const originalPost = api.post;

  test('getLegacySummary calls GET /api/plans/legacy/summary', async () => {
    let capturedUrl = '';
    api.get = ((url: string) => {
      capturedUrl = url;
      return Promise.resolve({
        plan_count: 2,
        item_count: 10,
        affected_scan_count: 1,
      });
    }) as any;

    try {
      const res = await plansApi.getLegacySummary();
      assert.strictEqual(capturedUrl, '/api/plans/legacy/summary');
      assert.strictEqual(res.plan_count, 2);
      assert.strictEqual(res.item_count, 10);
      assert.strictEqual(res.affected_scan_count, 1);
    } finally {
      api.get = originalGet;
    }
  });

  test('clearLegacyPlans calls POST /api/plans/legacy/clear', async () => {
    let capturedUrl = '';
    api.post = ((url: string) => {
      capturedUrl = url;
      return Promise.resolve({
        deleted_count: 2,
        deleted_item_count: 10,
        affected_scan_count: 1,
      });
    }) as any;

    try {
      const res = await plansApi.clearLegacyPlans();
      assert.strictEqual(capturedUrl, '/api/plans/legacy/clear');
      assert.strictEqual(res.deleted_count, 2);
      assert.strictEqual(res.deleted_item_count, 10);
      assert.strictEqual(res.affected_scan_count, 1);
    } finally {
      api.post = originalPost;
    }
  });
});
