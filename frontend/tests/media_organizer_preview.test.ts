import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

test('semantic organizer has an isolated read-only Batch operation', () => {
  const batch = read('src/pages/Batch/index.tsx');
  const view = read('src/pages/Batch/SemanticMediaOrganizerEditor.tsx');
  const api = read('src/api/media_organizer.ts');
  assert.match(batch, /op: 'semantic-media-organize'/);
  assert.match(batch, /<SemanticMediaOrganizerEditor\s*\/>/);
  assert.match(view, /DirectoryPicker/);
  assert.match(view, /ConsolePagination/);
  assert.match(view, /StatusBadge/);
  assert.match(view, /TaskProgress/);
  assert.match(view, /unit_count/);
  assert.match(view, /ready_count/);
  assert.match(view, /blocked_count/);
  assert.match(view, /already_organized_count/);
  assert.match(view, /group\.name/);
  assert.match(view, /sample_moves/);
  assert.match(view, /getStructuredApiError/);
  assert.match(view, /只读/);
  assert.match(api, /\/api\/media-organizer\/previews/);
  assert.match(api, /startPreview/);
  assert.match(api, /getPreview/);
  assert.match(api, /startExecution/);
  assert.match(api, /getExecution/);
  assert.match(api, /recoverExecution/);
  assert.doesNotMatch(api, /executePlan/);
});

test('the semantic organizer executes only one approved unit with explicit confirmation', () => {
  const batch = read('src/pages/Batch/index.tsx');
  const view = read('src/pages/Batch/SemanticMediaOrganizerEditor.tsx');
  assert.match(batch, /operation !== 'semantic-media-organize'/);
  assert.match(view, /execution_enabled/);
  assert.match(view, /confirmation_tokens/);
  assert.match(view, /selectedUnit/);
  assert.match(view, /executionConfirmation === expectedConfirmation/);
  assert.match(view, /summary.blocked_count === 0/);
  assert.match(view, /canExecute/);
  assert.match(view, /recoverExecution/);
  assert.match(view, /确认并执行当前作品/);
  assert.doesNotMatch(view, /executePlan|freezePlan|validatePlan/);
});


test('published media must be clearly labelled as awaiting manual cleanup', () => {
  const view = read('src/pages/Batch/SemanticMediaOrganizerEditor.tsx');
  const api = read('src/api/media_organizer.ts');
  assert.match(api, /manual_cleanup_required: boolean/);
  assert.match(api, /finalized: boolean/);
  assert.match(view, /executionStatus\.manual_cleanup_required/);
  assert.match(view, /等待人工核查清理/);
  assert.doesNotMatch(view, /本次执行已完成。请重新只读扫描/);
});
