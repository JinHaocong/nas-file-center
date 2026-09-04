import test, { describe } from 'node:test';
import assert from 'node:assert';
import { plansApi } from '../src/api/domain';
import { api } from '../src/api/client';
import {
  formatLegacyClearSuccessMessage,
  formatLegacyAlertDescription,
  LEGACY_CLEANUP_CONFIRM_DESCRIPTION,
} from '../src/components/plans/plan_cleanup';

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

  describe('Truthful Copy: Legacy Cleanup Semantics (affected != unlocked)', () => {
    test('formatLegacyClearSuccessMessage does not claim scans are unconditionally unlocked', () => {
      const msg = formatLegacyClearSuccessMessage(4, 3);
      assert.ok(!msg.includes('解锁 3 个扫描'), 'Must not claim 3 scans unlocked');
      assert.ok(!msg.includes('恢复 3 个扫描'), 'Must not claim scan delete permissions restored');
      assert.ok(
        msg.includes('移除 3 个扫描记录上的旧版计划依赖') || msg.includes('涉及 3 个扫描记录'),
        'Must accurately state legacy plan dependencies were removed on affected scans'
      );
      assert.ok(
        msg.includes('当前批处理计划') || msg.includes('BatchPlan'),
        'Must mention that active BatchPlan dependencies may still retain deletion restrictions'
      );
    });

    test('formatLegacyAlertDescription accurately explains dependency rather than guarantee of unlock', () => {
      const desc = formatLegacyAlertDescription({
        plan_count: 5,
        item_count: 20,
        affected_scan_count: 3,
      });
      assert.ok(!desc.includes('可安全恢复扫描记录的删除权限'), 'Must not claim deletion permission is safely restored');
      assert.ok(desc.includes('涉及 3 个扫描记录'), 'Must mention affected scan count');
      assert.ok(
        desc.includes('如果扫描仍关联当前 BatchPlan，其删除限制仍会继续保留'),
        'Must explicitly state scan deletion lock remains if BatchPlan exists'
      );
    });

    test('LEGACY_CLEANUP_CONFIRM_DESCRIPTION outlines exact scope and non-destructive nature', () => {
      assert.ok(
        !LEGACY_CLEANUP_CONFIRM_DESCRIPTION.includes('解锁所有相关扫描'),
        'Must not state unlocking all scans'
      );
      assert.ok(
        LEGACY_CLEANUP_CONFIRM_DESCRIPTION.includes('不会删除'),
        'Must specify what is not deleted'
      );
      assert.ok(
        LEGACY_CLEANUP_CONFIRM_DESCRIPTION.includes('如果 Scan 仍关联当前 BatchPlan，其删除限制不会解除'),
        'Must specify BatchPlan restriction retention'
      );
    });
  });
});
