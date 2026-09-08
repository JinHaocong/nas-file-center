import test, { describe } from 'node:test';
import assert from 'node:assert';
import {
  formatScanRootLabel,
  classifyMemberDecision,
  mapWorkflowPreviewItemsToDedupeRows,
  mapReleasedBytesByScanRoot,
  isBalancerContributionExcludedFromFactors,
} from '../src/utils/dedupePreview';
import { DedupePreviewMemberRow } from '../src/types/dedupe';
import { WorkflowPreviewItem } from '../src/types/workflow';

describe('Gate5-D / D4 Dedupe Preview & Explain Primitives', () => {
  describe('Scan Root Label Formatter', () => {
    test('formats scan root label as Scan Root <index> <path>', () => {
      assert.strictEqual(formatScanRootLabel(0, '/data/photos'), 'Scan Root 0 /data/photos');
      assert.strictEqual(formatScanRootLabel(1, '/data/backup'), 'Scan Root 1 /data/backup');
      assert.strictEqual(formatScanRootLabel(2), 'Scan Root 2');
    });
  });

  describe('Decision Classification', () => {
    test('classifies KEEP decision', () => {
      const res = classifyMemberDecision('KEEP');
      assert.strictEqual(res.kind, 'KEEP');
      assert.strictEqual(res.label, 'KEEP');
      assert.strictEqual(res.color, 'success');
    });

    test('classifies QUARANTINE decision', () => {
      const res = classifyMemberDecision('QUARANTINE');
      assert.strictEqual(res.kind, 'QUARANTINE');
      assert.strictEqual(res.label, 'QUARANTINE');
      assert.strictEqual(res.color, 'error');
    });

    test('classifies SAFETY EXCLUDED decision', () => {
      const res1 = classifyMemberDecision('SAFETY_EXCLUDED');
      assert.strictEqual(res1.kind, 'SAFETY_EXCLUDED');
      assert.strictEqual(res1.label, 'SAFETY EXCLUDED');

      const res2 = classifyMemberDecision('SAFETY EXCLUDED');
      assert.strictEqual(res2.kind, 'SAFETY_EXCLUDED');
      assert.strictEqual(res2.label, 'SAFETY EXCLUDED');
    });

    test('classifies SKIPPED decision', () => {
      const res = classifyMemberDecision('SKIPPED');
      assert.strictEqual(res.kind, 'SKIPPED');
      assert.strictEqual(res.label, 'SKIPPED');
      assert.strictEqual(res.color, 'default');
    });
  });

  describe('Workflow Preview Items Adapter', () => {
    test('maps workflow preview items metadata to dedupe rows', () => {
      const items: WorkflowPreviewItem[] = [
        {
          source_path: '/data/dup1.jpg',
          target_path: null,
          operation: 'keep',
          mtime_ns: null,
          changed: false,
          metadata: {
            group_provenance_id: 101,
            group_status: 'actionable',
            group_file_size: 2048,
            group_recommended_keep_path: '/data/dup1.jpg',
            group_reclaimable_bytes: 2048,
            group_selection_reason: 'newest mtime',
            absolute_path: '/data/dup1.jpg',
            relative_path: 'dup1.jpg',
            scan_root_index: 0,
            scan_root_path: '/data',
            eligible_as_keep: true,
            safety_reasons: [],
            total_score: 100,
            contributions: [{ factor: 'mtime', configured_weight: 100, actual_contribution: 100 }],
            is_top_candidate: true,
            recommended_keep: true,
            member_decision: 'KEEP',
            selection_reason: 'highest score',
          },
        },
      ];

      const rows = mapWorkflowPreviewItemsToDedupeRows(items);
      assert.strictEqual(rows.length, 1);
      assert.strictEqual(rows[0].absolute_path, '/data/dup1.jpg');
      assert.strictEqual(rows[0].group_provenance_id, 101);
      assert.strictEqual(rows[0].member_decision, 'KEEP');
      assert.strictEqual(rows[0].total_score, 100);
    });
  });

  describe('Released Bytes by Scan Root Mapping', () => {
    test('maps backend released_bytes_by_scan_root dict to scan_roots list', () => {
      const roots = ['/data/root0', '/data/root1'];
      const released = { '0': 1024, '1': 4096 };

      const mapped = mapReleasedBytesByScanRoot(released, roots);
      assert.strictEqual(mapped.length, 2);
      assert.strictEqual(mapped[0].rootIndex, 0);
      assert.strictEqual(mapped[0].rootPath, '/data/root0');
      assert.strictEqual(mapped[0].releasedBytes, 1024);
      assert.strictEqual(mapped[1].rootIndex, 1);
      assert.strictEqual(mapped[1].rootPath, '/data/root1');
      assert.strictEqual(mapped[1].releasedBytes, 4096);
    });
  });

  describe('Balancer Factor Separation', () => {
    test('balancer contribution is strictly excluded from scorer factor table', () => {
      const contributions = [
        { factor: 'path_priority', configured_weight: 10, actual_contribution: 10 },
        { factor: 'balanced_by_bytes', configured_weight: 0, actual_contribution: 50 },
      ];
      const isExcluded = isBalancerContributionExcludedFromFactors(contributions[1]);
      assert.strictEqual(isExcluded, true);

      const isNormalExcluded = isBalancerContributionExcludedFromFactors(contributions[0]);
      assert.strictEqual(isNormalExcluded, false);
    });
  });
});
