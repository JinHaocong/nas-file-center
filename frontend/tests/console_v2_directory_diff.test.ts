import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { DirectoryDiffResponse, DirectoryDiffRow } from '../src/api/domain';
import {
  applyDirectoryDiffVerification, buildDirectoryDiffCsv, buildDirectoryDiffRequest,
  buildDirectoryDiffVerifyRequest, directoryDiffRowLabel, directoryDiffTone,
  filterDirectoryDiffRows, formatDirectoryDiffSize,
} from '../src/utils/directoryDiffSafety';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const sameSize: DirectoryDiffRow = {
  relative_path: 'nested/picture.jpg', kind_a: 'file', kind_b: 'file',
  size_a: 1024, size_b: 1024, status: 'same_size_unverified',
};
const onlyA: DirectoryDiffRow = {
  relative_path: 'only-A.txt', kind_a: 'file', kind_b: null,
  size_a: 17, size_b: null, status: 'only_a',
};
const onlyB: DirectoryDiffRow = {
  relative_path: 'only-B.txt', kind_a: null, kind_b: 'file',
  size_a: null, size_b: 19, status: 'only_b',
};
const different: DirectoryDiffRow = {
  relative_path: 'different', kind_a: 'file', kind_b: 'file',
  size_a: 20, size_b: 21, status: 'size_different',
};
const mismatch: DirectoryDiffRow = {
  relative_path: 'mismatch', kind_a: 'file', kind_b: 'directory',
  size_a: 5, size_b: null, status: 'type_mismatch',
};
const bothDirs: DirectoryDiffRow = {
  relative_path: 'nested', kind_a: 'directory', kind_b: 'directory',
  size_a: null, size_b: null, status: 'both_directories',
};
const rows = [sameSize, onlyA, onlyB, different, mismatch, bothDirs];
const report = (items: DirectoryDiffRow[] = rows): DirectoryDiffResponse => ({
  root_a: '/nas/A', root_b: '/nas/B',
  entries_a: 5, entries_b: 5, skipped_symlinks_a: 1, skipped_symlinks_b: 2,
  counts: { same_size_unverified: 1 }, items, total: items.length,
});
const sameDigest = 'a'.repeat(64);
const otherDigest = 'b'.repeat(64);

