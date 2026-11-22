import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) =>
  readFileSync(resolve(process.cwd(), path), 'utf8');

test('historical MediaPackage links open the unified organizer while legacy API gates stay intact', () => {
  const batch = read('src/pages/Batch/index.tsx');
  const view = read('src/pages/Batch/MediaPackageOrganizerEditor.tsx');
  const api = read('src/api/media_package.ts');

  assert.match(batch, /operation === 'media_package-organize'/);
  assert.match(batch, /<MediaOrganizerBatchEditor\s*\/>/);
  assert.match(view, /DirectoryPicker/);
  assert.match(view, /media_packageApi\.startPreview/);
  assert.match(view, /media_packageApi\.getPreview/);
  assert.match(view, /ConsolePagination/);
  assert.match(view, /blocked_count/);
  assert.match(view, /needed_moves/);
  assert.match(view, /只读/);
  assert.match(api, /\/api\/media_package\/previews/);
  assert.match(api, /startExecution/);
  assert.match(api, /getExecution/);
  assert.match(view, /confirmationToken/);
  assert.match(view, /canExecute/);
  assert.match(view, /blocked_count === 0/);
  assert.match(view, /executionConfirmation === confirmationToken/);
  assert.match(view, /确认并执行 媒体资源包整理/);
  assert.doesNotMatch(api, /\/plans/);
});

test('Media package preview is a fixed rule not a configurable processing toggle', () => {
  const view = read('src/pages/Batch/MediaPackageOrganizerEditor.tsx');
  const api = read('src/api/media_package.ts');
  assert.match(view, /200/);
  assert.match(view, /MediaPackage/);
  assert.doesNotMatch(view, /setSmartSkip|setLimit|setGroupSize|skipConflicts/);
  assert.doesNotMatch(api, /group_size|smart_skip|recursive:/);
});
