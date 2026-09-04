import assert from 'node:assert/strict';
import { test, describe } from 'node:test';

import {
  computeProgressPercentage,
  isProgressIndeterminate,
  TASK_STATUS_CONFIG,
  WORKER_STATUS_BADGE_MAP,
  CANONICAL_JOB_CAPABILITIES,
  TASK_LOG_LEVEL_MAP,
} from '../src/components/tasks/task_utils';
import { sanitizeContext, isSensitiveKey } from '../src/utils/sanitize';
import {
  formatDuration,
  formatElapsed,
  formatHeartbeatAge,
} from '../src/utils/format';
import { tasksApi } from '../src/api/tasks';
import { api } from '../src/api/client';
import { TaskStatus } from '../src/types/task';

describe('Task Progress & Indeterminate Percentages', () => {
  test('running task with current=0 total=0 returns null percent (strictly no fake percentage)', () => {
    const percent = computeProgressPercentage(0, 0, null);
    assert.strictEqual(percent, null);
    assert.strictEqual(isProgressIndeterminate(0, null), true);
  });

  test('fclones subprocess running state with current=0 total=0 has indeterminate status', () => {
    const isIndeterminate = isProgressIndeterminate(0, null);
    assert.strictEqual(isIndeterminate, true);

    // When total is 0, computeProgressPercentage must never return 0, 50, or 99
    assert.notStrictEqual(computeProgressPercentage(0, 0, null), 0);
    assert.notStrictEqual(computeProgressPercentage(0, 0, null), 50);
    assert.notStrictEqual(computeProgressPercentage(0, 0, null), 99);
  });

  test('completed task with current=4 total=4 calculates exactly 100%', () => {
    const percent = computeProgressPercentage(4, 4, null);
    assert.strictEqual(percent, 100);
    assert.strictEqual(isProgressIndeterminate(4, 100), false);
  });

  test('progress percentage clamps properly between 0 and 100', () => {
    assert.strictEqual(computeProgressPercentage(15, 10, 150), 100);
    assert.strictEqual(computeProgressPercentage(-5, 10, -50), 0);
    assert.strictEqual(computeProgressPercentage(3, 10, 30), 30);
    assert.strictEqual(computeProgressPercentage(1, 4, null), 25);
  });

  test('negative or zero total is treated as indeterminate', () => {
    assert.strictEqual(computeProgressPercentage(10, -1, null), null);
    assert.strictEqual(computeProgressPercentage(0, -5, null), null);
    assert.strictEqual(isProgressIndeterminate(-1, null), true);
    assert.strictEqual(isProgressIndeterminate(0, null), true);
  });
});

describe('Task Status Tags & Mappings', () => {
  const allStatuses: TaskStatus[] = [
    'queued',
    'running',
    'paused',
    'cancel_requested',
    'cancelled',
    'failed',
    'completed',
  ];

  test('all 7 canonical statuses are mapped with distinct labels and AntD colors', () => {
    for (const status of allStatuses) {
      const config = TASK_STATUS_CONFIG[status];
      assert.ok(config, `Status ${status} must have config`);
      assert.ok(config.label && config.label.length > 0);
      assert.ok(config.color && config.color.length > 0);
    }
    // Verify specific visual color mappings
    assert.strictEqual(TASK_STATUS_CONFIG.queued.color, 'default');
    assert.strictEqual(TASK_STATUS_CONFIG.running.color, 'processing');
    assert.strictEqual(TASK_STATUS_CONFIG.paused.color, 'warning');
    assert.strictEqual(TASK_STATUS_CONFIG.cancel_requested.color, 'warning');
    assert.strictEqual(TASK_STATUS_CONFIG.cancelled.color, 'default');
    assert.strictEqual(TASK_STATUS_CONFIG.failed.color, 'error');
    assert.strictEqual(TASK_STATUS_CONFIG.completed.color, 'success');
  });
});

