import test, { describe } from 'node:test';
import assert from 'node:assert';
import { dashboardApi } from '../src/api/domain';
import { api } from '../src/api/client';
import { DashboardSummary } from '../src/types';

describe('Dashboard Freshness & Latest-Scan Semantics Tests', () => {
  describe('API Client: dashboardApi.getSummary', () => {
    const originalGet = api.get;

    test('getSummary calls GET /api/dashboard/summary', async () => {
      let capturedUrl = '';
      const mockSummary: DashboardSummary = {
        indexed_files: 100,
        indexed_folders: 10,
        scan_count: 2,
        plan_count: 1,
        duplicate_group_count: 5,
        queued_or_running_jobs: 0,
        latest_reclaimable_bytes: 2048,
        latest_scan_id: 2,
        latest_scan_name: 'Scan #2',
        latest_scan_finished_at: '2026-09-04T12:00:00Z',
      };

      api.get = ((url: string) => {
        capturedUrl = url;
        return Promise.resolve(mockSummary);
      }) as any;

      try {
        const res = await dashboardApi.getSummary();
        assert.strictEqual(capturedUrl, '/api/dashboard/summary');
        assert.strictEqual(res.duplicate_group_count, 5);
        assert.strictEqual(res.latest_scan_id, 2);
        assert.strictEqual(res.latest_scan_name, 'Scan #2');
        assert.strictEqual(res.latest_scan_finished_at, '2026-09-04T12:00:00Z');
      } finally {
        api.get = originalGet;
      }
    });

    test('handles zero completed scans safely with null metadata', async () => {
      const emptySummary: DashboardSummary = {
        indexed_files: 0,
        indexed_folders: 0,
        scan_count: 0,
        plan_count: 0,
        duplicate_group_count: 0,
        queued_or_running_jobs: 0,
        latest_reclaimable_bytes: 0,
        latest_scan_id: null,
        latest_scan_name: null,
        latest_scan_finished_at: null,
      };

      api.get = (() => Promise.resolve(emptySummary)) as any;

      try {
        const res = await dashboardApi.getSummary();
        assert.strictEqual(res.duplicate_group_count, 0);
        assert.strictEqual(res.latest_reclaimable_bytes, 0);
        assert.strictEqual(res.latest_scan_id, null);
        assert.strictEqual(res.latest_scan_name, null);
        assert.strictEqual(res.latest_scan_finished_at, null);
      } finally {
        api.get = originalGet;
      }
    });
  });

  describe('UI Semantics: Snapshot Labeling & Subtitle resolution', () => {
    function resolveDashboardLabels(summary: DashboardSummary) {
      const duplicateCountDisplay = summary.latest_scan_id ? summary.duplicate_group_count : '—';
      const scanSubtitle = summary.latest_scan_id
        ? `基于: ${summary.latest_scan_name || `扫描 #${summary.latest_scan_id}`}`
        : '暂无已完成扫描';
      const reclaimableDisplay = summary.latest_scan_id ? `${summary.latest_reclaimable_bytes} B` : '—';

      return {
        cardTitleGroups: '最近一次扫描发现',
        cardTitleReclaim: '最近一次扫描预计可释放',
        duplicateCountDisplay,
        scanSubtitle,
        reclaimableDisplay,
      };
    }

    test('formats snapshot labels correctly when completed scan exists', () => {
      const summary: DashboardSummary = {
        indexed_files: 50,
        indexed_folders: 5,
        scan_count: 1,
        plan_count: 0,
        duplicate_group_count: 8,
        queued_or_running_jobs: 0,
        latest_reclaimable_bytes: 4096,
        latest_scan_id: 10,
        latest_scan_name: 'Media Scan',
        latest_scan_finished_at: '2026-09-04T10:00:00Z',
      };

      const labels = resolveDashboardLabels(summary);
      assert.strictEqual(labels.cardTitleGroups, '最近一次扫描发现');
      assert.strictEqual(labels.cardTitleReclaim, '最近一次扫描预计可释放');
      assert.strictEqual(labels.duplicateCountDisplay, 8);
      assert.strictEqual(labels.scanSubtitle, '基于: Media Scan');
      assert.strictEqual(labels.reclaimableDisplay, '4096 B');
    });

    test('formats snapshot labels gracefully when no completed scan exists', () => {
      const summary: DashboardSummary = {
        indexed_files: 0,
        indexed_folders: 0,
        scan_count: 1,
        plan_count: 0,
        duplicate_group_count: 0,
        queued_or_running_jobs: 1,
        latest_reclaimable_bytes: 0,
        latest_scan_id: null,
        latest_scan_name: null,
        latest_scan_finished_at: null,
      };

      const labels = resolveDashboardLabels(summary);
      assert.strictEqual(labels.duplicateCountDisplay, '—');
      assert.strictEqual(labels.scanSubtitle, '暂无已完成扫描');
      assert.strictEqual(labels.reclaimableDisplay, '—');
    });
  });
});
