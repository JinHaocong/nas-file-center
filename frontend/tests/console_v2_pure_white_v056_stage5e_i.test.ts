import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const css = read('src/styles/v056-right-workspace-v2.css');
const entry = read('src/main.tsx');
const browser = read('scripts/browser-workspace-cascade.mjs');
const ci = read('../.github/workflows/ui-v044-validation.yml');

describe('Pure White Stage 5E-I v056 final cascade authority', () => {
  test('retire two unconditional early-only duplicate selectors without changing later winners', () => {
    assert.doesNotMatch(css, /\.nfc-app-main \.nfc-dashboard-page \.nfc-dashboard-rail\s*\{\s*gap:\s*22px;\s*\}/,
      'Old 22px dashboard rail declaration would be overwritten by late 14px winner');
    assert.doesNotMatch(css, /\.nfc-app-main \.nfc-media-page \.nfc-page-alert\s*\{\s*margin:\s*14px 0 18px;\s*\}/,
      'Old 14px 0 18px media alert margin would be overwritten by late winner');
    assert.match(css, /\.nfc-app-main \.nfc-dashboard-page \.nfc-dashboard-rail\s*\{\s*gap:\s*14px;\s*\}/);
    assert.match(css, /\.nfc-app-main \.nfc-media-page \.nfc-page-alert\s*\{\s*margin:\s*12px 14px 14px;\s*\}/);
    assert.match(css, /\.nfc-app-main \.nfc-media-page \.nfc-page-alert\s*\{\s*border:\s*0;/,
      'Independent later warning surface styles must survive');
  });

  test('responsive rail overrides and source import order are unchanged', () => {
    assert.match(css, /@media \(max-width: 1199px\)[\s\S]*?\.nfc-app-main \.nfc-dashboard-page \.nfc-dashboard-rail\s*\{\s*gap:\s*12px;/);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*?\.nfc-app-main \.nfc-dashboard-page \.nfc-dashboard-rail\s*\{[^}]*grid-template-columns:\s*1fr;/);
    const v055 = entry.indexOf("import './styles/v055-workspace-breathing.css';");
    const v056 = entry.indexOf("import './styles/v056-right-workspace-v2.css';");
    const native = entry.indexOf("import './styles/console-v2.css';");
    assert.ok(v055 !== -1 && v055 < v056 && v056 < native);
    assert.doesNotMatch(css, /\.(?:ant-[a-z][\w-]*|anticon\b)/);
  });

  test('retire old v056 isolated phone-width shadow and keep the later column fix', () => {
    assert.doesNotMatch(css, /\.nfc-app-main \.nfc-page-header-copy\s*\{\s*max-width:\s*100%;\s*\}/);
    const later = css.slice(css.indexOf('/* Responsive spacing correction'));
    assert.match(later, /@media \(max-width: 767px\)/);
    assert.match(later, /\.nfc-app-main \.nfc-page-header-copy\s*\{\s*width:\s*100%;\s*max-width:\s*100%;\s*flex:\s*0 1 auto;/);
    assert.match(css, /@media \(max-width: 1199px\)[\s\S]*?\.nfc-app-main \.nfc-page-header-copy\s*\{\s*flex:\s*1 1 620px/);
    assert.match(read('src/styles/console-v2.css'),
      /\.nfc-v2-shell \.nfc-v2-dashboard-hero \.nfc-page-header-copy\s*\{\s*flex:\s*0 1 auto/);
    const entry = read('src/main.tsx');
    assert.ok(entry.indexOf("import './styles/v056-right-workspace-v2.css';") <
      entry.indexOf("import './styles/console-v2.css';"));
  });

  test('full read-only Chromium workspace and dense ledger gates remain active', () => {
    for (const needle of [
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      "'/dashboard'", "'/media'", "'/quarantine'",
      'Media metrics overflow viewport',
      'Wide table must own horizontal overflow',
      '32/32 cases, 352 screenshots',
      "request.method() !== 'GET'", 'url.origin !== BASE',
      'status: 405', 'assert.deepEqual(writes, []', 'assert.deepEqual(outbound, []',
    ]) assert.ok(browser.includes(needle), needle);
    for (const needle of [
      'Checkout exact candidate HEAD', 'Verify candidate identity',
      'node scripts/browser-workspace-cascade.mjs',
      'node scripts/browser-task-ledger-states.mjs',
      'node scripts/browser-indexes-ledger-states.mjs',
      'node scripts/browser-media-ledger-states.mjs',
      'frontend/artifacts/browser-workspace-cascade/*.png',
      'frontend/artifacts/browser-media-ledger-states/*.png',
    ]) assert.ok(ci.includes(needle), needle);
  });
});