describe('Capabilities Verification', () => {
  test('fclones-scan capabilities contract: cancel=true, retry=true, pause=false, resume=false', () => {
    const fclonesCaps = CANONICAL_JOB_CAPABILITIES['fclones-scan'];
    assert.ok(fclonesCaps);
    assert.strictEqual(fclonesCaps.supports_cancel, true);
    assert.strictEqual(fclonesCaps.supports_retry, true);
    assert.strictEqual(fclonesCaps.supports_pause, false);
    assert.strictEqual(fclonesCaps.supports_resume, false);
  });

  test('index-root capabilities contract: cancel=false, retry=true, pause=false, resume=false', () => {
    const indexCaps = CANONICAL_JOB_CAPABILITIES['index-root'];
    assert.ok(indexCaps);
    assert.strictEqual(indexCaps.supports_cancel, false);
    assert.strictEqual(indexCaps.supports_retry, true);
    assert.strictEqual(indexCaps.supports_pause, false);
    assert.strictEqual(indexCaps.supports_resume, false);
  });
});

describe('Worker Status Health Mappings', () => {
  test('worker health statuses map to success, warning, and error states', () => {
    assert.strictEqual(WORKER_STATUS_BADGE_MAP.online.badgeStatus, 'success');
    assert.strictEqual(WORKER_STATUS_BADGE_MAP.stale.badgeStatus, 'warning');
    assert.strictEqual(WORKER_STATUS_BADGE_MAP.offline.badgeStatus, 'error');
  });

  test('formatHeartbeatAge formats relative age accurately', () => {
    assert.strictEqual(formatHeartbeatAge(null), '-');
    assert.strictEqual(formatHeartbeatAge(undefined), '-');
    assert.strictEqual(formatHeartbeatAge(0.2), '刚刚');
    assert.strictEqual(formatHeartbeatAge(14), '14 秒前');
    assert.strictEqual(formatHeartbeatAge(180), '3 分钟前');
    assert.strictEqual(formatHeartbeatAge(7200), '2 小时前');
  });
});

describe('Sensitive Information Redaction (Sanitization)', () => {
  test('detects sensitive keys case-insensitively', () => {
    assert.strictEqual(isSensitiveKey('password'), true);
    assert.strictEqual(isSensitiveKey('ADMIN_PASSWORD'), true);
    assert.strictEqual(isSensitiveKey('passwd'), true);
    assert.strictEqual(isSensitiveKey('user_token'), true);
    assert.strictEqual(isSensitiveKey('api_key'), true);
    assert.strictEqual(isSensitiveKey('secret_salt'), true);
    assert.strictEqual(isSensitiveKey('cookie'), true);
    assert.strictEqual(isSensitiveKey('session_id'), true);
    assert.strictEqual(isSensitiveKey('auth_bearer'), true);
    assert.strictEqual(isSensitiveKey('authorization'), true);

    // Non sensitive
    assert.strictEqual(isSensitiveKey('path'), false);
    assert.strictEqual(isSensitiveKey('job_type'), false);
    assert.strictEqual(isSensitiveKey('file_count'), false);
    assert.strictEqual(isSensitiveKey('checkpoint_seq'), false);
  });

  test('redacts sensitive values in deep nested objects and arrays', () => {
    const rawData = {
      job_id: 17,
      roots: ['/data/nas/media'],
      user: {
        username: 'admin',
        password: 'SuperSecretPassword123!',
        auth_token: 'xyz987654321',
      },
      headers: [
        { name: 'Content-Type', value: 'application/json' },
        { name: 'Authorization', secret_token: 'Bearer sensitive-token' },
      ],
      safe_metric: 42,
    };

    const sanitized = sanitizeContext(rawData) as typeof rawData;
    assert.strictEqual(sanitized.job_id, 17);
    assert.strictEqual(sanitized.safe_metric, 42);
    assert.strictEqual(sanitized.user.username, 'admin');
    assert.strictEqual(sanitized.user.password, '***REDACTED***');
    assert.strictEqual(sanitized.user.auth_token, '***REDACTED***');
    assert.strictEqual(sanitized.headers[0].value, 'application/json');
    assert.strictEqual(sanitized.headers[1].secret_token, '***REDACTED***');
  });

  test('sanitizer safely handles null, undefined, primitives', () => {
    assert.strictEqual(sanitizeContext(null), null);
    assert.strictEqual(sanitizeContext(undefined), undefined);
    assert.strictEqual(sanitizeContext('regular string'), 'regular string');
    assert.strictEqual(sanitizeContext(12345), 12345);
  });
});

