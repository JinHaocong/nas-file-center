import test, { describe } from 'node:test';
import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const quarantinePageSource = readFileSync(
  resolve(process.cwd(), 'src/pages/Quarantine/index.tsx'),
  'utf8'
);

describe('Gate6-A quarantine page wiring contract', () => {
  test('quarantine table exposes explicit active-row bulk selection', () => {
    assert.match(quarantinePageSource, /rowSelection=/);
    assert.match(quarantinePageSource, /preserveSelectedRowKeys:\s*true/);
    assert.match(quarantinePageSource, /getBulkSelectableEntryIds/);
  });

  test('bulk restore and Gate6-A2 bulk permanent purge are both wired to safety modals', () => {
    assert.match(quarantinePageSource, /批量恢复/);
    assert.match(quarantinePageSource, /批量永久删除/);
    assert.match(quarantinePageSource, /BulkRestoreModal/);
    assert.match(quarantinePageSource, /BulkPurgeModal/);
    assert.doesNotMatch(quarantinePageSource, /批量永久删除在 v0\.3\.6 已暂缓/);
    assert.doesNotMatch(
      quarantinePageSource,
      /<Button[\s\S]*?danger[\s\S]*?icon=\{<DeleteOutlined \/>\}[\s\S]*?disabled=\{true\}[\s\S]*?>[\s\S]*?批量永久删除/
    );
    assert.match(quarantinePageSource, /selectedEntryIds\.length/);
    assert.match(quarantinePageSource, /isAdmin/);
    assert.match(quarantinePageSource, /allowDelete/);
    assert.match(quarantinePageSource, /isSafeMode/);
  });

  test('all-filtered selection resolves to explicit ids before preview', () => {
    assert.match(quarantinePageSource, /resolveBulkFilteredEntryIds/);
    assert.match(quarantinePageSource, /已选择当前筛选/);
  });

  test('bulk restore routes draft generation into the existing plan safety lifecycle', () => {
    assert.match(quarantinePageSource, /navigate\(`\/plans\/\$\{[^}]+\}`\)/);
  });

  test('restored records participate in safe terminal cleanup through Worker tasks', () => {
    const apiSource = readFileSync(
      resolve(process.cwd(), 'src/api/quarantine.ts'),
      'utf8'
    );
    assert.match(apiSource, /\['restored', 'purged', 'abandoned', 'conflict'\]/);
    assert.match(quarantinePageSource, /canDeleteRecord = \['restored', 'purged', 'abandoned', 'conflict'\]/);
    assert.match(quarantinePageSource, /\.nas-file-center-trash/);
    assert.match(quarantinePageSource, /work_job_id/);
    assert.match(quarantinePageSource, /任务中心/);
    assert.match(quarantinePageSource, /批量删除记录/);
  });

});
