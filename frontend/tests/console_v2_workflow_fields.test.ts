import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  MAX_SCAN_ROOTS, mergeMissingRootIds, selectOrganizerRoot, toggleScanRoot,
  scanSubpathValue, moveSubpathValue, formatTouchTimeLocal, parseTouchTimeLocal,
} from '../src/utils/workflowStepFields';
const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 Scan/Move/Touch native workflow fields', () => {
  test('file mode holds 1..16 root IDs; blocks new unknown and overflow IDs', () => {
    const allowed = Array.from({length: 25}, (_, i) => i + 1);
    assert.deepEqual(toggleScanRoot([], 3, true, allowed), [3]);
    assert.deepEqual(toggleScanRoot([3, 2], 3, true, allowed), [3, 2]);
    assert.deepEqual(toggleScanRoot([3, 2], 3, false, allowed), [2]);
    assert.deepEqual(toggleScanRoot([3], 99, true, allowed), [3]);
    assert.deepEqual(toggleScanRoot([3], -1, true, allowed), [3]);
    assert.deepEqual(toggleScanRoot([3], 3.14, true, allowed), [3]);
    assert.deepEqual(toggleScanRoot(allowed.slice(0, 16), 17, true, allowed), allowed.slice(0, 16));
    assert.deepEqual(toggleScanRoot(allowed.slice(0, 16), 1, false, []), allowed.slice(1, 16));
    assert.equal(MAX_SCAN_ROOTS, 16);
  });
  test('Organizer mode uses one registered root and retains old root when list is missing', () => {
    assert.deepEqual(selectOrganizerRoot([8], 7, [7, 8]), [7]);
    assert.deepEqual(selectOrganizerRoot([8], 99, [7, 8]), [8]);
    assert.deepEqual(selectOrganizerRoot([8], 0, [7, 8]), [8]);
    assert.deepEqual(selectOrganizerRoot([8], Number.NaN, [7, 8]), [8]);
    assert.deepEqual(mergeMissingRootIds([2, 1, 2], [77, 1]), [2, 1, 77]);
    assert.deepEqual(mergeMissingRootIds([], [77]), [77]);
  });
  test('relative subpath normalization preserves old contract without silently resolving paths', () => {
    assert.equal(scanSubpathValue(' photos/2026 '), 'photos/2026');
    assert.equal(scanSubpathValue('  '), undefined);
    assert.equal(moveSubpathValue(' archive/2026 '), 'archive/2026');
    assert.equal(moveSubpathValue('  '), '');
    assert.equal(moveSubpathValue('../outside'), '../outside');
    assert.equal(scanSubpathValue('/root')!, '/root');
  });
  test('mtime_ns roundtrips local timezone and milliseconds, not UTC date input', () => {
    const d = new Date(2026, 1, 28, 23, 59, 17, 432);
    const ns = d.getTime() * 1_000_000;
    const s = formatTouchTimeLocal(ns);
    assert.match(s, /^2026-02-28T23:59:17\.432$/);
    assert.equal(parseTouchTimeLocal(s), ns);
    assert.equal(formatTouchTimeLocal(null), '');
    assert.equal(formatTouchTimeLocal(0), '');
    assert.equal(parseTouchTimeLocal(''), null);
    assert.equal(parseTouchTimeLocal('2026-02-28T23:59'), new Date(2026,1,28,23,59).getTime() * 1_000_000);
  });
  test('invalid dates, malformed input, leap days and DST-gap normalization are rejected', () => {
    for (const value of [
      '2026-02-30T12:00', '2025-02-29T12:00', '2026-13-01T10:00',
      '2026-01-01T24:00', '2026-01-01T20:61', '2026-01-01T01:01:60',
      '2026-01-01', 'not-a-date', '2026-01-01T12:00:00.1234',
    ]) assert.equal(parseTouchTimeLocal(value), null, value);
    assert.equal(parseTouchTimeLocal('2024-02-29T12:30'), new Date(2024,1,29,12,30).getTime()*1_000_000);
  });
  test('scan editor keeps registered-only root selection and no silent root loss', () => {
    const s = read('src/components/workflows/ScanStepEditor.tsx');
    for (const t of [
      "queryKey: ['indexesRootsList']", 'indexesApi.listIndexes(1, 100)',
      "mode === 'organizer'", 'MAX_SCAN_ROOTS', 'mergeMissingRootIds',
      'selectOrganizerRoot', 'toggleScanRoot', 'shownIds.map',
      '<select', 'type="checkbox"', 'role="group"', 'aria-labelledby=',
      'disabled={readOnly}', 'if (readOnly) return', 'subpath: scanSubpathValue',
      'nfc-workflow-full-control', 'aria-describedby=', 'isError',
    ]) assert.ok(s.includes(t), t);
    assert.doesNotMatch(s, /from ['"]antd['"]|<Form\b|<Select\b|<Input\b/);
  });
  test('move editor preserves saved missing root while validating new IDs', () => {
    const s = read('src/components/workflows/MoveStepEditor.tsx');
    for (const t of [
      "queryKey: ['indexesRootsList']", 'indexesApi.listIndexes(1, 100)',
      'savedUnknownRoot', 'Number.isSafeInteger(targetId)', '!available.includes(targetId)',
      'destination_root_id: targetId', 'destination_subpath: moveSubpathValue',
      'nfc-workflow-full-control', 'disabled={readOnly}', 'isError',
    ]) assert.ok(s.includes(t), t);
    assert.doesNotMatch(s, /from ['"]antd['"]|<Form\b|<Select\b|<Input\b/);
  });
  test('touch editor preserves touch_now server time and exact ns field with local editor', () => {
    const s = read('src/components/workflows/TouchStepEditor.tsx');
    for (const t of [
      'checked={step.touch_now}', 'mtime_ns: checked ? null : step.mtime_ns || Date.now() * 1_000_000',
      'if (readOnly) return', 'if (readOnly || step.touch_now) return',
      'formatTouchTimeLocal(step.mtime_ns)', 'parseTouchTimeLocal(value)',
      'type="datetime-local"', 'step="0.001"', 'required', 'disabled={readOnly}',
      '按浏览器本地时区显示', 'touch_now: false, mtime_ns: mtimeNs',
    ]) assert.ok(s.includes(t), t);
    assert.doesNotMatch(s, /from ['"]antd['"]|from ['"]dayjs['"]|<DatePicker\b|<Switch\b/);
  });
  test('portal-safe CSS covers dark mode, mobile targets, focus and reduced motion', () => {
    const css = read('src/styles/console-v2-workflow-fields.css');
    const main = read('src/main.tsx');
    for (const t of [
      '.nfc-v2-step-select', '.nfc-v2-step-datetime', '.nfc-v2-step-root-options',
      '.nfc-v2-step-root-option', '.nfc-v2-step-checkbox-label',
      "[data-theme='dark']", 'color-scheme: dark', ':focus-visible',
      '@media (max-width: 767px)', 'min-height: 44px',
      '@media (prefers-reduced-motion: reduce)',
    ]) assert.ok(css.includes(t), t);
    assert.ok(main.includes("import './styles/console-v2-workflow-fields.css';"));
  });
});
