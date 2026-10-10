import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { POLICY_OPTIONS } from '../src/utils/constants';
import {
  defaultClassicDedupeValues, validateClassicDedupe, toClassicDedupePayload,
  splitPriorityPatterns,
} from '../src/pages/Scans/classic_dedupe_form';
import { validateDedupePair, toDedupePairPayload } from '../src/components/dedupe/diagnostic_form';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 classic dedupe and diagnostic migrations', () => {
  test('classic form accepts all authoritative policies and excludes hidden priority options', () => {
    const initial = defaultClassicDedupeValues();
    assert.equal(initial.policy, 'balanced-roots');
    for (const option of POLICY_OPTIONS) {
      assert.equal(validateClassicDedupe({ ...initial, policy: option.value,
        pathPriorityText: '*.mp4', relativePathPriorityText: 'Originals/*' }), null);
    }
    assert.equal(validateClassicDedupe({ ...initial, policy: 'bogus' }), '请选择保留策略');
    assert.equal(validateClassicDedupe({ ...initial, policy: 'path-priority', pathPriorityText: '  \n  ' }), '请输入路径优先级规则');
    assert.equal(validateClassicDedupe({ ...initial, policy: 'relative-path-preference', relativePathPriorityText: '\n' }), '请输入相对路径优先级规则');
    assert.deepEqual(splitPriorityPatterns('  /a/*\r\n \n /b/* '), ['/a/*', '/b/*']);
    assert.deepEqual(toClassicDedupePayload({ ...initial, pathPriorityText: '/ignored' }), { policy: 'balanced-roots' });
    assert.deepEqual(toClassicDedupePayload({ ...initial, policy: 'path-priority', pathPriorityText: ' /a/* \n /b/* ',
      relativePathPriorityText: 'ignored' }),
    { policy: 'path-priority', path_priority_patterns: ['/a/*', '/b/*'] });
    assert.deepEqual(toClassicDedupePayload({ ...initial, policy: 'relative-path-preference',
      relativePathPriorityText: 'Originals/*\r\nSorted/*' }),
    { policy: 'relative-path-preference', relative_path_priority_patterns: ['Originals/*', 'Sorted/*'] });
  });

  test('diagnostic payload preserves trimmed paths and null vs scan context', () => {
    assert.equal(validateDedupePair({ pathA: ' \n ', pathB: '/data/B' }), '请输入第一个完整文件路径');
    assert.equal(validateDedupePair({ pathA: '/data/A', pathB: '' }), '请输入第二个完整文件路径');
    assert.equal(validateDedupePair({ pathA: '/data/A', pathB: '/data/B' }), null);
    assert.deepEqual(toDedupePairPayload({ pathA: ' /data/A ', pathB: ' /data/B\n' }),
      { path_a: '/data/A', path_b: '/data/B', scan_job_id: null });
    assert.deepEqual(toDedupePairPayload({ pathA: '/data/A', pathB: '/data/B' }, 53),
      { path_a: '/data/A', path_b: '/data/B', scan_job_id: 53 });
  });

  test('classic plan modal preserves Draft lifecycle, pending guards, navigation and errors', () => {
    const modal = read('src/pages/Scans/DedupePlanModal.tsx');
    for (const token of [
      '<Dialog.Root', '<Dialog.Content', 'nfc-overlay-modal',
      '<ConsoleButton', '<ConsoleIcon', 'POLICY_OPTIONS.map',
      'validateClassicDedupe(values)', 'toClassicDedupePayload(values)',
      'scansApi.createDedupePlan(scanId, payload)',
      "navigate('/plans/' + res.id)", 'planMutation.isPending',
      'submittingRef.current', 'onEscapeKeyDown', 'onPointerDownOutside',
      'Freeze → Validate → Execute', 'SHA256', 'toast.error(message)',
      'planMutation.reset()', 'Number.isSafeInteger(scanId)',
    ]) assert.ok(modal.includes(token), token);
    assert.doesNotMatch(modal, /from ['"]antd['"]|@ant-design\/icons|<Form\b|<Modal\b|message\./);
  });

  test('diagnostic keeps every backend diagnosis state, path context and readonly result', () => {
    const modal = read('src/components/dedupe/DedupeDiagnosticModal.tsx');
    for (const symbol of [
      'EXACT_CONTENT_DUPLICATE', 'SAME_FILESYSTEM_ENTRY', 'DIFFERENT_SIZE',
      'DIFFERENT_CONTENT', 'PATH_NOT_FOUND', 'PATH_OUTSIDE_CONFIGURED_ROOTS',
      'SYMLINK_UNSUPPORTED', 'NOT_REGULAR_FILE', 'INDETERMINATE',
      'PATH_OUTSIDE_SCAN_ROOTS', 'QUARANTINE_EXCLUDED',
      'NOT_IN_SNAPSHOT_FILTER_OR_SCAN_TIME_STATE',
      'result.same_filesystem_entry', 'result.sha256_match', 'result.size_match',
      'result.scan.same_duplicate_group', 'pathInfo.reasons',
      'result.scan.fclones_args', 'result.scan.paths.map',
      'item.in_quarantine', 'item.is_symlink', 'item.hash_error',
      'navigator.clipboard.writeText(item.sha256)',
      'mutation.reset()', 'inFlight.current',
      'toDedupePairPayload(values, scanJobId)',
      'scansApi.diagnosePair(request)',
      'ALLOWED_ROOTS / PathGuard', '<Dialog.Content',
    ]) assert.ok(modal.includes(symbol), symbol);
    assert.doesNotMatch(modal, /from ['"]antd['"]|@ant-design\/icons|<Descriptions\b|<Alert\b|<Form\b|<Modal\b/);
  });

  test('scoped portal CSS provides responsive light, dark and reduced motion support', () => {
    const css = read('src/styles/console-v2-dedupe-overlays.css');
    const main = read('src/main.tsx');
    for (const token of ['.nfc-v2-dedupe-dialog', '.nfc-v2-diagnostic-dialog', '.nfc-v2-dedupe-overlay',
      "[data-theme='dark']", '@media (max-width: 767px)', ':focus-visible',
      'prefers-reduced-motion: reduce', 'overscroll-behavior']) assert.ok(css.includes(token), token);
    assert.ok(main.includes("import './styles/console-v2-dedupe-overlays.css';"));
  });
});
