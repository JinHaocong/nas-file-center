import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.1 premium visual pass contract', () => {
  test('design tokens expose premium elevation and motion primitives', () => {
    const css = read('src/index.css');
    for (const token of [
      '--nfc-shadow-xs',
      '--nfc-shadow-sm',
      '--nfc-shadow-md',
      '--nfc-ease-standard',
      '--nfc-ease-emphasized',
      '--nfc-motion-enter',
    ]) {
      assert.ok(css.includes(token), token);
    }
  });

  test('app shell and shared surfaces have deliberate motion', () => {
    const css = read('src/index.css');
    for (const selector of [
      '.nfc-page-content > *',
      '.nfc-page-header',
      '.nfc-data-panel',
      '.nfc-metric-card',
      '.nfc-quick-action',
      '.nfc-sidebar-menu',
    ]) {
      assert.ok(css.includes(selector), selector);
    }
    assert.ok(css.includes('@keyframes nfc-enter'));
    assert.ok(css.includes('@keyframes nfc-status-pulse'));
  });

  test('native controls and surfaces share NFC chrome without historical AntD selectors', () => {
    const css = read('src/index.css');
    const native = read('src/styles/console-v2.css');
    for (const selector of [
      '.nfc-brand', '.nfc-page-header', '.nfc-data-panel',
      '.nfc-metric-card', '.nfc-task-mobile-card', '.nfc-form-note',
    ]) assert.ok(css.includes(selector), selector);
    assert.ok(css.includes('box-shadow: var(--nfc-shadow-sm)'));
    assert.ok(native.includes('.nfc-v2-dialog .nfc-console-button'));
    assert.doesNotMatch(css, /\.(?:ant-[a-z][\w-]*|anticon\b)/);
  });

  test('native sidebar active state keeps visible navigation emphasis', () => {
    const nav = read('src/styles/console-v2.css');
    const sidebar = read('src/components/Sidebar.tsx');
    const css = read('src/index.css');
    assert.match(nav, /\.nfc-v2-nav-item\.is-active\s*\{/);
    assert.match(sidebar, /nfc-v2-nav-item.*is-active/);
    assert.ok(css.includes('var(--nfc-ease-standard)'));
  });

  test('status badge supports live-state pulse while reduced motion still wins', () => {
    const source = read('src/components/ui/StatusBadge.tsx');
    assert.ok(source.includes('nfc-status-live'));
    for (const status of ['running', 'executing', 'validating']) {
      assert.ok(source.includes(status), status);
    }
    const css = read('src/index.css');
    assert.ok(css.includes('prefers-reduced-motion: reduce'));
    assert.ok(css.includes('.nfc-status-live'));
  });

  test('native theme provider delegates UI chrome to light/dark CSS tokens', () => {
    const source = read('src/contexts/ThemeContext.tsx');
    const media = read('src/utils/themeMode.ts');
    const css = read('src/index.css');
    const native = read('src/styles/console-v2.css');
    for (const token of [
      'ThemeContext.Provider', "localStorage.getItem('nfc_theme_mode')",
      "localStorage.setItem('nfc_theme_mode', newMode)",
      "'(prefers-color-scheme: dark)'",
      'watchSystemDarkPreference(systemColorSchemeQuery, setSystemDark)',
      "setAttribute('data-theme'",
      'document.documentElement.style.colorScheme',
    ]) assert.ok(source.includes(token), token);
    for (const token of [
      "media.addEventListener('change', handleChange)",
      "media.removeEventListener('change', handleChange)",
      'media.addListener(handleChange)',
      'media.removeListener(handleChange)',
    ]) assert.ok(media.includes(token), token);
    for (const token of [':root {', "[data-theme='dark']", '--nfc-accent:',
      '--nfc-surface-1:', '--nfc-text:']) assert.ok(css.includes(token), token);
    assert.ok(native.includes('.nfc-console-button'));
    assert.ok(native.includes('focus-visible'));
    assert.doesNotMatch(source, /from ['"]antd['"]|ConfigProvider|antdTheme|locale={zhCN}/);
  });

  test('representative surfaces add stagger, section accents and refined interaction chrome', () => {
    const css = read('src/index.css');
    for (const selector of [
      '.nfc-data-panel-title::before',
      '.nfc-metric-grid .nfc-metric-card:nth-child(2)',
      '.nfc-dashboard-layout > :nth-child(2)',
      '.nfc-mobile-record-list > *',
      '.nfc-header-actions',
      '.nfc-brand-mark',
      '.nfc-form-note',
      '.nfc-step-editor-note',
      '::-webkit-scrollbar',
    ]) {
      assert.ok(css.includes(selector), selector);
    }
  });

  test('frozen design contract has a v0.4.1 premium visual amendment', () => {
    const source = read('../DESIGN.md');
    assert.ok(source.includes('v0.4.1 Premium Visual Pass'));
    assert.ok(source.includes('Motion hierarchy'));
    assert.ok(source.includes('Ant Design is infrastructure, not visual identity'));
  });
});
