import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { normalizeThemeMode, shouldUseDarkTheme } from '../src/utils/themeMode';
const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 native ThemeContext and zero direct AntD imports', () => {
  test('stored tri-state mode preserves light default and rejects malformed storage', () => {
    for (const mode of ['light', 'dark', 'system'] as const) {
      assert.equal(normalizeThemeMode(mode), mode);
    }
    for (const invalid of [null, undefined, '', 'auto', 'LIGHT', ' system ', 0,
      false, {}, [], NaN]) assert.equal(normalizeThemeMode(invalid), 'light');
  });
  test('light and dark override system; system mode follows media query', () => {
    assert.equal(shouldUseDarkTheme('light', true), false);
    assert.equal(shouldUseDarkTheme('light', false), false);
    assert.equal(shouldUseDarkTheme('dark', true), true);
    assert.equal(shouldUseDarkTheme('dark', false), true);
    assert.equal(shouldUseDarkTheme('system', true), true);
    assert.equal(shouldUseDarkTheme('system', false), false);
  });
  test('provider retains React context, storage, media listener cleanup and CSS contract', () => {
    const theme = read('src/contexts/ThemeContext.tsx');
    const login = read('src/pages/Login/index.tsx');
    const app = read('src/App.tsx');
    for (const part of [
      'export type { ThemeMode }', 'ThemeContext.Provider',
      "normalizeThemeMode(localStorage.getItem('nfc_theme_mode'))",
      "localStorage.setItem('nfc_theme_mode', newMode)",
      'shouldUseDarkTheme(mode, systemDark)',
      "window.matchMedia?.('(prefers-color-scheme: dark)')",
      "addEventListener('change', handleChange)", "removeEventListener('change', handleChange)",
      "document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light')",
      "document.documentElement.style.colorScheme = isDark ? 'dark' : 'light'",
      '{children}', 'export const useTheme',
    ]) assert.ok(theme.includes(part), part);
    assert.ok(login.includes('useTheme()'));
    assert.ok(login.includes('setMode(event.target.value as ThemeMode)'));
    assert.ok(app.includes('<ThemeProvider>'));
    assert.doesNotMatch(theme, /from ['"]antd['"]|antd\/locale|ConfigProvider|@ant-design\/icons/);
  });
  test('existing CSS supplies explicit light/dark theme tokens without JS provider', () => {
    const css = read('src/index.css');
    for (const token of [
      ':root {', "[data-theme='dark'] {", '--nfc-accent:',
      '--nfc-canvas:', '--nfc-surface-1:', '--nfc-surface-2:',
      '--nfc-hairline:', '--nfc-text:', '--nfc-text-muted:',
    ]) assert.ok(css.includes(token), token);
    const native = read('src/styles/console-v2.css');
    assert.ok(native.includes('.nfc-console-button'));
    assert.ok(native.includes(':focus-visible'));
  });
  test('all direct AntD import exceptions are removed; audit still fail-closes', () => {
    const guard = read('scripts/check-ant-design-tail.mjs');
    assert.ok(guard.includes('const allowed = new Set(['));
    assert.ok(!guard.includes("'src/contexts/ThemeContext.tsx'"));
    assert.ok(guard.includes('const missing = [...allowed].filter'));
    assert.ok(guard.includes('const unexpected = matches.filter(item => !item.approved)'));
    assert.ok(guard.includes('if (missing.length || unexpected.length) process.exitCode = 1'));
  });
});
