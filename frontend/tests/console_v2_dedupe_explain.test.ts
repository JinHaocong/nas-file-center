import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  isBalancerContributionExcludedFromFactors, mapReleasedBytesByScanRoot,
  classifyMemberDecision, formatScanRootLabel,
} from '../src/utils/dedupePreview';
import {
  findDuplicateGroupSiblings, formatOptionalGroupId, formatOptionalFileSize,
  getProtectLastFileDescription,
} from '../src/utils/dedupePresentation';
import type { DedupePreviewMemberRow } from '../src/types/dedupe';
const read = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8');

describe('Console v2 advanced dedupe explanation and preview summary', () => {
  test('backend factor contributions exclude selection balancer but preserve scoring factors', () => {
    assert.equal(isBalancerContributionExcludedFromFactors({
      factor: 'balanced_by_bytes', configured_weight: 0, actual_contribution: 999,
    }), true);
    assert.equal(isBalancerContributionExcludedFromFactors({
      factor: 'recursive_directory_balance', configured_weight: 0, actual_contribution: 250,
    }), true);
    assert.equal(isBalancerContributionExcludedFromFactors({
      factor: 'path_priority', configured_weight: 50, actual_contribution: 12,
    }), false);
    assert.equal(isBalancerContributionExcludedFromFactors({
      factor: 'mtime', configured_weight: 10, actual_contribution: -5,
    }), false);
    const s = read('src/components/dedupe/DedupeExplainDrawer.tsx');
    assert.ok(s.includes('!isBalancerContributionExcludedFromFactors(c)'));
    assert.ok(s.includes('member.contributions || []'));
    assert.ok(s.includes('factor.actual_contribution.toLocaleString()'));
    assert.ok(s.includes("factor.actual_contribution > 0 ? '+' : ''"));
    assert.ok(s.includes('容量平衡器属于选择仲裁层，独立于因子权重计分之外'));
  });

  test('sibling list never merges unknown groups or members from other provenance IDs', () => {
    const rows: DedupePreviewMemberRow[] = [
      {absolute_path:'/a',group_provenance_id:42,member_decision:'KEEP'},
      {absolute_path:'/b',group_provenance_id:42,member_decision:'QUARANTINE'},
      {absolute_path:'/c',group_provenance_id:43,member_decision:'KEEP'},
      {absolute_path:'/d',member_decision:'UNAVAILABLE'},
    ];
    assert.deepEqual(findDuplicateGroupSiblings(rows[0],rows),[rows[1]]);
    assert.deepEqual(findDuplicateGroupSiblings(rows[3],rows),[]);
    const s=read('src/components/dedupe/DedupeExplainDrawer.tsx');
    assert.ok(s.includes('findDuplicateGroupSiblings(member, groupMembers)'));
    assert.ok(s.includes('当前预览页'));
    assert.ok(s.includes('sib.selection_reason'));
    assert.ok(s.includes('sib.absolute_path'));
  });

  test('native Radix sheet preserves canonical metadata and fail-closed incomplete explanation', () => {
    const s=read('src/components/dedupe/DedupeExplainDrawer.tsx');
    for (const token of [
      '<ConsoleSheet', 'open={open}', 'onClose={onClose}', 'role="note"',
      'member.incomplete', '后端 canonical 分析数据', '!member.incomplete',
      'classifyMemberDecision', 'formatOptionalGroupId', 'formatOptionalFileSize',
      'eligible_as_keep === true', 'eligible_as_keep === false',
      '安全策略排除', '不可用 / -', 'safety_reasons?.join',
      'group_skip_reason', 'group_recommended_keep_path', 'group_reclaimable_bytes',
      'group_selection_reason', 'selection_reason', 'total_score',
      'candidate_balance_bucket', 'recursive_last_file_protection_reason',
      "member.storage_action !== 'quarantine'", 'storage_metadata_compatible',
      'storage_blocking_reason', 'storage_capability',
      'metadata eligibility，不执行 filesystem capability probe',
      '<table', '<th scope="col">配置权重', 'balanceInfo.lca',
      'balanceInfo.lca_depth', 'balanceInfo.anchor_root',
      'balanceInfo.parent_bucket', 'balanceInfo.recursive_last_file_protection',
      'balanceInfo.bucket_released_bytes_before', 'balanceInfo.bucket_released_bytes_after',
      'balanceInfo.spread_before', 'balanceInfo.spread_after', 'renderBucketBytes',
      'navigator.clipboard.writeText', '前端不进行任何打分计算',
    ]) assert.ok(s.includes(token),token);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Drawer\b|<Table\b|<Descriptions\b|<Card\b|<Alert\b/);
    assert.equal(formatOptionalGroupId(undefined),'组 -');
    assert.equal(formatOptionalFileSize(undefined),'-');
    assert.equal(classifyMemberDecision('SAFETY_EXCLUDED').kind,'SAFETY_EXCLUDED');
    assert.equal(classifyMemberDecision('UNAVAILABLE').kind,'UNAVAILABLE');
  });

  test('preview summary uses authoritative totals, storage counts and root-index distribution', () => {
    const s=read('src/components/dedupe/DedupePreviewSummaryPanel.tsx');
    for (const token of [
      'summary.group_count ?? summary.actionable_group_count ?? 0',
      'summary.actionable_group_count ?? 0',
      'summary.skipped_group_count ?? 0',
      'summary.candidate_member_count ?? 0',
      "storageAction === 'hardlink'",
      "storageAction === 'reflink'",
      "summary.storage_action || 'quarantine'",
      'summary.planned_action_count ?? 0',
      'summary.storage_blocked_count ?? 0',
      'summary.planned_quarantine_count ?? 0',
      'summary.expected_reclaim_bytes ?? 0',
      'mapReleasedBytesByScanRoot', 'formatScanRootLabel',
      "scanRoots.length > 0 ? scanRoots : summary.scan_roots",
      'formatBytes(entry.releasedBytes)', 'Hardlink 语义已选择',
      'Reflink 语义已选择', 'Copy-on-Write',
      "mode === 'balanced_by_bytes'",
      'backend released_bytes', '该机制独立于因子权重计分之外',
      'getProtectLastFileDescription(policy.protect_last_file)',
      '去重安全保护策略 (protect_last_file): 未配置。',
      '<ConsoleIcon', '<SummaryNotice',
    ]) assert.ok(s.includes(token),token);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Alert\b|<Tag\b/);
    const roots = mapReleasedBytesByScanRoot({'0':123,'2':500},['/nas/a','/nas/b','/nas/c']);
    assert.deepEqual(roots.map(r=>r.releasedBytes),[123,0,500]);
    assert.equal(formatScanRootLabel(2,'/nas/c'),'Scan Root 2 /nas/c');
    assert.match(getProtectLastFileDescription(true),/已启用/);
    assert.match(getProtectLastFileDescription(false),/未启用/);
  });

  test('scoped CSS supports dark portal, mobile, focus and reduced motion', () => {
    const css=read('src/styles/console-v2-dedupe-explain.css');
    const main=read('src/main.tsx');
    for(const token of [
      '.nfc-v2-dedupe-summary', '.nfc-v2-dedupe-explain-sheet',
      '.nfc-v2-dedupe-explain-table-wrap', '.nfc-v2-dedupe-explain-facts',
      'overflow-wrap: anywhere', 'overflow-x: auto', 'focus-visible',
      "[data-theme='dark']", '@media (max-width: 767px)',
      'prefers-reduced-motion: reduce',
    ])assert.ok(css.includes(token),token);
    assert.ok(main.includes("import './styles/console-v2-dedupe-explain.css';"));
    const sheet=read('src/components/ui/ConsoleSheet.tsx');
    assert.ok(sheet.includes('<Dialog.Root'));
    assert.ok(sheet.includes('<Dialog.Description'));
    assert.ok(sheet.includes('Dialog.Close asChild'));
  });
});
