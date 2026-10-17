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
