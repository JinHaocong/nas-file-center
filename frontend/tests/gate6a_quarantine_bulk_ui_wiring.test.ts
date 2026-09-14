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

  test('bulk restore remains executable while bulk permanent purge is deferred', () => {
    assert.match(quarantinePageSource, /批量恢复/);
    assert.match(quarantinePageSource, /批量永久删除/);
    assert.match(quarantinePageSource, /BulkRestoreModal/);
    assert.match(quarantinePageSource, /BulkPurgeModal/);
    assert.match(quarantinePageSource, /批量永久删除在 v0\.3\.6 已暂缓/);
    assert.match(quarantinePageSource, /safe hard-link ownership scope|hard-link ownership|硬链接所有权/);
    assert.match(
      quarantinePageSource,
      /<Button[\s\S]*?danger[\s\S]*?icon=\{<DeleteOutlined \/>\}[\s\S]*?disabled=\{true\}[\s\S]*?>[\s\S]*?批量永久删除/
    );
  });

  test('all-filtered selection resolves to explicit ids before preview', () => {
    assert.match(quarantinePageSource, /resolveBulkFilteredEntryIds/);
    assert.match(quarantinePageSource, /已选择当前筛选/);
  });

  test('bulk restore routes draft generation into the existing plan safety lifecycle', () => {
    assert.match(quarantinePageSource, /navigate\(`\/plans\/\$\{[^}]+\}`\)/);
  });
});
