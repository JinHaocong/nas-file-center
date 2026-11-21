import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

const read = (path: string) => readFileSync(join(process.cwd(), path), 'utf8');

test('single quarantine purge reports queued Worker jobs instead of claiming immediate deletion', () => {
  const modal = read('src/pages/Quarantine/PurgeConfirmModal.tsx');
  const types = read('src/types/quarantine.ts');

  assert.match(types, /status:\s*'queued'/);
  assert.match(types, /work_job_id:\s*number/);
  assert.match(modal, /result\.status\s*===\s*'queued'/);
  assert.match(modal, /result\.work_job_id/);
  assert.match(modal, /queryKey:\s*\['tasks'\]/);
  assert.match(modal, /永久清除任务/);
  assert.match(modal, /onClose\(\)/);
});
