import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const index = read('src/index.css');
const entry = read('src/main.tsx');
const matrix = read('scripts/browser-workspace-cascade.mjs');
const ci = read('../.github/workflows/ui-v044-validation.yml');

function rules(selector: string): string[] {
  const escaped = selector.replace(/[.*+?^$\x7b\x7d()|[\]\\]/g, '\\$&');
  return [...index.matchAll(new RegExp('(?:^|\\n)\\s*' + escaped +
    '\\s*\\{([^}]*)\\}', 'g'))].map(m => m[1]);
}
function properties(body: string): Map<string, string> {
  const map = new Map<string, string>();
  for (const candidate of body.split(';')) {
    const colon = candidate.indexOf(':');
    if (colon > 0) map.set(candidate.slice(0, colon).trim(), candidate.slice(colon + 1).trim());
  }
  return map;
}

describe('Pure White Stage 5E-B historical index.css cascade convergence', () => {
  test('18 early overwritten declarations removed while keeping independent base declarations', () => {
    const retired: Array<[string, string[]]> = [
      ['.nfc-page-eyebrow', ['margin-bottom', 'font-size', 'letter-spacing']],
      ['.nfc-page-title', ['font-size', 'font-weight', 'line-height', 'letter-spacing']],
      ['.nfc-page-description', ['max-width', 'font-size', 'line-height']],
      ['.nfc-metric-value', ['margin-top', 'font-size', 'font-weight', 'line-height', 'letter-spacing']],
      ['.nfc-dashboard-layout', ['margin-top', 'grid-template-columns', 'gap']],
    ];
    let count = 0;
    for (const [selector, shadowed] of retired) {
      const blocks = rules(selector);
      assert.ok(blocks.length >= 2, selector + ' needs later winning block');
      const first = properties(blocks[0]);
      const later = blocks.slice(1).map(properties);
      for (const key of shadowed) {
        assert.equal(first.has(key), false, selector + ' early shadow ' + key);
        assert.ok(later.some(map => map.has(key)), selector + ' missing winner ' + key);
        count += 1;
      }
    }
    assert.equal(count, 18);
    assert.equal(properties(rules('.nfc-page-title')[0]).get('color'), 'var(--nfc-text)');
    assert.equal(properties(rules('.nfc-page-description')[0]).get('color'), 'var(--nfc-text-muted)');
    assert.equal(properties(rules('.nfc-metric-value')[0]).get('font-variant-numeric'), 'tabular-nums');
    assert.equal(properties(rules('.nfc-dashboard-layout')[0]).get('display'), 'grid');
  });

  test('later typography/metric winners are stable and imported in the original cascade order', () => {
    assert.match(index, /font-size:\s*clamp\(26px, 2\.2vw, 34px\);/);
    assert.match(index, /font-size:\s*clamp\(26px, 2\.35vw, 36px\);/);
    assert.match(index, /grid-template-columns:\s*minmax\(0, 1\.9fr\) minmax\(260px, 0\.58fr\);/);
    assert.match(index, /letter-spacing:\s*0\.05em;/);
    assert.ok(entry.indexOf("import './index.css';") <
      entry.indexOf("import './styles/v049-workspace.css';"));
    assert.ok(entry.indexOf("import './styles/v049-workspace.css';") <
      entry.indexOf("import './styles/v050-layout.css';"));
    assert.ok(entry.indexOf("import './styles/v050-layout.css';") <
      entry.indexOf("import './styles/v054-premium-system.css';"));
    assert.ok(entry.indexOf("import './styles/v054-premium-system.css';") <
      entry.indexOf("import './styles/v056-right-workspace-v2.css';"));
  });

  test('responsive real Chromium adds Indexes / Media / Quarantine and keeps earlier ledgers', () => {
    for (const token of [
      "'/dashboard'", "'/plans'", "'/tasks'",
      "'/indexes'", "'/media'", "'/quarantine'",
      "'文件索引'", "'媒体完整性'", "'文件隔离区'",
      'Media metrics overflow viewport',
      'Media metrics lost their responsive grid',
      'Ledger duplicate heading margin',
      'Desktop page must own single scrolling region',
      'assert.equal(passed, WIDTHS.length * THEMES.length)',
      '32/32 cases, 192 screenshots',
    ]) assert.ok(matrix.includes(token), token);
  });

  test('read-only safety and browser screenshot evidence remain enforced for all six pages', () => {
    for (const token of [
      'url.origin !== BASE', "request.method() !== 'GET'",
      'status: 405', 'assert.deepEqual(writes, []', 'assert.deepEqual(outbound, []',
      'item.id +', 'page.screenshot',
    ]) assert.ok(matrix.includes(token), token);
    assert.ok(ci.includes('node scripts/browser-workspace-cascade.mjs'));
    assert.ok(ci.includes('frontend/artifacts/browser-workspace-cascade/*.png'));
    assert.doesNotMatch(matrix, /(?:api|plansApi|quarantineApi)\.(?:execute|delete|purge|freeze|validate)\(/i);
  });
});
