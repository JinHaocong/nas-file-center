import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { filterDedupePreviewRows, decisionFilterOptions } from '../src/components/dedupe/previewTableModel';
import type { DedupePreviewMemberRow } from '../src/types/dedupe';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const rows: DedupePreviewMemberRow[] = [
  { absolute_path: '/srv/A/Master.jpg', relative_path: 'A/Master.jpg', scan_root_index: 0,
    member_decision: 'KEEP', eligible_as_keep: true },
  { absolute_path: '/srv/B/master.jpg', relative_path: 'B/master.jpg', scan_root_index: 1,
    member_decision: 'QUARANTINE', eligible_as_keep: false, storage_blocking_reason: 'protected' },
  { absolute_path: '/srv/B/test.mp4', relative_path: 'B/test.mp4', scan_root_index: 1,
    member_decision: 'HARDLINK', eligible_as_keep: true },
  { absolute_path: '/srv/A/unknown', scan_root_index: 0, member_decision: 'UNAVAILABLE' },
  { absolute_path: '/srv/A/protected', scan_root_index: 0, member_decision: 'SAFETY_EXCLUDED', eligible_as_keep: false },
];
describe('Console v2 advanced dedupe preview table', () => {
  test('client-side filters are scoped to supplied server page and preserve safety classifications', () => {
    assert.equal(filterDedupePreviewRows(rows, {searchText:'',decisionFilter:'ALL',rootFilter:'ALL'}).length,5);
    assert.deepEqual(filterDedupePreviewRows(rows,{searchText:'master.JPG',decisionFilter:'ALL',rootFilter:'ALL'}),rows.slice(0,2));
    assert.deepEqual(filterDedupePreviewRows(rows,{searchText:'B/TEST',decisionFilter:'ALL',rootFilter:1}),[rows[2]]);
    assert.deepEqual(filterDedupePreviewRows(rows,{searchText:'',decisionFilter:'QUARANTINE',rootFilter:'ALL'}),[rows[1]]);
    assert.deepEqual(filterDedupePreviewRows(rows,{searchText:'',decisionFilter:'SAFETY_EXCLUDED',rootFilter:'ALL'}),[rows[4]]);
    assert.deepEqual(filterDedupePreviewRows(rows,{searchText:'',decisionFilter:'UNAVAILABLE',rootFilter:0}),[rows[3]]);
    assert.deepEqual(filterDedupePreviewRows(rows,{searchText:'',decisionFilter:'KEEP',rootFilter:1}),[]);
    assert.ok(decisionFilterOptions.some(o=>o.value==='HARDLINK'));
    assert.ok(decisionFilterOptions.some(o=>o.value==='REFLINK'));
  });
  test('native semantic desktop table and mobile cards keep rich safety explanations', () => {
    const s=read('src/components/dedupe/DedupePreviewTable.tsx');
    for(const token of [
      '<table className="nfc-v2-dedupe-table">','<th scope="col">决策',
      'ResponsiveDataView','nfc-dedupe-member-mobile-card','onSelectMember',
      'formatOptionalGroupId','formatOptionalFileSize','getEligibilityPresentation',
      'scan_root_index','storage_blocking_reason','recommended_keep',
      'decisionFilter','rootFilter','filterDedupePreviewRows',
      '<ConsolePagination page={pagination.current}','onChange={pagination.onChange}',
      'pagination.total','服务器总计','本页符合条件',"pagination === false",
      'nfc-v2-dedupe-empty','aria-label="决策筛选"'])assert.ok(s.includes(token),token);
    assert.doesNotMatch(s,/from ['"]antd['"]|@ant-design\/icons|<Table\b|<Pagination\b|<Select\b|<Input\b/);
  });
  test('page still uses server-controlled authority and digest safety, not client table filters', () => {
    const p=read('src/pages/Scans/AdvancedDedupePage.tsx');
    for(const token of [
      'acceptedPreviewDigest','expected_preview_digest','PREVIEW_CHANGED',
      'canGeneratePlan','shouldAcceptDirectResponse','CONFIG_EDITED','PREVIEW_SUCCESS',
      'scansApi.dedupePreview','scansApi.createAdvancedDedupePlan',
      'DedupePreviewTable','DedupeIdentitySafetyPanel','DedupePreviewSummaryPanel',
      'Freeze -> Validate -> Execute'])assert.ok(p.includes(token),token);
    assert.doesNotMatch(p,/deleteFiles\(|executePlan\(/);
  });
  test('scoped responsive styles imported with dark and accessible focus treatment', () => {
    const css=read('src/styles/console-v2-advanced-dedupe.css');
    const main=read('src/main.tsx');
    for(const token of [
      '.nfc-v2-dedupe-preview-filters','.nfc-v2-dedupe-table',
      "[data-theme='dark']",':focus-visible',
      '@media (max-width: 767px)','prefers-reduced-motion: reduce'])assert.ok(css.includes(token),token);
    assert.ok(main.includes("import './styles/console-v2-advanced-dedupe.css';"));
  });
});