describe('Duration & Elapsed Time Formatting', () => {
  test('formatDuration formats seconds, minutes, hours correctly', () => {
    assert.strictEqual(formatDuration(15), '15s');
    assert.strictEqual(formatDuration(95), '1m 35s');
    assert.strictEqual(formatDuration(3665), '1h 1m 5s');
    assert.strictEqual(formatDuration(-10), '0s');
  });

  test('formatElapsed handles null and finished states', () => {
    assert.strictEqual(formatElapsed(null, null), '-');
    assert.strictEqual(formatElapsed(undefined, undefined), '-');
    assert.strictEqual(
      formatElapsed('2026-09-04T10:00:00Z', '2026-09-04T10:02:30Z'),
      '2m 30s'
    );
  });
});

describe('Tasks API Client Query Parameters & Contract', () => {
  test('listTasks constructs expected query string with server-side pagination and filters', async () => {
    let capturedUrl = '';
    const originalGet = api.get;
    api.get = (url: string) => {
      capturedUrl = url;
      return Promise.resolve({ items: [], page: 2, page_size: 50, total: 0 } as any);
    };

    try {
      await tasksApi.listTasks({
        page: 2,
        pageSize: 50,
        status: 'running',
        jobType: 'fclones-scan',
      });
      assert.strictEqual(
        capturedUrl,
        '/api/tasks?page=2&page_size=50&status=running&job_type=fclones-scan'
      );

      // 'all' filters should be omitted
      await tasksApi.listTasks({
        page: 1,
        pageSize: 50,
        status: 'all',
        jobType: 'all',
      });
      assert.strictEqual(capturedUrl, '/api/tasks?page=1&page_size=50');
    } finally {
      api.get = originalGet;
    }
  });

  test('getTaskLogs constructs expected logs endpoint URL, pagination, and level filter', async () => {
    let capturedUrl = '';
    const originalGet = api.get;
    api.get = (url: string) => {
      capturedUrl = url;
      return Promise.resolve({ items: [], page: 1, page_size: 50, total: 0 } as any);
    };

    try {
      await tasksApi.getTaskLogs(17, { page: 1, pageSize: 50, level: 'error' });
      assert.strictEqual(capturedUrl, '/api/tasks/17/logs?page=1&page_size=50&level=error');

      await tasksApi.getTaskLogs(17, { page: 1, pageSize: 50, level: 'all' });
      assert.strictEqual(capturedUrl, '/api/tasks/17/logs?page=1&page_size=50');
    } finally {
      api.get = originalGet;
    }
  });

  test('getWorkerStatus targets /api/tasks/worker', async () => {
    let capturedUrl = '';
    const originalGet = api.get;
    api.get = (url: string) => {
      capturedUrl = url;
      return Promise.resolve({ status: 'online' } as any);
    };

    try {
      await tasksApi.getWorkerStatus();
      assert.strictEqual(capturedUrl, '/api/tasks/worker');
    } finally {
      api.get = originalGet;
    }
  });

  test('TASK_LOG_LEVEL_MAP maps all levels', () => {
    assert.strictEqual(TASK_LOG_LEVEL_MAP.info.color, 'blue');
    assert.strictEqual(TASK_LOG_LEVEL_MAP.warning.color, 'orange');
    assert.strictEqual(TASK_LOG_LEVEL_MAP.error.color, 'red');
    assert.strictEqual(TASK_LOG_LEVEL_MAP.debug.color, 'default');
  });
});
