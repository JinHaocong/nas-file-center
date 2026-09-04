import test, { describe } from 'node:test';
import assert from 'node:assert';
import { getTaskActionAvailability } from '../src/components/tasks/task_actions';
import { tasksApi } from '../src/api/tasks';
import { api } from '../src/api/client';
import { TaskCapabilities, TaskStatus } from '../src/types/task';

describe('Task Capability-driven Actions: Availability Policy Matrix', () => {
  const allCaps: TaskCapabilities = {
    supports_pause: true,
    supports_resume: true,
    supports_cancel: true,
    supports_retry: true,
  };

  const noCaps: TaskCapabilities = {
    supports_pause: false,
    supports_resume: false,
    supports_cancel: false,
    supports_retry: false,
  };

  test('null or undefined task disallows all actions safely', () => {
    const actions = ['pause', 'resume', 'cancel', 'retry'] as const;
    for (const act of actions) {
      const resNull = getTaskActionAvailability(null, act);
      assert.strictEqual(resNull.enabled, false);
      assert.strictEqual(resNull.reason, '任务不存在');

      const resUndef = getTaskActionAvailability(undefined, act);
      assert.strictEqual(resUndef.enabled, false);
      assert.strictEqual(resUndef.reason, '任务不存在');
    }
  });

  describe('Pause Action Matrix', () => {
    test('supports_pause=false + running => disabled (capability reason)', () => {
      const res = getTaskActionAvailability({ capabilities: noCaps, status: 'running' }, 'pause');
      assert.strictEqual(res.enabled, false);
      assert.strictEqual(res.reason, '此任务类型不支持暂停');
    });

    test('supports_pause=true + running => enabled', () => {
      const res = getTaskActionAvailability({ capabilities: allCaps, status: 'running' }, 'pause');
      assert.strictEqual(res.enabled, true);
      assert.strictEqual(res.reason, null);
    });

    test('supports_pause=true + queued => enabled', () => {
      const res = getTaskActionAvailability({ capabilities: allCaps, status: 'queued' }, 'pause');
      assert.strictEqual(res.enabled, true);
      assert.strictEqual(res.reason, null);
    });

    test('supports_pause=true + paused => disabled (already paused)', () => {
      const res = getTaskActionAvailability({ capabilities: allCaps, status: 'paused' }, 'pause');
      assert.strictEqual(res.enabled, false);
      assert.strictEqual(res.reason, '任务已经暂停');
    });

    test('supports_pause=true + cancel_requested => disabled (cancelling)', () => {
      const res = getTaskActionAvailability({ capabilities: allCaps, status: 'cancel_requested' }, 'pause');
      assert.strictEqual(res.enabled, false);
      assert.strictEqual(res.reason, '当前任务正在取消');
    });

    test('supports_pause=true + terminal statuses (completed, failed, cancelled) => disabled', () => {
      for (const status of ['completed', 'failed', 'cancelled'] as TaskStatus[]) {
        const res = getTaskActionAvailability({ capabilities: allCaps, status }, 'pause');
        assert.strictEqual(res.enabled, false);
        assert.strictEqual(res.reason, '终态任务不可暂停');
      }
    });
  });

  describe('Resume Action Matrix', () => {
    test('supports_resume=false + paused => disabled (capability reason)', () => {
      const res = getTaskActionAvailability({ capabilities: noCaps, status: 'paused' }, 'resume');
      assert.strictEqual(res.enabled, false);
      assert.strictEqual(res.reason, '此任务类型不支持恢复');
    });

    test('supports_resume=true + paused => enabled', () => {
      const res = getTaskActionAvailability({ capabilities: allCaps, status: 'paused' }, 'resume');
      assert.strictEqual(res.enabled, true);
      assert.strictEqual(res.reason, null);
    });

    test('supports_resume=true + running => disabled (only paused allowed)', () => {
      const res = getTaskActionAvailability({ capabilities: allCaps, status: 'running' }, 'resume');
      assert.strictEqual(res.enabled, false);
      assert.strictEqual(res.reason, '仅暂停状态的任务可以恢复');
    });

    test('supports_resume=true + queued => disabled (only paused allowed)', () => {
      const res = getTaskActionAvailability({ capabilities: allCaps, status: 'queued' }, 'resume');
      assert.strictEqual(res.enabled, false);
      assert.strictEqual(res.reason, '仅暂停状态的任务可以恢复');
    });

    test('supports_resume=true + cancel_requested => disabled (cancelling)', () => {
      const res = getTaskActionAvailability({ capabilities: allCaps, status: 'cancel_requested' }, 'resume');
      assert.strictEqual(res.enabled, false);
      assert.strictEqual(res.reason, '当前任务正在取消');
    });

    test('supports_resume=true + terminal statuses => disabled', () => {
      for (const status of ['completed', 'failed', 'cancelled'] as TaskStatus[]) {
        const res = getTaskActionAvailability({ capabilities: allCaps, status }, 'resume');
        assert.strictEqual(res.enabled, false);
        assert.strictEqual(res.reason, '终态任务不可恢复');
      }
    });
  });

  describe('Cancel Action Matrix', () => {
    test('supports_cancel=false + running => disabled (capability reason)', () => {
      const res = getTaskActionAvailability({ capabilities: noCaps, status: 'running' }, 'cancel');
      assert.strictEqual(res.enabled, false);
      assert.strictEqual(res.reason, '此任务类型不支持取消');
    });

    test('supports_cancel=true + queued => enabled', () => {
      const res = getTaskActionAvailability({ capabilities: allCaps, status: 'queued' }, 'cancel');
      assert.strictEqual(res.enabled, true);
      assert.strictEqual(res.reason, null);
    });

    test('supports_cancel=true + running => enabled', () => {
      const res = getTaskActionAvailability({ capabilities: allCaps, status: 'running' }, 'cancel');
      assert.strictEqual(res.enabled, true);
      assert.strictEqual(res.reason, null);
    });

    test('supports_cancel=true + paused => enabled', () => {
      const res = getTaskActionAvailability({ capabilities: allCaps, status: 'paused' }, 'cancel');
      assert.strictEqual(res.enabled, true);
      assert.strictEqual(res.reason, null);
    });

    test('supports_cancel=true + cancel_requested => disabled (cannot cancel repeatedly)', () => {
      const res = getTaskActionAvailability({ capabilities: allCaps, status: 'cancel_requested' }, 'cancel');
      assert.strictEqual(res.enabled, false);
      assert.strictEqual(res.reason, '当前任务正在取消');
    });

    test('supports_cancel=true + cancelled => disabled (already cancelled)', () => {
      const res = getTaskActionAvailability({ capabilities: allCaps, status: 'cancelled' }, 'cancel');
      assert.strictEqual(res.enabled, false);
      assert.strictEqual(res.reason, '任务已取消');
    });

    test('supports_cancel=true + terminal statuses (completed, failed) => disabled', () => {
      for (const status of ['completed', 'failed'] as TaskStatus[]) {
        const res = getTaskActionAvailability({ capabilities: allCaps, status }, 'cancel');
        assert.strictEqual(res.enabled, false);
        assert.strictEqual(res.reason, '终态任务不可取消');
      }
    });
  });

  describe('Retry Action Matrix', () => {
    test('supports_retry=false + failed => disabled (capability reason)', () => {
      const res = getTaskActionAvailability({ capabilities: noCaps, status: 'failed' }, 'retry');
      assert.strictEqual(res.enabled, false);
      assert.strictEqual(res.reason, '此任务类型不支持重试');
    });

    test('supports_retry=true + failed => enabled', () => {
      const res = getTaskActionAvailability({ capabilities: allCaps, status: 'failed' }, 'retry');
      assert.strictEqual(res.enabled, true);
      assert.strictEqual(res.reason, null);
    });

    test('supports_retry=true + completed => disabled (already completed)', () => {
      const res = getTaskActionAvailability({ capabilities: allCaps, status: 'completed' }, 'retry');
      assert.strictEqual(res.enabled, false);
      assert.strictEqual(res.reason, '已完成的任务无需重试');
    });

    test('supports_retry=true + active statuses (running, queued, paused) => disabled', () => {
      for (const status of ['running', 'queued', 'paused'] as TaskStatus[]) {
        const res = getTaskActionAvailability({ capabilities: allCaps, status }, 'retry');
        assert.strictEqual(res.enabled, false);
        assert.strictEqual(res.reason, '运行中或未失败的任务不可重试');
      }
    });

    test('supports_retry=true + cancelled => disabled', () => {
      const res = getTaskActionAvailability({ capabilities: allCaps, status: 'cancelled' }, 'retry');
      assert.strictEqual(res.enabled, false);
      assert.strictEqual(res.reason, '已取消的任务不可重试');
    });

    test('supports_retry=true + cancel_requested => disabled', () => {
      const res = getTaskActionAvailability({ capabilities: allCaps, status: 'cancel_requested' }, 'retry');
      assert.strictEqual(res.enabled, false);
      assert.strictEqual(res.reason, '仅失败任务可以重试');
    });
  });
});

