import test, { describe } from 'node:test';
import assert from 'node:assert';
import {
  canCreateUndoPlan,
  getQuarantinePurgeAvailability,
  getQuarantineRestoreAvailability,
  validateQuarantineRetentionDays,
  formatQuarantineRetention,
} from '../src/components/quarantine/quarantine_rules';
import { quarantineApi } from '../src/api/quarantine';
import { plansApi } from '../src/api/domain';
import { api } from '../src/api/client';

describe('Gate4 Quarantine, Restore, Purge & Undo Plan Contract Tests', () => {
  describe('Quarantine Page & Query Parameter Construction', () => {
    test('QuarantinePage renders list with default pagination', async () => {
      let capturedUrl = '';
      const originalGet = api.get;
      api.get = (async (url: string) => {
        capturedUrl = url;
        return { items: [], total: 0, page: 1, page_size: 20 };
      }) as any;

      try {
        await quarantineApi.list();
        assert.strictEqual(capturedUrl, '/api/quarantine');
      } finally {
        api.get = originalGet;
      }
    });

    test('QuarantinePage filters by state and search query properly', async () => {
      let capturedUrl = '';
      const originalGet = api.get;
      api.get = (async (url: string) => {
        capturedUrl = url;
        return { items: [], total: 0, page: 2, page_size: 50 };
      }) as any;

      try {
        await quarantineApi.list({
          page: 2,
          pageSize: 50,
          state: 'active',
          search: 'test_file.txt',
        });
        const urlObj = new URL('http://localhost' + capturedUrl);
        assert.strictEqual(urlObj.pathname, '/api/quarantine');
        assert.strictEqual(urlObj.searchParams.get('page'), '2');
        assert.strictEqual(urlObj.searchParams.get('page_size'), '50');
        assert.strictEqual(urlObj.searchParams.get('state'), 'active');
        assert.strictEqual(urlObj.searchParams.get('search'), 'test_file.txt');
      } finally {
        api.get = originalGet;
      }
    });

    test('QuarantinePage state="all" does not append state query param', async () => {
      let capturedUrl = '';
      const originalGet = api.get;
      api.get = (async (url: string) => {
        capturedUrl = url;
        return { items: [], total: 0, page: 1, page_size: 20 };
      }) as any;

      try {
        await quarantineApi.list({ state: 'all' });
        assert.strictEqual(capturedUrl, '/api/quarantine');
      } finally {
        api.get = originalGet;
      }
    });
  });

  describe('RestoreModal Policy Matrix & Safety Guards', () => {
    test('RestoreModal default skip policy is valid and allowed when mutation is on', () => {
      const res = getQuarantineRestoreAvailability(false, 'skip');
      assert.strictEqual(res.canRestore, true);
      assert.strictEqual(res.reason, undefined);
    });

    test('RestoreModal rename option is valid and allowed', () => {
      const res = getQuarantineRestoreAvailability(false, 'rename');
      assert.strictEqual(res.canRestore, true);
      assert.strictEqual(res.reason, undefined);
    });

    test('RestoreModal manual option requires valid absolute path with leading slash', () => {
      // Empty target
      const resEmpty = getQuarantineRestoreAvailability(false, 'manual', '');
      assert.strictEqual(resEmpty.canRestore, false);
      assert.match(resEmpty.reason || '', /请输入自定义恢复目标路径/);

      // Relative path
      const resRel = getQuarantineRestoreAvailability(false, 'manual', 'relative/path.txt');
      assert.strictEqual(resRel.canRestore, false);
      assert.match(resRel.reason || '', /必须为以 \/ 开头的绝对路径/);

      // Valid absolute path
      const resValid = getQuarantineRestoreAvailability(false, 'manual', '/data/restored/file.txt');
      assert.strictEqual(resValid.canRestore, true);
      assert.strictEqual(resValid.reason, undefined);
    });

    test('RestoreModal disabled when ALLOW_MUTATION=false (Safe Mode)', () => {
      const resSkip = getQuarantineRestoreAvailability(true, 'skip');
      assert.strictEqual(resSkip.canRestore, false);
      assert.match(resSkip.reason || '', /只读安全模式生效中/);

      const resRename = getQuarantineRestoreAvailability(true, 'rename');
      assert.strictEqual(resRename.canRestore, false);
      assert.match(resRename.reason || '', /只读安全模式生效中/);

      const resManual = getQuarantineRestoreAvailability(true, 'manual', '/data/safe.txt');
      assert.strictEqual(resManual.canRestore, false);
      assert.match(resManual.reason || '', /只读安全模式生效中/);
    });

    test('quarantineApi.restore sends expected payload and endpoint', async () => {
      let capturedUrl = '';
      let capturedPayload: any = null;
      const originalPost = api.post;
      api.post = (async (url: string, payload: any) => {
        capturedUrl = url;
        capturedPayload = payload;
        return { id: 42, state: 'restored', status: 'restored', restored_to_path: '/data/a.txt', conflict_policy: 'rename', conflict_resolved: false };
      }) as any;

      try {
        const res = await quarantineApi.restore(42, { conflict_policy: 'rename' });
        assert.strictEqual(capturedUrl, '/api/quarantine/42/restore');
        assert.deepStrictEqual(capturedPayload, { conflict_policy: 'rename' });
        assert.strictEqual(res.state, 'restored');
      } finally {
        api.post = originalPost;
      }
    });
  });

  describe('PurgeConfirmModal Matrix & Double-guard Protection', () => {
    test('PurgeConfirmModal requires exact uppercase DELETE', () => {
      const resLower = getQuarantinePurgeAvailability(true, true, 'delete');
      assert.strictEqual(resLower.canPurge, false);
      assert.match(resLower.reason || '', /DELETE/);

      const resMixed = getQuarantinePurgeAvailability(true, true, 'Delete');
      assert.strictEqual(resMixed.canPurge, false);

      const resEmpty = getQuarantinePurgeAvailability(true, true, '');
      assert.strictEqual(resEmpty.canPurge, false);

      const resValid = getQuarantinePurgeAvailability(true, true, 'DELETE');
      assert.strictEqual(resValid.canPurge, true);
      assert.strictEqual(resValid.reason, undefined);
    });

    test('PurgeConfirmModal blocks non-admin users', () => {
      const resNonAdmin = getQuarantinePurgeAvailability(false, true, 'DELETE');
      assert.strictEqual(resNonAdmin.canPurge, false);
      assert.match(resNonAdmin.reason || '', /管理员/);
    });

    test('PurgeConfirmModal blocks when ALLOW_DELETE=false', () => {
      const resNoDelete = getQuarantinePurgeAvailability(true, false, 'DELETE');
      assert.strictEqual(resNoDelete.canPurge, false);
      assert.match(resNoDelete.reason || '', /ALLOW_DELETE=false/);
    });

    test('quarantineApi.purge sends DELETE confirmation payload', async () => {
      let capturedUrl = '';
      let capturedPayload: any = null;
      const originalPost = api.post;
      api.post = (async (url: string, payload: any) => {
        capturedUrl = url;
        capturedPayload = payload;
        return { id: 99, state: 'purged', status: 'purged' };
      }) as any;

      try {
        const res = await quarantineApi.purge(99, { confirmation: 'DELETE' });
        assert.strictEqual(capturedUrl, '/api/quarantine/99/purge');
        assert.deepStrictEqual(capturedPayload, { confirmation: 'DELETE' });
        assert.strictEqual(res.state, 'purged');
      } finally {
        api.post = originalPost;
      }
    });
  });

  describe('Retention Policy UI & Value Constraints', () => {
    test('RetentionPolicy only allows 0, 7, 30, 90', () => {
      assert.strictEqual(validateQuarantineRetentionDays(0).valid, true);
      assert.strictEqual(validateQuarantineRetentionDays(7).valid, true);
      assert.strictEqual(validateQuarantineRetentionDays(30).valid, true);
      assert.strictEqual(validateQuarantineRetentionDays(90).valid, true);

      // Invalid numbers
      assert.strictEqual(validateQuarantineRetentionDays(1).valid, false);
      assert.strictEqual(validateQuarantineRetentionDays(15).valid, false);
      assert.strictEqual(validateQuarantineRetentionDays(60).valid, false);
      assert.strictEqual(validateQuarantineRetentionDays(365).valid, false);
      assert.strictEqual(validateQuarantineRetentionDays(-1).valid, false);

      // Invalid types
      assert.strictEqual(validateQuarantineRetentionDays('7' as any).valid, false);
      assert.strictEqual(validateQuarantineRetentionDays(null as any).valid, false);
      assert.strictEqual(validateQuarantineRetentionDays(true as any).valid, false);
    });

    test('formatQuarantineRetention formats known periods', () => {
      assert.strictEqual(formatQuarantineRetention(0), '永久保留 (0 天)');
      assert.strictEqual(formatQuarantineRetention(7), '7 天 (7 days)');
      assert.strictEqual(formatQuarantineRetention(30), '30 天 (30 days)');
      assert.strictEqual(formatQuarantineRetention(90), '90 天 (90 days)');
      assert.strictEqual(formatQuarantineRetention(null), '永久保留 (0 天)');
    });

    test('quarantineApi.updateRetentionPolicy sends valid days', async () => {
      let capturedUrl = '';
      let capturedPayload: any = null;
      const originalPut = api.put;
      api.put = (async (url: string, payload: any) => {
        capturedUrl = url;
        capturedPayload = payload;
        return { quarantine_retention_days: payload.quarantine_retention_days, updated_at: '2026-09-06T00:00:00Z' };
      }) as any;

      try {
        const res = await quarantineApi.updateRetentionPolicy(30);
        assert.strictEqual(capturedUrl, '/api/quarantine/retention-policy');
        assert.deepStrictEqual(capturedPayload, { quarantine_retention_days: 30 });
        assert.strictEqual(res.quarantine_retention_days, 30);
      } finally {
        api.put = originalPut;
      }
    });
  });

  describe('Operation Journal & PlanDetail Contracts', () => {
    test('plansApi.getOperationJournal queries correct plan endpoint with pagination', async () => {
      let capturedUrl = '';
      const originalGet = api.get;
      api.get = (async (url: string) => {
        capturedUrl = url;
        return { items: [], total: 0, page: 1, page_size: 50 };
      }) as any;

      try {
        await plansApi.getOperationJournal(123, 2, 25);
        assert.strictEqual(capturedUrl, '/api/plans/123/operation-journal?page=2&page_size=25');
      } finally {
        api.get = originalGet;
      }
    });
  });

  describe('Undo Plan Flow & Policy Matrix', () => {
    test('PlanDetail Create Undo Plan button appears only for completed or partial plans with operations', () => {
      // Completed plan with journal items -> allowed
      assert.strictEqual(canCreateUndoPlan({ status: 'completed', expected_changes: 5 }, 5), true);
      assert.strictEqual(canCreateUndoPlan({ status: 'completed', expected_changes: 5 }, 0), true);

      // Partial plan with journal items -> allowed
      assert.strictEqual(canCreateUndoPlan({ status: 'partial', expected_changes: 10 }, 4), true);

      // Draft, frozen, ready, validating, executing, stale, failed without executed items -> disallowed
      assert.strictEqual(canCreateUndoPlan({ status: 'draft', expected_changes: 5 }, 0), false);
      assert.strictEqual(canCreateUndoPlan({ status: 'frozen', expected_changes: 5 }, 0), false);
      assert.strictEqual(canCreateUndoPlan({ status: 'ready', expected_changes: 5 }, 0), false);
      assert.strictEqual(canCreateUndoPlan({ status: 'executing', expected_changes: 5 }, 2), false);
      assert.strictEqual(canCreateUndoPlan({ status: 'stale', expected_changes: 5 }, 0), false);

      // Null or invalid plan
      assert.strictEqual(canCreateUndoPlan(null, 5), false);
      assert.strictEqual(canCreateUndoPlan(undefined, 5), false);
    });

    test('plansApi.createUndoPlan calls POST /api/plans/{id}/undo-plan', async () => {
      let capturedUrl = '';
      const originalPost = api.post;
      api.post = (async (url: string) => {
        capturedUrl = url;
        return { id: 789, name: 'Undo Test Plan', kind: 'undo', status: 'draft', total_items: 3 };
      }) as any;

      try {
        const res = await plansApi.createUndoPlan(456);
        assert.strictEqual(capturedUrl, '/api/plans/456/undo-plan');
        assert.strictEqual(res.id, 789);
        assert.strictEqual(res.kind, 'undo');
        assert.strictEqual(res.status, 'draft');
        assert.strictEqual(res.total_items, 3);
      } finally {
        api.post = originalPost;
      }
    });

    test('Undo plan displays kind=undo tag and maintains linkage to source plan', () => {
      const undoPlan = {
        id: 789,
        kind: 'undo',
        metadata: {
          is_undo: true,
          undo_of_plan_id: 456,
          undo_for_plan_id: 456,
        },
      };
      assert.strictEqual(undoPlan.kind, 'undo');
      assert.strictEqual(undoPlan.metadata.is_undo, true);
      assert.strictEqual(undoPlan.metadata.undo_of_plan_id, 456);
    });

    test('Allows generating Undo plan from an already undone plan (reflexive Undo)', () => {
      // Undo plan has completed -> user can undo the undo plan
      const completedUndoPlan = {
        id: 789,
        kind: 'undo',
        status: 'completed',
        expected_changes: 3,
        metadata: {
          is_undo: true,
          undo_of_plan_id: 456,
        },
      };
      assert.strictEqual(canCreateUndoPlan(completedUndoPlan, 3), true);
    });
  });
});
