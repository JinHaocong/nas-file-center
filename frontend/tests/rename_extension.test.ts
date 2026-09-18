import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const renamePageSource = readFileSync(
  resolve(process.cwd(), 'src/pages/Rename/index.tsx'),
  'utf8'
);
const domainSource = readFileSync(
  resolve(process.cwd(), 'src/api/domain.ts'),
  'utf8'
);

describe('Batch rename extension replacement UI contract', () => {
  test('rename form exposes source-extension filter and target-extension fields', () => {
    assert.match(renamePageSource, /name=["']source_extension["']/);
    assert.match(renamePageSource, /name=["']target_extension["']/);
    assert.match(renamePageSource, /原扩展名|源扩展名/);
    assert.match(renamePageSource, /目标扩展名/);
  });

  test('preview payload transports extension fields to the API client', () => {
    assert.match(renamePageSource, /source_extension:\s*values\.source_extension/);
    assert.match(renamePageSource, /target_extension:\s*values\.target_extension/);
    assert.match(domainSource, /source_extension\?:\s*string/);
    assert.match(domainSource, /target_extension\?:\s*string/);
  });

  test('UI explicitly warns extension replacement is rename-only, not image conversion', () => {
    assert.match(renamePageSource, /不会转换|不做.*转码|仅.*重命名/);
  });
});