describe('Tasks API Client Mutation Contract & Mock Tests', () => {
  const originalPost = api.post;

  test('pauseTask calls POST /api/tasks/{id}/pause without body and returns TaskItem', async () => {
    let capturedUrl = '';
    let capturedBody: unknown = null;
    api.post = ((url: string, body?: unknown) => {
      capturedUrl = url;
      capturedBody = body;
      return Promise.resolve({
        id: 123,
        job_type: 'fclones-scan',
        status: 'paused',
      } as any);
    }) as any;

    try {
      const result = await tasksApi.pauseTask(123);
      assert.strictEqual(capturedUrl, '/api/tasks/123/pause');
      assert.strictEqual(capturedBody, undefined);
      assert.strictEqual(result.id, 123);
      assert.strictEqual(result.status, 'paused');
    } finally {
      api.post = originalPost;
    }
  });

  test('resumeTask calls POST /api/tasks/{id}/resume without body and returns TaskItem', async () => {
    let capturedUrl = '';
    let capturedBody: unknown = null;
    api.post = ((url: string, body?: unknown) => {
      capturedUrl = url;
      capturedBody = body;
      return Promise.resolve({
        id: 123,
        job_type: 'fclones-scan',
        status: 'queued',
      } as any);
    }) as any;

    try {
      const result = await tasksApi.resumeTask(123);
      assert.strictEqual(capturedUrl, '/api/tasks/123/resume');
      assert.strictEqual(capturedBody, undefined);
      assert.strictEqual(result.id, 123);
      assert.strictEqual(result.status, 'queued');
    } finally {
      api.post = originalPost;
    }
  });

  test('cancelTask calls POST /api/tasks/{id}/cancel and supports cancel_requested & cancelled', async () => {
    let capturedUrl = '';
    api.post = ((url: string) => {
      capturedUrl = url;
      return Promise.resolve({
        id: 123,
        job_type: 'fclones-scan',
        status: 'cancel_requested',
      } as any);
    }) as any;

    try {
      const result = await tasksApi.cancelTask(123);
      assert.strictEqual(capturedUrl, '/api/tasks/123/cancel');
      assert.strictEqual(result.status, 'cancel_requested');
    } finally {
      api.post = originalPost;
    }
  });

  test('retryTask calls POST /api/tasks/{id}/retry and returns new job structure', async () => {
    let capturedUrl = '';
    api.post = ((url: string) => {
      capturedUrl = url;
      return Promise.resolve({
        job: {
          id: 456,
          job_type: 'fclones-scan',
          status: 'queued',
          retry_of: 123,
        },
        retry_of: 123,
      } as any);
    }) as any;

    try {
      const result = await tasksApi.retryTask(123);
      assert.strictEqual(capturedUrl, '/api/tasks/123/retry');
      assert.strictEqual(result.job.id, 456);
      assert.strictEqual(result.retry_of, 123);
      assert.strictEqual(result.job.status, 'queued');
    } finally {
      api.post = originalPost;
    }
  });

  test('mutation errors (409 conflict, 404 not found) are propagated without swallowing', async () => {
    api.post = (() => {
      const err = new Error('Terminal job in state completed cannot be cancelled');
      (err as any).status = 409;
      return Promise.reject(err);
    }) as any;

    try {
      await assert.rejects(
        async () => {
          await tasksApi.cancelTask(123);
        },
        {
          message: 'Terminal job in state completed cannot be cancelled',
        }
      );
    } finally {
      api.post = originalPost;
    }
  });

  test('TASK-033-UI-06 isolation assertion: deleteTask and clearHistory are NOT exposed on tasksApi', () => {
    const apiObj = tasksApi as Record<string, unknown>;
    assert.strictEqual(apiObj.deleteTask, undefined, 'deleteTask must NOT be exposed in frontend');
    assert.strictEqual(apiObj.clearHistory, undefined, 'clearHistory must NOT be exposed in frontend');
    assert.strictEqual(apiObj.clearTaskHistory, undefined, 'clearTaskHistory must NOT be exposed in frontend');
  });
});
