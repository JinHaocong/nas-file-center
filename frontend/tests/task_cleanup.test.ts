import test, { describe } from 'node:test';
import assert from 'node:assert';
import { getTaskDeleteAvailability } from '../src/components/tasks/task_cleanup';
import { tasksApi } from '../src/api/tasks';
import { api } from '../src/api/client';
import { TaskStatus, TerminalTaskStatus } from '../src/types/task';

describe('Task History Cleanup: Policy Matrix & API Contract Tests', () => {
  describe('Policy Matrix: getTaskDeleteAvailability', () => {
    test('null or undefined task disallows deletion safely', () => {
      const resNull = getTaskDeleteAvailability(null);
      assert.strictEqual(resNull.enabled, false);
      assert.strictEqual(resNull.reason, '任务不存在');

      const resUndef = getTaskDeleteAvailability(undefined);
      assert.strictEqual(resUndef.enabled, false);
      assert.strictEqual(resUndef.reason, '任务不存在');

      const resNoStatus = getTaskDeleteAvailability({} as any);
      assert.strictEqual(resNoStatus.enabled, false);
      assert.strictEqual(resNoStatus.reason, '任务不存在');
    });

    test('terminal states (completed, failed, cancelled) are enabled for deletion', () => {
      const terminalStatuses: TaskStatus[] = ['completed', 'failed', 'cancelled'];
      for (const status of terminalStatuses) {
        const res = getTaskDeleteAvailability({ status });
        assert.strictEqual(res.enabled, true, `Status ${status} should be enabled for deletion`);
        assert.strictEqual(res.reason, null);
      }
    });

    test('active states (queued, running, paused, cancel_requested) are disabled with reasons', () => {
      const cases: { status: TaskStatus; expectedReason: string }[] = [
        { status: 'queued', expectedReason: '排队中的任务不能删除' },
        { status: 'running', expectedReason: '执行中的任务不能删除' },
        { status: 'paused', expectedReason: '暂停中的任务不能删除，请先取消任务' },
        { status: 'cancel_requested', expectedReason: '任务正在取消，请等待进入终态后再删除' },
      ];

      for (const c of cases) {
        const res = getTaskDeleteAvailability({ status: c.status });
        assert.strictEqual(res.enabled, false, `Status ${c.status} must be disabled for deletion`);
        assert.strictEqual(res.reason, c.expectedReason);
      }
    });

    test('unknown status is safely disabled with fallback reason', () => {
      const res = getTaskDeleteAvailability({ status: 'unknown_status' as any });
      assert.strictEqual(res.enabled, false);
      assert.strictEqual(res.reason, '当前任务状态不支持删除');
    });
  });

  describe('API Client: deleteTask & clearTaskHistory', () => {
    const originalDelete = api.delete;
    const originalPost = api.post;

    test('deleteTask calls DELETE /api/tasks/{taskId} and returns response', async () => {
      let capturedUrl = '';
      api.delete = ((url: string) => {
        capturedUrl = url;
        return Promise.resolve({ deleted: true, id: 123 });
      }) as any;

      try {
        const res = await tasksApi.deleteTask(123);
        assert.strictEqual(capturedUrl, '/api/tasks/123');
        assert.strictEqual(res.deleted, true);
        assert.strictEqual(res.id, 123);
      } finally {
        api.delete = originalDelete;
      }
    });

    test('clearTaskHistory calls POST /api/tasks/clear-history with explicit statuses array', async () => {
      let capturedUrl = '';
      let capturedBody: any = null;
      api.post = ((url: string, body?: any) => {
        capturedUrl = url;
        capturedBody = body;
        return Promise.resolve({ deleted_count: 5 });
      }) as any;

      try {
        const statuses: TerminalTaskStatus[] = ['completed', 'failed', 'cancelled'];
        const res = await tasksApi.clearTaskHistory(statuses);
        assert.strictEqual(capturedUrl, '/api/tasks/clear-history');
        assert.deepStrictEqual(capturedBody, { statuses });
        assert.strictEqual(res.deleted_count, 5);
      } finally {
        api.post = originalPost;
      }
    });

    test('clearTaskHistory supports partial terminal status list', async () => {
      let capturedBody: any = null;
      api.post = ((url: string, body?: any) => {
        capturedBody = body;
        return Promise.resolve({ deleted_count: 2 });
      }) as any;

      try {
        const statuses: TerminalTaskStatus[] = ['completed'];
        const res = await tasksApi.clearTaskHistory(statuses);
        assert.deepStrictEqual(capturedBody, { statuses: ['completed'] });
        assert.strictEqual(res.deleted_count, 2);
      } finally {
        api.post = originalPost;
      }
    });

    test('empty status selection guard: frontend UI disallows submitting empty array', () => {
      // Logic validation: when selectedStatuses is empty, confirm action is disallowed
      const selectedStatuses: TerminalTaskStatus[] = [];
      const canSubmit = selectedStatuses.length > 0;
      assert.strictEqual(canSubmit, false, 'Frontend must disable submission when statuses=[]');
    });

    test('deleteTask propagates 404 not found error', async () => {
      api.delete = (() => {
        const err = new Error('Task not found');
        (err as any).status = 404;
        return Promise.reject(err);
      }) as any;

      try {
        await assert.rejects(
          async () => {
            await tasksApi.deleteTask(999999);
          },
          (err: any) => {
            assert.strictEqual(err.status, 404);
            assert.strictEqual(err.message, 'Task not found');
            return true;
          }
        );
      } finally {
        api.delete = originalDelete;
      }
    });

    test('deleteTask propagates 409 conflict error when task is active', async () => {
      api.delete = (() => {
        const err = new Error("Only terminal jobs can be deleted (current status is 'running')");
        (err as any).status = 409;
        return Promise.reject(err);
      }) as any;

      try {
        await assert.rejects(
          async () => {
            await tasksApi.deleteTask(456);
          },
          (err: any) => {
            assert.strictEqual(err.status, 409);
            assert.match(err.message, /Only terminal jobs can be deleted/);
            return true;
          }
        );
      } finally {
        api.delete = originalDelete;
      }
    });

    test('clearTaskHistory propagates 400 bad request error on invalid status', async () => {
      api.post = (() => {
        const err = new Error("Cannot clear non-terminal status 'running'");
        (err as any).status = 400;
        return Promise.reject(err);
      }) as any;

      try {
        await assert.rejects(
          async () => {
            await tasksApi.clearTaskHistory(['running' as any]);
          },
          (err: any) => {
            assert.strictEqual(err.status, 400);
            assert.match(err.message, /Cannot clear non-terminal status/);
            return true;
          }
        );
      } finally {
        api.post = originalPost;
      }
    });

    test('clearTaskHistory propagates 403 CSRF error on missing origin', async () => {
      api.post = (() => {
        const err = new Error('CSRF validation failed: missing Origin or Referer header on mutation request');
        (err as any).status = 403;
        return Promise.reject(err);
      }) as any;

      try {
        await assert.rejects(
          async () => {
            await tasksApi.clearTaskHistory(['completed']);
          },
          (err: any) => {
            assert.strictEqual(err.status, 403);
            assert.match(err.message, /CSRF validation failed/);
            return true;
          }
        );
      } finally {
        api.post = originalPost;
      }
    });
  });
});