describe('Console v2 Directory Diff native read-only migration', () => {
  test('keeps exact two-root Preview API payload without rewriting literal paths', () => {
    assert.deepEqual(buildDirectoryDiffRequest('/nas/A', '/nas/B'),
      { root_a: '/nas/A', root_b: '/nas/B' });
    assert.deepEqual(buildDirectoryDiffRequest('/nas/A ', '/nas/B'),
      { root_a: '/nas/A ', root_b: '/nas/B' });
    assert.equal(buildDirectoryDiffRequest('', '/nas/B'), null);
    assert.equal(buildDirectoryDiffRequest('/nas/A', '   '), null);
    assert.equal(buildDirectoryDiffRequest('/nas/A', '/nas/A'), null);
  });

  test('preserves all original statuses, labels, and SHA256-specific result labels', () => {
    assert.deepEqual(rows.map(directoryDiffRowLabel), [
      '大小相同 · 待校验', '仅 A 存在', '仅 B 存在', '大小不同', '类型不同', '双方均有目录',
    ]);
    assert.equal(directoryDiffRowLabel({ ...sameSize, verification: 'content_same' }), 'SHA256 相同');
    assert.equal(directoryDiffRowLabel({ ...sameSize, verification: 'content_different' }), 'SHA256 不同');
    assert.equal(directoryDiffTone({ ...sameSize, verification: 'content_different' }), 'danger');
    assert.equal(directoryDiffTone({ ...sameSize, verification: 'content_same' }), 'success');
    assert.equal(directoryDiffTone(sameSize), 'neutral');
  });

  test('differences exclude unverified equal size until a different digest is confirmed', () => {
    const current = filterDirectoryDiffRows(rows, 'differences');
    assert.deepEqual(current.map(row => row.relative_path), [
      'only-A.txt', 'only-B.txt', 'different', 'mismatch',
    ]);
    const verifiedDifferent = { ...sameSize, verification: 'content_different' as const };
    const after = filterDirectoryDiffRows([verifiedDifferent, ...rows.slice(1)], 'differences');
    assert.equal(after[0].relative_path, sameSize.relative_path);
    assert.deepEqual(filterDirectoryDiffRows([verifiedDifferent], 'verified'), [verifiedDifferent]);
    assert.deepEqual(filterDirectoryDiffRows([verifiedDifferent], 'unverified'), []);
  });

  test('status filters retain legacy semantics and do not mutate source rows', () => {
    assert.deepEqual(filterDirectoryDiffRows(rows, 'all'), rows);
    assert.deepEqual(filterDirectoryDiffRows(rows, 'unverified'), [sameSize]);
    assert.deepEqual(filterDirectoryDiffRows(rows, 'only_a'), [onlyA]);
    assert.deepEqual(filterDirectoryDiffRows(rows, 'only_b'), [onlyB]);
    assert.deepEqual(filterDirectoryDiffRows(rows, 'type_mismatch'), [mismatch]);
    assert.deepEqual(filterDirectoryDiffRows(rows, 'size_different'), [different]);
    assert.deepEqual(filterDirectoryDiffRows(rows, 'verified'), []);
  });

  test('SHA256 eligibility requires a current server-provided equal-size file pair', () => {
    const req = buildDirectoryDiffVerifyRequest(report(), sameSize);
    assert.deepEqual(req, {
      root_a: '/nas/A', root_b: '/nas/B', relative_path: 'nested/picture.jpg',
    });
    for (const row of [onlyA, onlyB, different, mismatch, bothDirs]) {
      assert.equal(buildDirectoryDiffVerifyRequest(report(), row), null);
    }
    assert.equal(buildDirectoryDiffVerifyRequest(null, sameSize), null);
    assert.equal(buildDirectoryDiffVerifyRequest(report([sameSize]), { ...sameSize, relative_path: 'unknown' }), null);
    assert.equal(buildDirectoryDiffVerifyRequest(report([{ ...sameSize, size_b: 9 }]), sameSize), null);
    assert.equal(buildDirectoryDiffVerifyRequest(report([{ ...sameSize, kind_a: 'directory' }]), sameSize), null);
  });

  test('successful identical hash updates only matching row without mutating input', () => {
    const before = report();
    const request = buildDirectoryDiffVerifyRequest(before, sameSize)!;
    const result = applyDirectoryDiffVerification(before, request, {
      relative_path: request.relative_path,
      sha256_a: sameDigest, sha256_b: sameDigest, same_content: true,
    });
    assert.equal(result?.items[0].verification, 'content_same');
    assert.equal(result?.items[1], onlyA);
    assert.equal(before.items[0].verification, undefined);
  });

  test('different digest is labeled as actual difference, never merely size difference', () => {
    const request = buildDirectoryDiffVerifyRequest(report(), sameSize)!;
    const response = applyDirectoryDiffVerification(report(), request, {
      relative_path: request.relative_path,
      sha256_a: sameDigest, sha256_b: otherDigest, same_content: false,
    });
    assert.equal(response?.items[0].verification, 'content_different');
    assert.equal(response?.items[0].status, 'same_size_unverified');
    assert.deepEqual(filterDirectoryDiffRows(response!.items, 'differences').map(row => row.relative_path)[0],
      sameSize.relative_path);
  });

  test('refuses stale roots, wrong relative path, or contradictory digest result', () => {
    const request = buildDirectoryDiffVerifyRequest(report(), sameSize)!;
    const valid = { relative_path: request.relative_path, sha256_a: sameDigest,
      sha256_b: otherDigest, same_content: false };
    assert.equal(applyDirectoryDiffVerification(report(), { ...request, root_a: '/nas/OLD' }, valid), null);
    assert.equal(applyDirectoryDiffVerification(report(), request, { ...valid, relative_path: 'other' }), null);
    assert.equal(applyDirectoryDiffVerification(report(), request, { ...valid, same_content: true }), null);
    assert.equal(applyDirectoryDiffVerification(report(), request, { ...valid, sha256_a: 'broken' }), null);
    assert.equal(applyDirectoryDiffVerification(report([onlyA]), request, valid), null);
  });

  test('formatting keeps bytes, IEC units and null markers', () => {
    assert.equal(formatDirectoryDiffSize(null), '—');
    assert.equal(formatDirectoryDiffSize(0), '0 B');
    assert.equal(formatDirectoryDiffSize(1023), '1023 B');
    assert.equal(formatDirectoryDiffSize(1024), '1.00 KiB');
    assert.equal(formatDirectoryDiffSize(1048576), '1.00 MiB');
  });

  test('CSV keeps exact six legacy columns, selected filter and spreadsheet neutralization', () => {
    const row = { ...onlyA, relative_path: ' =SUM("A1")' };
    const csv = buildDirectoryDiffCsv([row]);
    assert.ok(csv.startsWith('\uFEFF"relative_path","type_a","type_b","size_a_bytes","size_b_bytes","result"'));
    assert.ok(csv.includes("' =SUM"));
    assert.ok(csv.includes('""A1""'));
    assert.ok(csv.includes('\r\n'));
    assert.equal(csv.includes('nested/picture.jpg'), false);
    assert.ok(buildDirectoryDiffCsv([{ ...onlyA, relative_path: '@eval' }]).includes("'@eval"));
    assert.ok(buildDirectoryDiffCsv([{ ...onlyA, relative_path: '-cmd' }]).includes("'-cmd"));
  });

  test('page wiring keeps Preview and explicit SHA256 separated from all mutation actions', () => {
    const page = read('src/pages/DirectoryDiff/index.tsx');
    const helper = read('src/utils/directoryDiffSafety.ts');
    for (const token of [
      'directoryDiffApi.preview', 'directoryDiffApi.verify', 'useConsoleToast',
      '<DirectoryPicker value={rootA}', '<DirectoryPicker value={rootB}',
      'requestTicket.current !== ticket', 'activePreviewKey.current !== key',
      'clearResult();', 'previewGuard.current', 'verifyGuard.current',
      'buildDirectoryDiffRequest(rootA, rootB)', 'buildDirectoryDiffVerifyRequest(result, row)',
      'applyDirectoryDiffVerification', '<ConsoleButton', '<ConsoleEmpty',
      '<ConsolePagination', '<ResponsiveDataView', '<CodePath',
      'getPaginationState', 'visiblePage.map(', 'exportCsv(visible)',
      '单文件校验上限 256 MiB',
    ]) assert.ok(page.includes(token), token);
    assert.ok(helper.includes('same_size_unverified'));
    assert.doesNotMatch(page, /from ['"]antd['"]|@ant-design\/icons|<Table\b|<Form\b|<Pagination\b|<Tag\b/);
    assert.doesNotMatch(page, /createPlan|freezePlan|validatePlan|executePlan|deletePlan|moveFile|renameFile/);
  });

  test('scoped CSS provides dark, mobile, focus-visible and reduced-motion safety', () => {
    const css = read('src/styles/console-v2-directory-diff.css');
    for (const token of [
      '.nfc-v2-directory-diff', '.nfc-v2-directory-diff-form',
      '.nfc-v2-directory-diff-table', '.nfc-v2-directory-diff-mobile',
      '.nfc-v2-directory-diff-tag', "[data-theme='dark']",
      '@media (max-width:767px)', 'min-height:44px', ':focus-visible',
      '@media (prefers-reduced-motion:reduce)',
    ]) assert.ok(css.includes(token), token);
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-directory-diff.css';"));
  });
});
