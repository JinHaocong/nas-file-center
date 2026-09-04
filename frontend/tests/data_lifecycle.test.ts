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

  describe('Hotfix 1: Confirmation Truthfulness & Fresh Refetch Requirements', () => {
    test('Settings/index.tsx includes truthful advisory and recomputation disclosure in confirmation', () => {
      const content = readFileSync(resolve(__dirname, '../../src/pages/Settings/index.tsx'), 'utf-8');
      assert.ok(content.includes('当前预览仅为预计结果'), 'Must state preview is only an estimate');
      assert.ok(
        content.includes('实际执行时将根据数据库中最新保存的保留策略以及执行时最新的审计数据重新计算'),
        'Must disclose actual execution recomputes from latest DB policy'
      );
      assert.ok(content.includes('最终删除数量可能与当前预览不同'), 'Must disclose final count may differ from preview');
    });

    test('Settings/index.tsx includes non-filesystem and non-task/scan/plan/index safety boundary in confirmation', () => {
      const content = readFileSync(resolve(__dirname, '../../src/pages/Settings/index.tsx'), 'utf-8');
      assert.ok(content.includes('不会删除 NAS 上的真实文件或目录'), 'Must declare NAS filesystem unaffected');
      assert.ok(content.includes('不会删除 Task、Scan、Plan 或 Index 数据'), 'Must declare Task/Scan/Plan/Index unaffected');
    });

    test('Settings/index.tsx executes fresh policy and preview refetch before Modal.confirm and uses fresh result', () => {
      const content = readFileSync(resolve(__dirname, '../../src/pages/Settings/index.tsx'), 'utf-8');
      assert.ok(content.includes('refetchPolicy'), 'Must invoke refetchPolicy before confirm');
      assert.ok(content.includes('refetchPreview'), 'Must invoke refetchPreview before confirm');
      assert.ok(
        content.includes('prepareApplyPending') || content.includes('preparingApply'),
        'Must track preparing state'
      );
    });

    test('getAuditRetentionApplyAvailability disables apply while saving policy, preparing apply, or applying', () => {
      const saving = getAuditRetentionApplyAvailability(
        { audit_retention_days: 90 },
        { enabled: true, delete_count: 5 },
        { isSavingPolicy: true }
      );
      assert.strictEqual(saving.canApply, false);
      assert.ok(saving.disabledReason?.includes('保存'));

      const preparing = getAuditRetentionApplyAvailability(
        { audit_retention_days: 90 },
        { enabled: true, delete_count: 5 },
        { isPreparingApply: true }
      );
      assert.strictEqual(preparing.canApply, false);
      assert.ok(preparing.disabledReason?.includes('刷新') || preparing.disabledReason?.includes('获取'));

      const applying = getAuditRetentionApplyAvailability(
        { audit_retention_days: 90 },
        { enabled: true, delete_count: 5 },
        { isApplying: true }
      );
      assert.strictEqual(applying.canApply, false);

      const queryError = getAuditRetentionApplyAvailability(
        { audit_retention_days: 90 },
        { enabled: true, delete_count: 5 },
        { isQueryError: true }
      );
      assert.strictEqual(queryError.canApply, false);
      assert.ok(queryError.disabledReason?.includes('失败'));
    });

    test('zero-candidates with positive policy continues to allow apply (regression guard)', () => {
      const res = getAuditRetentionApplyAvailability(
        { audit_retention_days: 30 },
        { enabled: true, delete_count: 0 }
      );
      assert.strictEqual(res.canApply, true);
      assert.strictEqual(res.isZeroCandidates, true);
    });

    test('policy 0 continues to strictly disable apply (regression guard)', () => {
      const res = getAuditRetentionApplyAvailability(
        { audit_retention_days: 0 },
        { enabled: false, delete_count: 0 }
      );
      assert.strictEqual(res.canApply, false);
      assert.ok(res.disabledReason?.includes('永久保留'));
    });

    test('save policy never triggers apply retention (Save != Apply invariant)', () => {
      const content = readFileSync(resolve(__dirname, '../../src/pages/Settings/index.tsx'), 'utf-8');
      const handleSaveStart = content.indexOf('const handleSavePolicy = () => {');
      assert.ok(handleSaveStart !== -1);
      const handleSaveEnd = content.indexOf('};', handleSaveStart);
      const handleSaveBody = content.slice(handleSaveStart, handleSaveEnd);
      assert.ok(handleSaveBody.includes('savePolicyMutation.mutate'));
      assert.ok(!handleSaveBody.includes('applyRetention'));
      assert.ok(!handleSaveBody.includes('applyRetentionMutation'));
    });

    test('apply success feedback truthfully uses backend response.deleted_count', () => {
      const content = readFileSync(resolve(__dirname, '../../src/pages/Settings/index.tsx'), 'utf-8');
      const mutationStart = content.indexOf('const applyRetentionMutation = useMutation({');
      assert.ok(mutationStart !== -1);
      const mutationEnd = content.indexOf('  });', mutationStart);
      const mutationBody = content.slice(mutationStart, mutationEnd);
      assert.ok(mutationBody.includes('res.deleted_count'), 'Must use backend response.deleted_count');
      assert.ok(!mutationBody.includes('preview.delete_count'), 'Must not use preview.delete_count for success toast');
    });
  });

  describe('Hotfix 2: Query-Error Wiring Integration', () => {
    test('Settings/index.tsx destructures isError from dataLifecyclePolicy query', () => {
      const content = readFileSync(resolve(__dirname, '../../src/pages/Settings/index.tsx'), 'utf-8');
      assert.ok(
        /const\s*\{\s*[^}]*\bisError\s*:\s*policyQueryError[^}]*\}\s*=\s*useQuery\(\s*\{\s*queryKey:\s*\['dataLifecyclePolicy'\]/m.test(content) ||
        /queryKey:\s*\['dataLifecyclePolicy'\][\s\S]*?isError\s*:\s*policyQueryError/.test(content),
        'Settings/index.tsx must destructure isError: policyQueryError from dataLifecyclePolicy query'
      );
    });

    test('Settings/index.tsx destructures isError from auditRetentionPreview query', () => {
      const content = readFileSync(resolve(__dirname, '../../src/pages/Settings/index.tsx'), 'utf-8');
      assert.ok(
        /const\s*\{\s*[^}]*\bisError\s*:\s*previewQueryError[^}]*\}\s*=\s*useQuery\(\s*\{\s*queryKey:\s*\['auditRetentionPreview'\]/m.test(content) ||
        /queryKey:\s*\['auditRetentionPreview'\][\s\S]*?isError\s*:\s*previewQueryError/.test(content),
        'Settings/index.tsx must destructure isError: previewQueryError from auditRetentionPreview query'
      );
    });

    test('Settings/index.tsx passes isQueryError into getAuditRetentionApplyAvailability', () => {
      const content = readFileSync(resolve(__dirname, '../../src/pages/Settings/index.tsx'), 'utf-8');
      assert.ok(
        /isQueryError:\s*policyQueryError\s*\|\|\s*previewQueryError/.test(content),
        'Settings/index.tsx must pass isQueryError: policyQueryError || previewQueryError to getAuditRetentionApplyAvailability'
      );
    });

    test('getAuditRetentionApplyAvailability returns canApply=false and truthful disabledReason on isQueryError', () => {
      const res = getAuditRetentionApplyAvailability(
        { audit_retention_days: 30 },
        { enabled: true, delete_count: 10 },
        { isQueryError: true }
      );
      assert.strictEqual(res.canApply, false);
      assert.strictEqual(res.disabledReason, '获取保留策略或清理预览失败，请刷新重试');
    });
  });
});

