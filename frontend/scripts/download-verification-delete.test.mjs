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
