import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { normalizeThemeMode, shouldUseDarkTheme, restoreThemeMode, persistThemeMode, syncThemeModeFromStorage, readSystemDarkPreference, watchSystemDarkPreference } from '../src/utils/themeMode';
const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 native ThemeContext and zero direct AntD imports', () => {
  test('stored tri-state mode preserves light default and rejects malformed storage', () => {
    for (const mode of ['light', 'dark', 'system'] as const) {
      assert.equal(normalizeThemeMode(mode), mode);
    }
    for (const invalid of [null, undefined, '', 'auto', 'LIGHT', ' system ', 0,
      false, {}, [], NaN]) assert.equal(normalizeThemeMode(invalid), 'light');
  });
  test('storage errors cannot block initial theme or in-session theme changes', () => {
    assert.equal(restoreThemeMode(() => 'system'), 'system');
    assert.equal(restoreThemeMode(() => 'dark'), 'dark');
    assert.equal(restoreThemeMode(() => 'unexpected'), 'light');
    assert.equal(restoreThemeMode(() => { throw new Error('storage access denied'); }), 'light');
    let saved: string | null = null;
    persistThemeMode(() => { saved = 'dark'; });
    assert.equal(saved, 'dark');
    assert.doesNotThrow(() => persistThemeMode(() => {
      throw new Error('storage quota or access denied');
    }));
  });
  test('cross-tab preference changes track valid and invalid values but ignore unrelated storage', () => {
    for (const next of ['light', 'dark', 'system'] as const) {
      assert.equal(syncThemeModeFromStorage('dark', 'nfc_theme_mode', next), next);
    }
    assert.equal(syncThemeModeFromStorage('dark', 'nfc_theme_mode', 'broken'), 'light');
    assert.equal(syncThemeModeFromStorage('dark', 'nfc_theme_mode', null), 'light',
      'removing the persisted key reverts to the established default');
    assert.equal(syncThemeModeFromStorage('dark', null, null), 'light',
      'clearing all local storage keys also removes the persisted preference');
    assert.equal(syncThemeModeFromStorage('dark', 'unrelated_setting', 'light'), 'dark');
    assert.equal(syncThemeModeFromStorage('system', 'auth_session', null), 'system');
  });
  test('provider filters storage areas and detaches cross-tab listener on unmount', () => {
    const theme = read('src/contexts/ThemeContext.tsx');
    for (const part of [
      'const handleStorage = (event: StorageEvent) => {',
      'event.storageArea !== window.localStorage',
      'syncThemeModeFromStorage(current, event.key, event.newValue)',
      "window.addEventListener('storage', handleStorage)",
      "window.removeEventListener('storage', handleStorage)",
    ]) assert.ok(theme.includes(part), part);
    assert.match(theme, /event\.storageArea !== window\.localStorage[\s\S]*?catch\s*\{\s*return;\s*\}/);
  });
  test('system media query initialization falls back safely without breaking forced modes', () => {
    assert.equal(readSystemDarkPreference(() => ({ matches: true } as MediaQueryList)), true);
    assert.equal(readSystemDarkPreference(() => ({ matches: false } as MediaQueryList)), false);
    assert.equal(readSystemDarkPreference(() => undefined), false);
    assert.equal(readSystemDarkPreference(() => { throw Error('matchMedia blocked'); }), false);
    assert.equal(readSystemDarkPreference(() => ({
      get matches() { throw Error('matches blocked'); },
    } as unknown as MediaQueryList)), false);
    assert.equal(shouldUseDarkTheme('dark', false), true);
    assert.equal(shouldUseDarkTheme('light', true), false);
  });
  test('modern matchMedia changes follow the OS and unsubscribe on unmount', () => {
    const values: boolean[] = [];
    let handler: ((event: { matches: boolean }) => void) | undefined;
    let removed = false;
    const query = {
      matches: false,
      addEventListener(type: string, callback: typeof handler) {
        assert.equal(type, 'change');
        handler = callback;
      },
      removeEventListener(type: string, callback: typeof handler) {
        assert.equal(type, 'change');
        assert.equal(callback, handler);
        removed = true;
        handler = undefined;
      },
    } as unknown as MediaQueryList;
    const cleanup = watchSystemDarkPreference(() => query, dark => values.push(dark));
    handler?.({ matches: true });
    handler?.({ matches: false });
    assert.deepEqual(values, [false, true, false]);
    cleanup();
    assert.equal(removed, true);
    assert.equal(handler, undefined);
  });
  test('legacy matchMedia listeners work, and denied APIs never crash the theme shell', () => {
    const values: boolean[] = [];
    let handler: ((event: { matches: boolean }) => void) | undefined;
    let removed = false;
    const legacy = {
      matches: true,
      addListener(callback: typeof handler) { handler = callback; },
      removeListener(callback: typeof handler) {
        assert.equal(callback, handler);
        removed = true;
        handler = undefined;
      },
    } as unknown as MediaQueryList;
    const cleanup = watchSystemDarkPreference(() => legacy, dark => values.push(dark));
    handler?.({ matches: false });
    assert.deepEqual(values, [true, false]);
    cleanup();
    assert.equal(removed, true);
    for (const bad of [
      () => undefined,
      () => { throw Error('query blocked'); },
      () => ({ matches: false, addEventListener() { throw Error('listener blocked'); } } as unknown as MediaQueryList),
    ]) assert.doesNotThrow(() => watchSystemDarkPreference(bad, () => {})());
  });
  test('ThemeProvider delegates system preference lifecycle to guarded helper', () => {
    const theme = read('src/contexts/ThemeContext.tsx');
    for (const token of [
      "window.matchMedia?.('(prefers-color-scheme: dark)')",
      'readSystemDarkPreference(systemColorSchemeQuery)',
      'watchSystemDarkPreference(systemColorSchemeQuery, setSystemDark)',
    ]) assert.ok(theme.includes(token), token);
    assert.doesNotMatch(theme, /const mediaQuery = window.matchMedia/);
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
      "restoreThemeMode(() => localStorage.getItem('nfc_theme_mode'))",
      "persistThemeMode(() => localStorage.setItem('nfc_theme_mode', newMode))",
      'shouldUseDarkTheme(mode, systemDark)',
      "window.matchMedia?.('(prefers-color-scheme: dark)')",
      'watchSystemDarkPreference(systemColorSchemeQuery, setSystemDark)',
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
  test('Stage 5E-AR real Chromium exercises theme storage, OS mode, and strict read-only boundaries', () => {
    const browser = read('scripts/browser-theme-resilience.mjs');
    const workflow = read('../.github/workflows/ui-v044-validation.yml');
    for (const token of [
      "const BASE = 'http://127.0.0.1:' + PORT",
      "page.goto(BASE + '/login'",
      "context.route('**/api/**'",
      "req.method() !== 'GET'",
      "status: 405",
      "assert.deepEqual(rejectedWrites, []",
      "selectOption('dark')",
      "selectOption('system')",
      "await first.emulateMedia({ colorScheme: 'dark' })",
      "await second.emulateMedia({ colorScheme: 'dark' })",
      "await expectTheme(second, 'dark', 'dark')",
      "Object.defineProperty(window, 'matchMedia'",
      "Object.defineProperty(window, 'localStorage'",
      "assert.deepEqual(errors, []",
      "assert.equal(completed, 4)",
      '8 widths × 4 light/dark/system themes',
      '32/32 computed CSS, 6 surfaces each',
      'assert.deepEqual(external, []',
      "route.fulfill({ response: await route.fetch() })",
    ]) assert.ok(browser.includes(token), token);
    assert.ok(workflow.includes('node scripts/browser-theme-resilience.mjs'));
    assert.ok(workflow.includes('Run read-only Chromium ThemeProvider resilience matrix'));
    assert.doesNotMatch(browser, /route\.continue\s*\(|route\.fallback\s*\(/);
    assert.doesNotMatch(browser, /https:\/\//);
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
