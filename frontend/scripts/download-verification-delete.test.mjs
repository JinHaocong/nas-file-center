import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const ui = readFileSync('src/pages/DownloadVerification/index.tsx', 'utf8');
const api = readFileSync('src/api/downloadVerification.ts', 'utf8');

test('download verification report delete controls follow the API guard', () => {
  assert.match(api, /can_delete:\s*boolean/);
  assert.match(ui, /disabled=\{!run\.can_delete\}/);
  assert.match(ui, /title=\{run\.can_delete\s*\?/);
  assert.doesNotMatch(ui, /terminal\.has\(run\.job_status\)/);
  assert.match(ui, /unknown:\s*'任务记录不存在'/);
});

test('bulk deletion selects only server-approved reports on the current page', () => {
  assert.match(api, /bulkDeleteReports:\s*\(run_ids:\s*number\[\]\)/);
  assert.match(api, /api\.post<\{ deleted: number \}>\('\/api\/download-verifications\/bulk-delete'/);
  assert.match(ui, /filter\(run => run\.can_delete\)\.map\(run => run\.id\)/);
  assert.match(ui, /useEffect\(\(\) => \{ setSelectedReportIds\(\[\]\); \}, \[historyPage\]\)/);
  assert.match(ui, /checked=\{allDeletableSelected\}/);
  assert.match(ui, /checked=\{selectedDeletableIds\.includes\(run\.id\)\}/);
  assert.match(ui, /disabled=\{!run\.can_delete \|\| bulkRemove\.isPending\}/);
  assert.match(ui, /setBulkDeleteTarget\(\[\.\.\.selectedDeletableIds\]\)/);
  assert.match(ui, /<ConsoleConfirmDialog open=\{bulkDeleteTarget !== null\}/);
  assert.match(ui, /bulkRemove\.mutate\(bulkDeleteTarget\)/);
  assert.match(ui, /colSpan=\{7\}/);
});


test('abnormal-only detail filter uses server pagination and keeps reports read-only', () => {
  const router = readFileSync('../app/download_verification/router.py', 'utf8');
  const css = readFileSync('src/styles/console-v2-download-verify.css', 'utf8');
  assert.match(api, /items: \(id: number, page: number, status\?: string, abnormalOnly = false\)/);
  assert.match(api, /abnormal_only=true/);
  assert.match(ui, /\['download-verify-items', selected, page, abnormalOnly\]/);
  assert.match(ui, /downloadVerificationApi\.items\(selected!, page, undefined, abnormalOnly\)/);
  assert.match(ui, /aria-label="只看异常条目"/);
  assert.match(ui, /setAbnormalOnly\(event\.target\.checked\); setPage\(1\)/);
  assert.match(ui, /setSelected\(run\.id\); setPage\(1\); setAbnormalOnly\(false\)/);
  assert.match(ui, /没有发现异常条目/);
  assert.match(ui, /details\.data\?\.total/);
  assert.match(router, /DownloadVerificationItem\.status\.in_\(ABNORMAL_ITEM_STATUSES\)/);
  assert.match(router, /\.limit\(page_size\)\.offset\(\(page - 1\) \* page_size\)/);
  for (const status of ['ONLY_LOCAL', 'ONLY_REMOTE', 'SIZE_MISMATCH', 'TYPE_MISMATCH', 'HASH_MISMATCH']) {
    assert.ok(router.includes('"' + status + '"'), status + ' should be an abnormal result');
  }
  assert.doesNotMatch(router.split('ABNORMAL_ITEM_STATUSES = (')[1].split(')')[0], /METADATA_MATCH|DIRECTORY_MATCH|VERIFIED_MATCH|PENDING_SHA256/);
  assert.match(css, /\.nfc-dv-detail-filter input\[type=checkbox\]/);
});
