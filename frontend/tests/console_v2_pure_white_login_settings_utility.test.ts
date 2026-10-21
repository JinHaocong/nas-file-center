import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const loginPage = read('src/styles/pages/login.css');
const loginControls = read('src/styles/console-v2-scan-login.css');
const settings = read('src/styles/console-v2-settings.css');
const utility = read('src/styles/console-v2-utility-preview.css');

describe('Pure White Stage 4A login, settings and utility preview', () => {
  test('login uses an undecorated neutral canvas and restrained card elevation', () => {
    assert.match(loginPage, /\.nfc-login-shell\s*\{[^}]*background:\s*var\(--nfc-canvas\)/);
    assert.doesNotMatch(loginPage, /radial-gradient|\.nfc-login-panel::before/);
    assert.ok(loginPage.includes('border-radius: 12px'));
    assert.ok(loginPage.includes('rgba(20, 20, 18, 0.045)'));
    assert.ok(loginPage.includes("[data-theme='dark'] .nfc-login-panel"));
    assert.ok(loginPage.includes('@media (max-width: 767px)'));
    assert.ok(loginPage.includes('.nfc-login-submit'));
  });

  test('login and completed scan controls stay legible in light and dark without old blue', () => {
    for (const token of [
      'var(--nfc-hairline,#eaeae7)', 'var(--nfc-text,#20201f)',
      'var(--nfc-text-muted,#696965)', 'var(--nfc-accent,#262625)',
      'var(--nfc-surface-1,#242422)', 'var(--nfc-accent,#e9e9e6)',
      '.nfc-v2-login-input-wrap:focus-within',
      '.nfc-v2-login-form :is(input,button):disabled',
      '.nfc-v2-login-alert button { min-height:44px;min-width:44px;',
      'prefers-reduced-motion:reduce',
    ]) assert.ok(loginControls.includes(token), token);
    assert.doesNotMatch(loginControls, /#286ff1|#83b5ff|#1a2434|#36435a/);
    assert.ok(loginControls.includes('.nfc-v2-completed-scan-picker .nfc-v2-scan-root'));
    assert.ok(loginControls.includes('overflow-wrap:anywhere'));
  });

  test('Settings sessions are calm accessible numeric rows with mobile focus states', () => {
    for (const token of [
      '--nfc-v2-set-ink:var(--nfc-text)',
      '.nfc-v2-settings-table tbody tr:focus-within',
      'font-variant-numeric:tabular-nums',
      'overscroll-behavior-x:contain',
      '.nfc-v2-settings-mobile .nfc-session-mobile-card:focus-within',
      '.nfc-v2-settings-switch { min-height:44px;',
      '.nfc-v2-settings-mobile .nfc-mobile-record-actions .nfc-console-button { min-height:44px;',
      'prefers-reduced-motion:reduce',
    ]) assert.ok(settings.includes(token), token);
    for (const status of ['tone-success', 'tone-warning', 'tone-danger']) {
      assert.ok(settings.includes(status), status);
    }
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-settings.css';"));
  });

  test('Utility Preview remains tabular, responsive and neutral across themes', () => {
    for (const token of [
      'var(--nfc-surface-2,#f5f5f3)', 'var(--nfc-hairline,#eaeae7)',
      'var(--nfc-text,#20201f)', 'var(--nfc-accent,#262625)',
      'var(--nfc-surface-1,#242422)', 'var(--nfc-accent,#e9e9e6)',
      '.nfc-v2-utility-table tbody tr:focus-within',
      'font-variant-numeric:tabular-nums',
      '.nfc-v2-utility-mobile .nfc-utility-candidate-mobile-card:focus-within',
      'overflow-wrap:anywhere', 'min-height:44px',
      'prefers-reduced-motion:reduce',
    ]) assert.ok(utility.includes(token), token);
    assert.doesNotMatch(utility, /#286ff1|#83b5ff|#1a2434|#111827/);
    for (const status of ['.nfc-v2-utility-notice.is-warning', '.nfc-v2-utility-notice.is-error']) {
      assert.ok(utility.includes(status), status);
    }
  });

  test('Login/Settings old blue-black surfaces defer to scoped Pure White owners with live Chromium paint guards', () => {
    for (const token of [
      '--nfc-v2-login-canvas: #ffffff', '--nfc-v2-login-canvas: #171716',
      '--nfc-v2-login-panel: #ffffff', '--nfc-v2-login-panel: #242422',
      '--nfc-v2-login-line: #eaeae7', '--nfc-v2-login-line: #383834',
      '--nfc-v2-login-muted: #62625e', '--nfc-v2-login-muted: #bebeba',
      'background: var(--nfc-v2-login-canvas);',
      '.nfc-v2-login-shell .nfc-login-panel',
    ]) assert.ok(loginControls.includes(token), token);
    for (const token of [
      '--nfc-shell-card-bg:#ffffff;', '--nfc-shell-card-bg:#242422;',
      '--nfc-shell-card-border:#eaeae7;', '--nfc-shell-card-border:#383834;',
      '--nfc-w2-surface:#ffffff;', '--nfc-w2-surface:#242422;',
      '--nfc-w2-surface-soft:#f7f7f5;', '--nfc-w2-surface-soft:#2d2d2a;',
      '--nfc-v2-set-paper:#242422;', '--nfc-v2-set-soft:#2d2d2a;',
    ]) assert.ok(settings.includes(token), token);
    const browser = read('scripts/browser-full-route-visual.mjs');
    for (const marker of [
      "item.id === 'login' || item.id === 'settings'",
      "readPaint('.nfc-v2-login-shell')",
      "readPaint('.nfc-v2-settings .nfc-settings-grid > .nfc-data-panel')",
      "readPaint('.nfc-v2-settings .nfc-settings-subpanel')",
      "painted.shell?.image === 'none'",
      "painted.subpanel?.background === required.soft",
      'audit.loginSettingsPaint = { ...painted, required }',
      'Login/Settings actual neutral paint mismatch',
    ]) assert.ok(browser.includes(marker), 'Missing live paint audit: ' + marker);
    assert.ok(read('../.github/workflows/ui-v044-validation.yml')
      .includes('node scripts/browser-full-route-visual.mjs'));
    const src = read('src/main.tsx');
    assert.ok(src.indexOf("import './styles/v056-right-workspace-v2.css';") <
      src.indexOf("import './styles/console-v2-scan-login.css';"));
    assert.ok(src.indexOf("import './styles/v056-right-workspace-v2.css';") <
      src.indexOf("import './styles/console-v2-settings.css';"));
  });

  test('login still has auth single-flight and tri-state theme without storing credentials', () => {
    const src = read('src/pages/Login/index.tsx');
    for (const token of [
      'submissionInFlight.current', 'await login({ username, password })',
      'navigate(\'/dashboard\', { replace: true })', 'type="password"',
      'autoComplete="current-password"', 'aria-busy={loading}',
      'disabled={loading || !username.trim() || !password}',
      '<option value="light">', '<option value="dark">',
      '<option value="system">', 'role="alert"',
    ]) assert.ok(src.includes(token), token);
    assert.doesNotMatch(src, /localStorage|sessionStorage/);
  });

  test('Settings destructive actions and Utility Draft remain strictly server-guarded', () => {
    const src = read('src/pages/Settings/index.tsx');
    for (const token of [
      'Promise.all([refetchPolicy(), refetchPreview()])',
      "setConfirmation({ kind: 'retention'",
      'auditApi.clearHistory()', 'authApi.revokeSession(sessionId)',
      'getAuditRetentionApplyAvailability', 'confirmBusy',
      '<ConsoleConfirmDialog',
    ]) assert.ok(src.includes(token), token);
    const preview = read('src/pages/Workflows/UtilityWorkflowPreviewPanel.tsx');
    for (const token of [
      'sameUtilityDraftRequest(confirmation, requestNow)',
      'draftInFlight.current',
      'workflowApi.generatePlan(targetId, snapshot)',
      'utilityDraftRequest(',
      'selected_candidate_ids',
      'Freeze → Validate → Execute',
      '只生成新的 Draft Plan',
    ]) assert.ok(preview.includes(token), token);
    assert.doesNotMatch(preview, /plansApi\.(freezePlan|validatePlan|executePlan)|unlink|purgePlan/);
  });
});
