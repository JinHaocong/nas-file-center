import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  completedScanJobs, parseCompletedScanJobId, verifiedCompletedScanId,
} from '../src/utils/completedScanSelection';
import type { ScanJob } from '../src/types';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 native completed Scan picker and login', () => {
  test('manual scan IDs reject invalid, malformed, and unsafe numeric inputs', () => {
    for (const input of ['', '0', '-1', '+3', ' 3', '3 ', '3.14', '2e3',
      '01', 'NaN', 'Infinity', '9007199254740992', '1.0', '5abc']) {
      assert.equal(parseCompletedScanJobId(input), null, input);
    }
    assert.equal(parseCompletedScanJobId('1'), 1);
    assert.equal(parseCompletedScanJobId('27049'), 27049);
    assert.equal(parseCompletedScanJobId('9007199254740991'), Number.MAX_SAFE_INTEGER);
  });

  test('completed-only verified detail rejects foreign IDs and nonterminal jobs', () => {
    assert.equal(verifiedCompletedScanId(4, { id: 4, status: 'completed' }), 4);
    assert.equal(verifiedCompletedScanId(4, { id: 7, status: 'completed' }), null);
    for (const status of ['queued', 'running', 'failed', 'cancelled'] as const) {
      assert.equal(verifiedCompletedScanId(4, { id: 4, status }), null, status);
    }
    assert.equal(verifiedCompletedScanId(4, null), null);
    assert.equal(verifiedCompletedScanId(-1, { id: -1, status: 'completed' }), null);
  });

  test('mixed listing only exposes completed scans without mutating source', () => {
    const scans = [
      { id: 3, status: 'running' }, { id: 5, status: 'completed' },
      { id: 7, status: 'failed' }, { id: 8, status: 'completed' },
    ] as ScanJob[];
    assert.deepEqual(completedScanJobs(scans).map(x => x.id), [5, 8]);
    assert.deepEqual(scans.map(x => x.id), [3, 5, 7, 8]);
  });

  test('native scan picker retains verified manual ID and read-only selection authority', () => {
    const source = read('src/components/workflows/CompletedScanPicker.tsx');
    for (const required of [
      "queryKey: ['completedScansList']",
      'scansApi.listScans(1, 500)',
      'completedScanJobs(scansData || [])',
      "queryKey: ['scanDetailPicker', value]",
      'scansApi.getScanDetail(value!)',
      'scansApi.getScanDetail(id)',
      'verifiedCompletedScanId(id, detail)',
      'verificationGeneration.current', 'verificationInFlight.current',
      'generation !== verificationGeneration.current',
      'onChange(detail.id)', 'onChange(undefined)',
      'disabled || verificationInFlight.current',
      'if (disabled) return',
      'parseCompletedScanJobId(requested)',
      '<select', '<option', 'type="search"', 'inputMode="numeric"',
      '<StatusBadge status="completed"', 'formatScanRootLabel(index, root)',
      'formatDateTime(activeScan.finished_at)', 'formatBytes(scan.reclaimable_bytes)',
      'type="text"', "event.key === 'Enter'",
      'useConsoleToast()', 'aria-label="已选扫描任务信息"',
    ]) assert.ok(source.includes(required), required);
    assert.doesNotMatch(source, /from ['"]antd['"]|@ant-design\/icons|<Select\b|<InputNumber\b|<Tag\b/);
    assert.doesNotMatch(source, /generatePlan|executePlan|freezePlan|validatePlan|unlink|purge/);
  });

  test('native login retains auth context API, session redirect, theme tri-state and single-flight submission', () => {
    const source = read('src/pages/Login/index.tsx');
    for (const required of [
      'useAuth()', 'useTheme()', "useTitle('用户登录')",
      'await login({ username, password })',
      "navigate('/dashboard', { replace: true })",
      '<Navigate to="/dashboard" replace />',
      'submissionInFlight.current',
      'if (submissionInFlight.current || isAuthenticated',
      'type="password"', 'type="text"', 'name="username"',
      'name="password"', 'autoComplete="username"',
      'autoComplete="current-password"', 'required',
      'event.preventDefault()', 'aria-busy={loading}',
      'disabled={loading || !username.trim() || !password}',
      '<form', 'type="submit"', 'role="alert"',
      'setErrorMessage(null)', 'aria-label="关闭登录错误提示"',
      'aria-label="切换登录页主题"',
      '<option value="light">', '<option value="dark">',
      '<option value="system">', 'setMode(event.target.value as ThemeMode)',
      'nfc-login-shell', 'nfc-login-panel', 'nfc-login-brand',
    ]) assert.ok(source.includes(required), required);
    assert.doesNotMatch(source, /from ['"]antd['"]|@ant-design\/icons|<Form\b|<Dropdown\b|<Input\b/);
    assert.doesNotMatch(source, /authApi\.(login|logout)|localStorage|sessionStorage/);
  });

  test('native styles include dark, mobile, keyboard and reduced-motion support', () => {
    const css = read('src/styles/console-v2-scan-login.css');
    for (const selector of [
      '.nfc-v2-completed-scan-picker', '.nfc-v2-scan-choice',
      '.nfc-v2-completed-scan-picker .nfc-completed-scan-summary',
      '.nfc-v2-login-shell', '.nfc-v2-login-form', '.nfc-v2-login-alert',
      "data-theme='dark'", 'focus-visible', 'max-width:767px',
      'prefers-reduced-motion:reduce', 'min-height:44px',
    ]) assert.ok(css.includes(selector), selector);
    assert.ok(read('src/main.tsx').includes(
      "import './styles/console-v2-scan-login.css';"));
  });
});
