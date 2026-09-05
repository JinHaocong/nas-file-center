import test, { describe } from 'node:test';
import assert from 'node:assert';
import {
  getPlanDeleteAvailability,
  getPlanDeleteConfirmationContent,
  invalidatePlanDeleteFailure,
  isPlanNotFoundError,
  getPlanDetailRenderState,
  getPlanDetailView,
} from '../src/components/plans/plan_cleanup';
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

    test('plan with active_work_job_id is blocked from deletion even in deletable statuses', () => {
      const testStatuses = ['draft', 'frozen', 'ready', 'partial', 'completed', 'failed'];
      for (const status of testStatuses) {
        const res = getPlanDeleteAvailability({ status, active_work_job_id: 123 });
        assert.strictEqual(res.canDelete, false, `Status ${status} with active_work_job_id must be blocked`);
        assert.strictEqual(res.reason, '计划正在任务队列中执行，禁止删除');
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

  describe('Truthful Destructive UI: Plan Delete Confirmation Copy', () => {
    test('executed plan confirmation clarifies Audit is preserved and does NOT claim audit is cleaned', () => {
      const executedStatuses = ['partial', 'completed', 'failed'];
      for (const status of executedStatuses) {
        const content = getPlanDeleteConfirmationContent({ id: 123, status });
        assert.ok(content.title.includes('#123'), 'Title must identify plan ID');
        assert.ok(
          !content.description.includes('清理计划记录与审计流水'),
          'Must not claim audit log is cleaned up'
        );
        assert.ok(
          content.description.includes('Audit 审计记录仍会保留'),
          'Must explicitly clarify Audit log is preserved'
        );
        assert.ok(
          content.description.includes('Delete ≠ Undo'),
          'Must clearly state Delete ≠ Undo'
        );
        assert.ok(
          content.description.includes('不会撤销已经执行的 NAS 文件操作'),
          'Must clearly state executed operations are not reverted'
        );
      }
    });

    test('pre-execution plan confirmation clarifies Audit is unaffected and NAS files untouched', () => {
      const preExecStatuses = ['draft', 'frozen', 'ready'];
      for (const status of preExecStatuses) {
        const content = getPlanDeleteConfirmationContent({ id: 456, status });
        assert.ok(content.title.includes('#456'), 'Title must identify plan ID');
        assert.ok(
          content.description.includes('Audit 审计记录不会受到影响'),
          'Must state Audit records are unaffected'
        );
        assert.ok(
          content.description.includes('不会修改 NAS 上的任何真实文件'),
          'Must state NAS files are not modified'
        );
      }
    });
  });

  describe('Stale-State Prevention: Invalidation on Plan Delete Failure', () => {
    test('invalidatePlanDeleteFailure refreshes both plansList and planDetail queries', () => {
      const invalidatedKeys: any[] = [];
      const mockQueryClient = {
        invalidateQueries: (filters: { queryKey: any[] }) => {
          invalidatedKeys.push(filters.queryKey);
        },
      };

      invalidatePlanDeleteFailure(mockQueryClient, 88);

      const hasPlansList = invalidatedKeys.some(
        (key) => Array.isArray(key) && key[0] === 'plansList'
      );
      const hasPlanDetailWithId = invalidatedKeys.some(
        (key) => Array.isArray(key) && key[0] === 'planDetail' && key[1] === 88
      );
      const hasPlanDetailPrefix = invalidatedKeys.some(
        (key) => Array.isArray(key) && key[0] === 'planDetail'
      );

      assert.ok(hasPlansList, 'Must invalidate plansList query key');
      assert.ok(hasPlanDetailWithId || hasPlanDetailPrefix, 'Must invalidate planDetail query key');
    });
  });

  describe('Plan Detail 404 & Error State Priority Tests (Stale Cache Prevention)', () => {
    test('isPlanNotFoundError accurately detects 404 status from ApiError or response', () => {
      assert.strictEqual(isPlanNotFoundError({ status: 404, message: 'Not found' }), true);
      assert.strictEqual(isPlanNotFoundError({ response: { status: 404 } }), true);
      assert.strictEqual(isPlanNotFoundError({ status: 500, message: 'Server error' }), false);
      assert.strictEqual(isPlanNotFoundError({ status: 409, message: 'Conflict' }), false);
      assert.strictEqual(isPlanNotFoundError({ status: 403, message: 'Forbidden' }), false);
      assert.strictEqual(isPlanNotFoundError(null), false);
      assert.strictEqual(isPlanNotFoundError(undefined), false);
      assert.strictEqual(isPlanNotFoundError('404'), false);
    });

    test('Case A: no cache + 404 returns not-found', () => {
      const state = getPlanDetailRenderState({
        isLoading: false,
        isError: true,
        error: { status: 404, message: 'Plan not found' },
        hasPlan: false,
      });
      assert.strictEqual(state, 'not-found');
    });

    test('Case B: stale cache exists + 404 returns not-found (404 truth overrides stale data)', () => {
      const state = getPlanDetailRenderState({
        isLoading: false,
        isError: true,
        error: { status: 404, message: 'Plan not found' },
        hasPlan: true, // Stale cached plan in TanStack Query
      });
      assert.strictEqual(state, 'not-found', '404 backend truth must override stale cached plan data');
    });

    test('Case C: stale cache exists + 500 returns error (latest backend error overrides stale data)', () => {
      const state = getPlanDetailRenderState({
        isLoading: false,
        isError: true,
        error: { status: 500, message: 'Internal Server Error' },
        hasPlan: true,
      });
      assert.strictEqual(state, 'error', 'Latest server error must override stale cached plan data');
    });

    test('Case D: plan exists + no error returns ready', () => {
      const state = getPlanDetailRenderState({
        isLoading: false,
        isError: false,
        error: null,
        hasPlan: true,
      });
      assert.strictEqual(state, 'ready');
    });

    test('Case E: isLoading returns loading regardless of cached data or error', () => {
      const state = getPlanDetailRenderState({
        isLoading: true,
        isError: false,
        error: null,
        hasPlan: true,
      });
      assert.strictEqual(state, 'loading');
    });

    test('Case F: no plan + no error returns empty', () => {
      const state = getPlanDetailRenderState({
        isLoading: false,
        isError: false,
        error: null,
        hasPlan: false,
      });
      assert.strictEqual(state, 'empty');
    });

    test('Case G: no cache (hasPlan: false) + 500 server error yields view "error", NOT "not-found"', () => {
      const renderState = getPlanDetailRenderState({
        isLoading: false,
        isError: true,
        error: { status: 500, message: 'Internal Server Error' },
        hasPlan: false,
      });
      assert.strictEqual(renderState, 'error');

      const view = getPlanDetailView(renderState, false);
      assert.strictEqual(view, 'error', '500 server error without cached plan must display error view, NOT not-found');
    });

    test('Case H: no cache (hasPlan: false) + network error yields view "error", NOT "not-found"', () => {
      const renderState = getPlanDetailRenderState({
        isLoading: false,
        isError: true,
        error: new Error('Network Error: Failed to fetch'),
        hasPlan: false,
      });
      assert.strictEqual(renderState, 'error');

      const view = getPlanDetailView(renderState, false);
      assert.strictEqual(view, 'error', 'Network error without cached plan must display error view, NOT not-found');
    });

    test('Case I: stale cache (hasPlan: true) + 500 server error yields view "error"', () => {
      const renderState = getPlanDetailRenderState({
        isLoading: false,
        isError: true,
        error: { status: 500, message: 'Internal Server Error' },
        hasPlan: true,
      });
      assert.strictEqual(renderState, 'error');

      const view = getPlanDetailView(renderState, true);
      assert.strictEqual(view, 'error', '500 error with stale cache must display error view');
    });

    test('Case J: 404 error yields view "not-found" (both with and without cache)', () => {
      const viewNoCache = getPlanDetailView('not-found', false);
      assert.strictEqual(viewNoCache, 'not-found');

      const viewWithCache = getPlanDetailView('not-found', true);
      assert.strictEqual(viewWithCache, 'not-found');
    });

    test('Case K: loading state yields view "loading" regardless of hasPlan', () => {
      assert.strictEqual(getPlanDetailView('loading', false), 'loading');
      assert.strictEqual(getPlanDetailView('loading', true), 'loading');
    });

    test('Case L: empty / no plan without error yields view "not-found"', () => {
      assert.strictEqual(getPlanDetailView('empty', false), 'not-found');
      assert.strictEqual(getPlanDetailView('ready', false), 'not-found');
    });

    test('Case M: ready state with plan yields view "ready"', () => {
      assert.strictEqual(getPlanDetailView('ready', true), 'ready');
    });
  });
});
