import test, { describe } from 'node:test';
import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  formatAuditRetention,
  validateRetentionDaysInput,
  getAuditRetentionApplyAvailability,
} from '../src/components/settings/data_lifecycle';
import { dataLifecycleApi, auditApi } from '../src/api/domain';
import { api } from '../src/api/client';

describe('Data Lifecycle & Audit Retention: Frontend Unit Tests', () => {
  describe('Helper: formatAuditRetention', () => {
    test('0 days formats to 永久保留', () => {
      assert.strictEqual(formatAuditRetention(0), '永久保留');
    });

    test('positive days format to 保留最近 N 天', () => {
      assert.strictEqual(formatAuditRetention(30), '保留最近 30 天');
      assert.strictEqual(formatAuditRetention(90), '保留最近 90 天');
      assert.strictEqual(formatAuditRetention(365), '保留最近 365 天');
    });

    test('null or undefined format to 未配置', () => {
      assert.strictEqual(formatAuditRetention(null), '未配置');
      assert.strictEqual(formatAuditRetention(undefined), '未配置');
    });

    test('negative numbers format to 非法配置', () => {
      assert.strictEqual(formatAuditRetention(-1), '非法配置');
    });
  });

  describe('Helper: validateRetentionDaysInput', () => {
    test('valid integers between 0 and 3650 pass', () => {
      assert.strictEqual(validateRetentionDaysInput(0).valid, true);
      assert.strictEqual(validateRetentionDaysInput(1).valid, true);
      assert.strictEqual(validateRetentionDaysInput(90).valid, true);
      assert.strictEqual(validateRetentionDaysInput(3650).valid, true);
      assert.strictEqual(validateRetentionDaysInput('90').valid, true);
    });

    test('negative numbers and values > 3650 fail', () => {
      assert.strictEqual(validateRetentionDaysInput(-1).valid, false);
      assert.strictEqual(validateRetentionDaysInput(3651).valid, false);
    });

    test('non-integer, empty, null, undefined fail', () => {
      assert.strictEqual(validateRetentionDaysInput(90.5).valid, false);
      assert.strictEqual(validateRetentionDaysInput('abc').valid, false);
      assert.strictEqual(validateRetentionDaysInput('').valid, false);
      assert.strictEqual(validateRetentionDaysInput(null).valid, false);
      assert.strictEqual(validateRetentionDaysInput(undefined).valid, false);
    });
  });

  describe('Helper: getAuditRetentionApplyAvailability', () => {
    test('policy null or 0 days strictly disables apply retention', () => {
      const resNull = getAuditRetentionApplyAvailability(null);
      assert.strictEqual(resNull.canApply, false);
      assert.ok(resNull.disabledReason?.includes('永久保留'));

      const resZero = getAuditRetentionApplyAvailability({ audit_retention_days: 0 });
      assert.strictEqual(resZero.canApply, false);
      assert.ok(resZero.disabledReason?.includes('永久保留'));
    });

    test('positive policy allows apply retention with candidates', () => {
      const res = getAuditRetentionApplyAvailability(
        { audit_retention_days: 90 },
        { enabled: true, delete_count: 5 }
      );
      assert.strictEqual(res.canApply, true);
      assert.strictEqual(res.disabledReason, undefined);
    });

    test('positive policy with 0 candidates flags isZeroCandidates while keeping canApply true', () => {
      const res = getAuditRetentionApplyAvailability(
        { audit_retention_days: 90 },
        { enabled: true, delete_count: 0 }
      );
      assert.strictEqual(res.canApply, true);
      assert.strictEqual(res.isZeroCandidates, true);
    });
  });

  describe('API Client Contract Verification', () => {
    const originalGet = api.get;
    const originalPut = api.put;
    const originalPost = api.post;

    test('dataLifecycleApi.getPolicy routes to /api/data-lifecycle', async () => {
      let calledUrl = '';
      (api as any).get = async (url: string) => {
        calledUrl = url;
        return { audit_retention_days: 0, updated_at: null };
      };

      try {
        const res = await dataLifecycleApi.getPolicy();
        assert.strictEqual(calledUrl, '/api/data-lifecycle');
        assert.strictEqual(res.audit_retention_days, 0);
      } finally {
        api.get = originalGet;
      }
    });

    test('dataLifecycleApi.updatePolicy sends PUT to /api/data-lifecycle with payload', async () => {
      let calledUrl = '';
      let calledBody: any = null;
      (api as any).put = async (url: string, body: any) => {
        calledUrl = url;
        calledBody = body;
        return { audit_retention_days: 90, updated_at: '2026-09-04T12:00:00Z' };
      };

      try {
        const res = await dataLifecycleApi.updatePolicy(90);
        assert.strictEqual(calledUrl, '/api/data-lifecycle');
        assert.deepStrictEqual(calledBody, { audit_retention_days: 90 });
        assert.strictEqual(res.audit_retention_days, 90);
      } finally {
        api.put = originalPut;
      }
    });

    test('auditApi.getRetentionPreview routes to /api/audit/retention-preview', async () => {
      let calledUrl = '';
      (api as any).get = async (url: string) => {
        calledUrl = url;
        return { enabled: true, retention_days: 90, total_count: 10, delete_count: 2, keep_count: 8 };
      };

      try {
        const res = await auditApi.getRetentionPreview();
        assert.strictEqual(calledUrl, '/api/audit/retention-preview');
        assert.strictEqual(res.retention_days, 90);
      } finally {
        api.get = originalGet;
      }
    });

    test('auditApi.applyRetention sends POST to /api/audit/apply-retention', async () => {
      let calledUrl = '';
      (api as any).post = async (url: string) => {
        calledUrl = url;
        return { retention_days: 90, deleted_count: 2, remaining_count: 9, cutoff: '2026-06-06T00:00:00Z' };
      };

      try {
        const res = await auditApi.applyRetention();
        assert.strictEqual(calledUrl, '/api/audit/apply-retention');
        assert.strictEqual(res.deleted_count, 2);
      } finally {
        api.post = originalPost;
      }
    });
  });

  describe('UI Truthfulness & Security Invariants', () => {
    test('Settings/index.tsx includes Data Lifecycle Card and three safety principles', () => {
      const content = readFileSync(resolve(__dirname, '../../src/pages/Settings/index.tsx'), 'utf-8');
      assert.ok(content.includes('数据生命周期与审计保留策略'));
      assert.ok(content.includes('保存策略 ≠ 执行删除'));
      assert.ok(content.includes('0 天 = 永久保留'));
      assert.ok(content.includes('预览 ≠ 执行'));
      assert.ok(content.includes('确认执行审计日志保留清理？'));
    });

    test('Audit/index.tsx corrects false permanent claim and maintains zero-delete-ui invariant', () => {
      const content = readFileSync(resolve(__dirname, '../../src/pages/Audit/index.tsx'), 'utf-8');
      // 确认纠正了旧有的错误宣称
      assert.ok(!content.includes('永久记录所有文件操作'));
      assert.ok(content.includes('按系统数据生命周期保留策略记录文件操作'));
      // 确认无单行删除或批量勾选删除
      assert.ok(!content.includes('rowSelection'));
      assert.ok(!content.includes('batchDelete'));
      assert.ok(!content.includes('deleteAudit'));
    });
  });
});
