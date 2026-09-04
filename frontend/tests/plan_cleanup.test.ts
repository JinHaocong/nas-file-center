import test, { describe } from 'node:test';
import assert from 'node:assert';
import { getPlanDeleteAvailability } from '../src/components/plans/plan_cleanup';
import { plansApi } from '../src/api/domain';
import { api } from '../src/api/client';

describe('Plan Lifecycle Cleanup: Policy Matrix & API Contract Tests', () => {
  describe('Policy Matrix: getPlanDeleteAvailability', () => {
    test('null or undefined plan disallows deletion safely', () => {
      const resNull = getPlanDeleteAvailability(null);
      assert.strictEqual(resNull.canDelete, false);
      assert.strictEqual(resNull.reason, '无效的计划状态');

      const resUndef = getPlanDeleteAvailability(undefined);
      assert.strictEqual(resUndef.canDelete, false);
      assert.strictEqual(resUndef.reason, '无效的计划状态');

      const resNoStatus = getPlanDeleteAvailability({} as any);
      assert.strictEqual(resNoStatus.canDelete, false);
      assert.strictEqual(resNoStatus.reason, '无效的计划状态');
    });

    test('pre-execution states (draft, frozen, ready) allow deletion without execution history warning', () => {
      const preExecStatuses = ['draft', 'frozen', 'ready'];
      for (const status of preExecStatuses) {
        const res = getPlanDeleteAvailability({ status });
        assert.strictEqual(res.canDelete, true, `Status ${status} should be deletable`);
        assert.strictEqual(res.hasExecutionHistory, false, `Status ${status} should not have execution history flag`);
        assert.strictEqual(res.reason, undefined);
      }
    });

    test('post-execution / terminal states (partial, completed, failed) allow deletion with execution history warning', () => {
      const postExecStatuses = ['partial', 'completed', 'failed'];
      for (const status of postExecStatuses) {
        const res = getPlanDeleteAvailability({ status });
        assert.strictEqual(res.canDelete, true, `Status ${status} should be deletable`);
        assert.strictEqual(res.hasExecutionHistory, true, `Status ${status} must have execution history flag`);
        assert.strictEqual(res.reason, undefined);
      }
    });

    test('active execution states (validating, executing) are blocked from deletion', () => {
      const activeStatuses = ['validating', 'executing'];
      for (const status of activeStatuses) {
        const res = getPlanDeleteAvailability({ status });
        assert.strictEqual(res.canDelete, false, `Active status ${status} must be blocked`);
        assert.strictEqual(res.reason, '计划正在校验或执行中，禁止删除');
      }
    });

    test('unknown or unrecognized statuses fail closed', () => {
      const unknownStatuses = ['cancelled', 'pending', 'unknown', 'paused'];
      for (const status of unknownStatuses) {
        const res = getPlanDeleteAvailability({ status });
        assert.strictEqual(res.canDelete, false, `Unknown status ${status} must be blocked`);
        assert.strictEqual(res.reason, '未知或不允许删除的计划状态');
      }
    });
  });

  describe('API Client: plansApi endpoints', () => {
    const originalDelete = api.delete;
    const originalPost = api.post;

    test('deletePlan calls DELETE /api/plans/{id}', async () => {
      let capturedUrl = '';
      api.delete = ((url: string) => {
        capturedUrl = url;
        return Promise.resolve({ deleted: true, id: 101 });
      }) as any;

      try {
        const res = await plansApi.deletePlan(101);
        assert.strictEqual(capturedUrl, '/api/plans/101');
        assert.strictEqual(res.deleted, true);
        assert.strictEqual(res.id, 101);
      } finally {
        api.delete = originalDelete;
      }
    });

    test('clearHistory calls POST /api/plans/clear-history with specified statuses', async () => {
      let capturedUrl = '';
      let capturedPayload: any = null;
      api.post = ((url: string, payload: any) => {
        capturedUrl = url;
        capturedPayload = payload;
        return Promise.resolve({ deleted_count: 5 });
      }) as any;

      try {
        const res = await plansApi.clearHistory(['completed', 'failed']);
        assert.strictEqual(capturedUrl, '/api/plans/clear-history');
        assert.deepStrictEqual(capturedPayload, { statuses: ['completed', 'failed'] });
        assert.strictEqual(res.deleted_count, 5);
      } finally {
        api.post = originalPost;
      }
    });
  });
});
