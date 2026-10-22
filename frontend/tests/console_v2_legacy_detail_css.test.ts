import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 legacy v0.4.8 CSS retirement — tranche 2', () => {
  test('reviewed detail layer contains zero obsolete AntD class selectors', () => {
    const css = read('src/styles/v048-detail.css');
    assert.doesNotMatch(css, /\.(?:ant-[a-z][\w-]*|anticon\b)/);
    assert.ok(css.length > 6000, 'native v0.4.8 details must remain');
    assert.ok(css.includes('.nfc-responsive-descriptions {'));
    assert.doesNotMatch(css, /\.nfc-page-title\s*\{/,
      'Retired detail-only page-title rule must remain absent');
    assert.match(read('src/styles/v056-right-workspace-v2.css'),
      /\.nfc-page-title\s*\{[^}]*text-wrap:\s*balance/,
      'Final text-wrap owner must remain in v056');
  });

  test('mixed table hover selector keeps only the native keyboard focus path', () => {
    const old = read('src/styles/v048-detail.css');
    const final = read('src/styles/v056-right-workspace-v2.css');
    const mobile = read('src/styles/v051-product-polish.css');
    assert.doesNotMatch(old, /\.nfc-row-actions\s*\{[^}]*opacity:\s*0\.78/,
      'Retired early opacity must not return');
    assert.match(final, /\.nfc-row-actions\s*\{[^}]*opacity:\s*0\.56/);
    assert.match(final, /\.nfc-row-actions:focus-within\s*\{[^}]*opacity:\s*1/);
    assert.match(mobile, /@media \(max-width: 767px\)[\s\S]*\.nfc-row-actions\s*\{[^}]*opacity:\s*1/);
    assert.match(old, /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.nfc-row-actions\s*\{[^}]*transition:\s*none/);
  });

  test('native mobile pagination and details keep effective responsive presentation', () => {
    const old = read('src/styles/v048-detail.css');
    const final = read('src/styles/v049-workspace.css');
    assert.match(old, /\.nfc-mobile-pagination\s*\{[^}]*border-top:\s*1px solid var\(--nfc-premium-line\)/,
      'Distinct historical top edge must remain');
    assert.match(final, /\.nfc-mobile-pagination\s*\{[^}]*min-height:\s*50px;[^}]*padding:\s*9px 12px/);
    assert.match(final, /\.nfc-responsive-descriptions\s*\{[^}]*border-radius:\s*var\(--nfc-v49-radius-lg\) !important/);
    assert.match(final, /@media \(max-width: 420px\)[\s\S]*\.nfc-responsive-descriptions\s*\{[^}]*grid-template-columns:\s*1fr/);
    assert.match(old, /@keyframes nfc-detail-live-pulse/);
    assert.match(old, /@media \(prefers-reduced-motion: reduce\)[\s\S]*animation:\s*none/);
  });

  test('native modal and empty chrome retain their later, component-owned styles', () => {
    const entry = read('src/main.tsx');
    assert.ok(entry.indexOf("import './styles/v048-detail.css';") <
      entry.indexOf("import './styles/console-v2.css';"));
    const native = read('src/styles/console-v2.css');
    const phase2 = read('src/styles/console-v2-phase2.css');
    assert.ok(native.includes('.nfc-v2-dialog'));
    assert.ok(phase2.includes('.nfc-console-empty'));
    assert.ok(phase2.includes('.nfc-console-pagination'));
    assert.ok(entry.includes("import './styles/console-v2-phase2.css';"));
  });

  test('CSS import guard includes reviewed v048/v049/v054/v056', () => {
    const guard = read('scripts/check-console-css-ownership.mjs');
    assert.ok(guard.includes("'legacy-reviewed:v048-detail.css'"));
    assert.ok(guard.includes("'settings:pages/settings.css'"));
    assert.ok(guard.includes("'legacy-reviewed:v048.css'"));
    assert.ok(guard.includes("'legacy-reviewed:v049-workspace.css'"));
    assert.ok(guard.includes("'legacy-reviewed:v054-premium-system.css'"));
    assert.ok(guard.includes("'legacy-reviewed:v056-right-workspace-v2.css'"));
    assert.ok(guard.includes("if (errors.length) process.exitCode = 1"));
    const docs = read('../docs/console-v2-css-ownership.md');
    assert.ok(docs.includes('PR #185'));
    assert.ok(docs.includes('index.css'));
    assert.ok(docs.includes('visual acceptance'));
  });
});
