import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const renamePageSource = read('src/pages/Rename/AdvancedRenameEditor.tsx');
const payloadSource = read('src/utils/advancedRenameSafety.ts');
const domainSource = read('src/api/domain.ts');

describe('Batch rename extension replacement UI contract', () => {
  test('native editor exposes source/target extension fields', () => {
    assert.ok(renamePageSource.includes("'source_extension'"));
    assert.ok(renamePageSource.includes("'target_extension'"));
    assert.match(renamePageSource, /原扩展名|源扩展名/);
    assert.match(renamePageSource, /目标扩展名/);
  });
  test('preview request preserves extension fields end-to-end', () => {
    assert.ok(payloadSource.includes('source_extension: draft.source_extension'));
    assert.ok(payloadSource.includes('target_extension: draft.target_extension'));
    assert.ok(renamePageSource.includes('batchApi.previewRename(payload)'));
    assert.ok(domainSource.includes('source_extension?: string'));
    assert.ok(domainSource.includes('target_extension?: string'));
  });
  test('UI explicitly warns extension replacement renames, not converts', () => {
    assert.match(renamePageSource, /不会转换|不做.*转码|仅.*重命名/);
  });
});
