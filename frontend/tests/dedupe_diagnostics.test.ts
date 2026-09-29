import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('duplicate diagnostics', () => {
  test('domain API exposes a read-only pair diagnostic endpoint', () => {
    const domain = read('src/api/domain.ts');
    const types = read('src/types/dedupe.ts');

    assert.match(domain, /diagnosePair:/);
    assert.match(domain, /\/api\/scans\/diagnose-pair/);
    assert.match(domain, /DedupeDiagnosticResponse/);
    assert.match(types, /interface DedupeDiagnosticResponse/);
    assert.match(types, /SAME_FILESYSTEM_ENTRY/);
    assert.match(types, /EXACT_CONTENT_DUPLICATE/);
  });

  test('scan list and scan detail both expose duplicate diagnostics', () => {
    const scans = read('src/pages/Scans/index.tsx');
    const detail = read('src/pages/Scans/ScanDetail.tsx');

    assert.match(scans, /DedupeDiagnosticModal/);
    assert.match(scans, />\s*重复诊断\s*</);
    assert.match(detail, /DedupeDiagnosticModal/);
    assert.match(detail, /scanJobId=\{scanId\}/);
    assert.match(detail, />\s*重复诊断\s*</);
  });

  test('diagnostic modal is explicitly read-only and surfaces inode hash and scan evidence', () => {
    const modal = read('src/components/dedupe/DedupeDiagnosticModal.tsx');
    const css = read('src/styles/v056-right-workspace-v2.css');

    assert.match(modal, /只读诊断/);
    assert.match(modal, /Device \/ Inode/);
    assert.match(modal, /SHA-256/);
    assert.match(modal, /当时属于同一重复组/);
    assert.match(modal, /match-links/);
    assert.doesNotMatch(modal, /deleteScan\(|createDedupePlan\(|executePlan\(|quarantineApi/);
    assert.match(css, /\.nfc-dedupe-diagnostic-path-grid/);
    assert.match(css, /\.nfc-dedupe-diagnostic-scan-grid/);
  });
});
