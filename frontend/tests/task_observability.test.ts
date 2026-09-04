import assert from 'node:assert/strict';
import { test, describe } from 'node:test';

import {
  computeProgressPercentage,
  isProgressIndeterminate,
  calculateTaskEta,
  TASK_STATUS_CONFIG,
  WORKER_STATUS_BADGE_MAP,
  CANONICAL_JOB_CAPABILITIES,
  TASK_LOG_LEVEL_MAP,
} from '../src/components/tasks/task_utils';
import dayjs from 'dayjs';
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

describe('Task ETA Estimation & Deterministic Rules', () => {
  const baseTime = dayjs('2026-09-04T12:00:00Z');

  test('1. known total + running + valid elapsed returns finite ETA', () => {
    // Started 60 seconds ago, processed 50 out of 100 items -> remaining 50 -> rate 50/60s -> eta 60s ('1m')
    const startedAt = baseTime.subtract(60, 'second').toISOString();
    const result = calculateTaskEta('running', 50, 100, startedAt, 50, baseTime);

    assert.strictEqual(result.isUnknown, false);
    assert.strictEqual(result.etaSeconds, 60);
    assert.strictEqual(result.text, '1m 0s');

    // Started 120 seconds ago, processed 30 out of 150 items -> remaining 120 -> rate 30/120s -> eta 480s ('8m')
    const startedAt2 = baseTime.subtract(120, 'second').toISOString();
    const result2 = calculateTaskEta('running', 30, 150, startedAt2, 20, baseTime);
    assert.strictEqual(result2.isUnknown, false);
    assert.strictEqual(result2.etaSeconds, 480);
    assert.strictEqual(result2.text, '8m 0s');
  });

  test('2. total == 0 returns ETA unknown', () => {
    const startedAt = baseTime.subtract(30, 'second').toISOString();
    const res1 = calculateTaskEta('running', 0, 0, startedAt, null, baseTime);
    assert.strictEqual(res1.isUnknown, true);
    assert.strictEqual(res1.etaSeconds, null);
    assert.strictEqual(res1.text, '未知');

    const res2 = calculateTaskEta('running', 10, 0, startedAt, null, baseTime);
    assert.strictEqual(res2.isUnknown, true);
    assert.strictEqual(res2.etaSeconds, null);
    assert.strictEqual(res2.text, '未知');
  });

  test('3. percent == null / unknown progress returns ETA unknown', () => {
    const startedAt = baseTime.subtract(40, 'second').toISOString();
    // Test A: running, current=50, total=100, percent=null, valid started_at => unknown
    const resA = calculateTaskEta('running', 50, 100, startedAt, null, baseTime);
    assert.strictEqual(resA.isUnknown, true);
    assert.strictEqual(resA.etaSeconds, null);
    assert.strictEqual(resA.text, '未知');

    // Test B: running, current=50, total=100, percent=undefined, valid started_at => unknown
    const resB = calculateTaskEta('running', 50, 100, startedAt, undefined, baseTime);
    assert.strictEqual(resB.isUnknown, true);
    assert.strictEqual(resB.etaSeconds, null);
    assert.strictEqual(resB.text, '未知');

    // Zero current & zero total with null percent
    const resZero = calculateTaskEta('running', 0, 0, startedAt, null, baseTime);
    assert.strictEqual(resZero.isUnknown, true);
    assert.strictEqual(resZero.etaSeconds, null);
    assert.strictEqual(resZero.text, '未知');
  });

  test('4. current == 0 returns ETA unknown (no velocity sample)', () => {
    const startedAt = baseTime.subtract(10, 'second').toISOString();
    const res = calculateTaskEta('running', 0, 100, startedAt, 0, baseTime);
    assert.strictEqual(res.isUnknown, true);
    assert.strictEqual(res.etaSeconds, null);
    assert.strictEqual(res.text, '未知');
  });

  test('5. missing or invalid started_at returns ETA unknown', () => {
    const res1 = calculateTaskEta('running', 50, 100, null, 50, baseTime);
    assert.strictEqual(res1.isUnknown, true);
    assert.strictEqual(res1.text, '未知');

    const res2 = calculateTaskEta('running', 50, 100, undefined, 50, baseTime);
    assert.strictEqual(res2.isUnknown, true);
    assert.strictEqual(res2.text, '未知');

    const res3 = calculateTaskEta('running', 50, 100, 'not-a-valid-date', 50, baseTime);
    assert.strictEqual(res3.isUnknown, true);
    assert.strictEqual(res3.text, '未知');
  });

  test('6. completed or current >= total returns deterministic completed behavior', () => {
    // Completed status
    const completedRes = calculateTaskEta('completed', 100, 100, null, 100, baseTime);
    assert.strictEqual(completedRes.isUnknown, false);
    assert.strictEqual(completedRes.etaSeconds, 0);
    assert.strictEqual(completedRes.text, '已完成');

    // Running but already finished count
    const startedAt = baseTime.subtract(50, 'second').toISOString();
    const finishRes = calculateTaskEta('running', 100, 100, startedAt, 100, baseTime);
    assert.strictEqual(finishRes.isUnknown, false);
    assert.strictEqual(finishRes.etaSeconds, 0);
    assert.strictEqual(finishRes.text, '0s');

    // Running with current exceeding total
    const exceedRes = calculateTaskEta('running', 120, 100, startedAt, 100, baseTime);
    assert.strictEqual(exceedRes.isUnknown, false);
    assert.strictEqual(exceedRes.etaSeconds, 0);
    assert.strictEqual(exceedRes.text, '0s');

    // Test C: running, current=100, total=100, percent=100, started_at=null -> 0s
    const resC = calculateTaskEta('running', 100, 100, null, 100, baseTime);
    assert.strictEqual(resC.isUnknown, false);
    assert.strictEqual(resC.etaSeconds, 0);
    assert.strictEqual(resC.text, '0s');

    // Test D: running, current=120, total=100, percent=100, started_at=invalid -> 0s
    const resD = calculateTaskEta('running', 120, 100, 'invalid-date-string', 100, baseTime);
    assert.strictEqual(resD.isUnknown, false);
    assert.strictEqual(resD.etaSeconds, 0);
    assert.strictEqual(resD.text, '0s');
  });

  test('7. failed, cancelled, paused, and cancel_requested return deterministic state-specific text', () => {
    const failedRes = calculateTaskEta('failed', 10, 100, null, 10, baseTime);
    assert.strictEqual(failedRes.isUnknown, true);
    assert.strictEqual(failedRes.text, '不可用');

    const cancelledRes = calculateTaskEta('cancelled', 10, 100, null, 10, baseTime);
    assert.strictEqual(cancelledRes.isUnknown, true);
    assert.strictEqual(cancelledRes.text, '不可用');

    const pausedRes = calculateTaskEta('paused', 10, 100, null, 10, baseTime);
    assert.strictEqual(pausedRes.isUnknown, true);
    assert.strictEqual(pausedRes.text, '已暂停');

    const cancelReqRes = calculateTaskEta('cancel_requested', 10, 100, null, 10, baseTime);
    assert.strictEqual(cancelReqRes.isUnknown, true);
    assert.strictEqual(cancelReqRes.text, '正在取消');
  });

  test('8. invalid timestamps never return NaN, Infinity, or negative numbers', () => {
    // Zero elapsed time (now == started_at)
    const startedAt = baseTime.toISOString();
    const res1 = calculateTaskEta('running', 5, 100, startedAt, 5, baseTime);
    assert.strictEqual(res1.isUnknown, true);
    assert.strictEqual(res1.text, '未知');
    assert.strictEqual(Number.isNaN(res1.etaSeconds), false);

    // Future timestamp (started_at in the future -> elapsed < 0)
    const futureStartedAt = baseTime.add(60, 'second').toISOString();
    const res2 = calculateTaskEta('running', 5, 100, futureStartedAt, 5, baseTime);
    assert.strictEqual(res2.isUnknown, true);
    assert.strictEqual(res2.text, '未知');
    assert.strictEqual(Number.isNaN(res2.etaSeconds), false);

    // Huge numbers
    const res3 = calculateTaskEta('running', 1, 1000000, baseTime.subtract(1, 'second').toISOString(), 0, baseTime);
    assert.strictEqual(Number.isFinite(res3.etaSeconds), true);
    assert.ok((res3.etaSeconds ?? 0) >= 0);
  });

  test('9. supports options object parameter convention', () => {
    const startedAt = baseTime.subtract(60, 'second').toISOString();
    const result = calculateTaskEta({
      status: 'running',
      current: 50,
      total: 100,
      startedAt,
      percent: 50,
      now: baseTime,
    });
    assert.strictEqual(result.isUnknown, false);
    assert.strictEqual(result.etaSeconds, 60);
    assert.strictEqual(result.text, '1m 0s');
  });

  test('10. mandatory boundary checks A, B, C, D, E (step2-fixed3 review verification)', () => {
    const startedAt = baseTime.subtract(60, 'second').toISOString();

    // A: running, current=50, total=100, percent=null, valid started_at => unknown
    const checkA = calculateTaskEta('running', 50, 100, startedAt, null, baseTime);
    assert.strictEqual(checkA.isUnknown, true);
    assert.strictEqual(checkA.text, '未知');
    assert.strictEqual(checkA.etaSeconds, null);

    // B: running, current=50, total=100, percent=undefined, valid started_at => unknown
    const checkB = calculateTaskEta('running', 50, 100, startedAt, undefined, baseTime);
    assert.strictEqual(checkB.isUnknown, true);
    assert.strictEqual(checkB.text, '未知');
    assert.strictEqual(checkB.etaSeconds, null);

    // C: running, current=100, total=100, percent=100, started_at=null => 0s
    const checkC = calculateTaskEta('running', 100, 100, null, 100, baseTime);
    assert.strictEqual(checkC.isUnknown, false);
    assert.strictEqual(checkC.text, '0s');
    assert.strictEqual(checkC.etaSeconds, 0);

    // D: running, current=120, total=100, percent=100, started_at=invalid => 0s
    const checkD = calculateTaskEta('running', 120, 100, 'invalid-date-string', 100, baseTime);
    assert.strictEqual(checkD.isUnknown, false);
    assert.strictEqual(checkD.text, '0s');
    assert.strictEqual(checkD.etaSeconds, 0);

    // E: running, current=50, total=100, percent=50, elapsed=60s => eta 60s ('1m 0s')
    const checkE = calculateTaskEta('running', 50, 100, startedAt, 50, baseTime);
    assert.strictEqual(checkE.isUnknown, false);
    assert.strictEqual(checkE.text, '1m 0s');
    assert.strictEqual(checkE.etaSeconds, 60);
  });
});
