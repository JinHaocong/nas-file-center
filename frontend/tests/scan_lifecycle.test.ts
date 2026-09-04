import test, { describe } from 'node:test';
import assert from 'node:assert';
import { getScanDeleteAvailability } from '../src/components/scans/scan_cleanup';
import { scansApi } from '../src/api/domain';
import { api } from '../src/api/client';

describe('Scan History Lifecycle: Policy Matrix & API Contract Tests', () => {
  describe('Policy Matrix: getScanDeleteAvailability', () => {
    test('null or undefined scan disallows deletion safely', () => {
      const resNull = getScanDeleteAvailability(null);
      assert.strictEqual(resNull.canDelete, false);
      assert.strictEqual(resNull.reason, '无效扫描状态');

      const resUndef = getScanDeleteAvailability(undefined);
      assert.strictEqual(resUndef.canDelete, false);
      assert.strictEqual(resUndef.reason, '无效扫描状态');

      const resNoStatus = getScanDeleteAvailability({} as any);
      assert.strictEqual(resNoStatus.canDelete, false);
      assert.strictEqual(resNoStatus.reason, '无效扫描状态');
    });

    test('terminal scans without dependent plans are enabled for deletion', () => {
      const terminalStatuses = ['completed', 'failed', 'cancelled'];
      for (const status of terminalStatuses) {
        const res = getScanDeleteAvailability({ status, has_dependent_plan: false });
        assert.strictEqual(res.canDelete, true, `Status ${status} without plan should be deletable`);
        assert.strictEqual(res.reason, undefined);
      }
    });

    test('terminal scans with dependent plans are blocked from deletion', () => {
      const terminalStatuses = ['completed', 'failed', 'cancelled'];
      for (const status of terminalStatuses) {
        const res = getScanDeleteAvailability({ status, has_dependent_plan: true });
        assert.strictEqual(res.canDelete, false, `Status ${status} with plan must be blocked`);
        assert.strictEqual(res.reason, '该扫描已生成关联计划，无法删除');
      }
    });

    test('active scans are blocked regardless of dependent plan', () => {
      const activeStatuses = ['queued', 'running'];
      for (const status of activeStatuses) {
        const res = getScanDeleteAvailability({ status, has_dependent_plan: false });
        assert.strictEqual(res.canDelete, false, `Active status ${status} must be blocked`);
        assert.strictEqual(res.reason, '仅终态扫描可删除');

        const resWithPlan = getScanDeleteAvailability({ status, has_dependent_plan: true });
        assert.strictEqual(resWithPlan.canDelete, false);
        assert.strictEqual(resWithPlan.reason, '仅终态扫描可删除');
      }
    });
  });

  describe('API Client: scansApi.deleteScan', () => {
    const originalDelete = api.delete;

    test('deleteScan calls DELETE /api/scans/{id}', async () => {
      let capturedUrl = '';
      api.delete = ((url: string) => {
        capturedUrl = url;
        return Promise.resolve({ deleted: true, id: 42 });
      }) as any;

      try {
        const res = await scansApi.deleteScan(42);
        assert.strictEqual(capturedUrl, '/api/scans/42');
        assert.strictEqual(res.deleted, true);
        assert.strictEqual(res.id, 42);
      } finally {
        api.delete = originalDelete;
      }
    });
  });
});
