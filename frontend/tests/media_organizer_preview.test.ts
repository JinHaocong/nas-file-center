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
  assert.doesNotMatch(api, /startExecution|executePlan|\/execute/);
  assert.doesNotMatch(view, /startExecution|executePlan|\/execute/);
});

test('the semantic organizer cannot generate a mutation Plan without a freeze gate', () => {
  const batch = read('src/pages/Batch/index.tsx');
  const view = read('src/pages/Batch/SemanticMediaOrganizerEditor.tsx');
  assert.match(batch, /operation !== 'semantic-media-organize'/);
  assert.match(view, /目前只支持只读预览/);
  assert.doesNotMatch(view, /确认并执行|执行确认码/);
});
