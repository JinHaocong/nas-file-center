import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) =>
  readFileSync(resolve(process.cwd(), path), 'utf8');

test('Luolcy has an isolated read-only Batch operation with no execute button', () => {
  const batch = read('src/pages/Batch/index.tsx');
  const view = read('src/pages/Batch/LuolcyOrganizerEditor.tsx');
  const api = read('src/api/luolcy.ts');

  assert.match(batch, /op: 'luolcy-organize'/);
  assert.match(batch, /<LuolcyOrganizerEditor\s*\/>/);
  assert.match(view, /DirectoryPicker/);
  assert.match(view, /luolcyApi\.startPreview/);
  assert.match(view, /luolcyApi\.getPreview/);
  assert.match(view, /ConsolePagination/);
  assert.match(view, /blocked_count/);
  assert.match(view, /needed_moves/);
  assert.match(view, /只读/);
  assert.match(api, /\/api\/luolcy\/previews/);
  assert.doesNotMatch(api, /execute|delete|rename|\/plans/);
  assert.doesNotMatch(view, /createPlan|startExecute|runMove/);
});

test('Luolcy preview is a fixed rule not a configurable processing toggle', () => {
  const view = read('src/pages/Batch/LuolcyOrganizerEditor.tsx');
  const api = read('src/api/luolcy.ts');
  assert.match(view, /200/);
  assert.match(view, /Luolcy/);
  assert.doesNotMatch(view, /setSmartSkip|setLimit|setGroupSize|skipConflicts/);
  assert.doesNotMatch(api, /group_size|smart_skip|recursive:/);
});
