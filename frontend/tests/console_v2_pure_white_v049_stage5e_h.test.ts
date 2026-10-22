import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const v049 = read('src/styles/v049-workspace.css');
const v056 = read('src/styles/v056-right-workspace-v2.css');
const workspace = read('scripts/browser-workspace-cascade.mjs');
const workflow = read('../.github/workflows/ui-v044-validation.yml');
const entry = read('src/main.tsx');

function blocks(selector: string): string[] {
  const escaped = selector.replace(/[.*+?^$\x7b\x7d()|[\]\\]/g, '\\$&');
  const pattern = new RegExp('(?:^|\\n)' + escaped + '\\s*\\{([^}]*)\\}', 'g');
  return [...v049.matchAll(pattern)].map(match => match[1]);
}
function property(block: string, name: string): string | undefined {
  const escaped = name.replace(/-/g, '\\-');
  const match = block.match(new RegExp('(?:^|\\n)\\s*' + escaped + ':([^;]*);'));
  return match?.[1].trim();
}

// Only unconditional early same-selector properties with later winners of equal
// importance were retired. Responsive @media rules and shared styles are intact.
const retired: Array<[string, string[], number]> = [
  ['.nfc-header.nfc-header', ['top', 'min-height', 'padding', 'border-radius'], 2],
  ['.nfc-header-status', ['background'], 2],
  ['.nfc-page-header', ['background'], 2],
  ['.nfc-data-panel-header', ['padding', 'border-bottom-color'], 1],
  ['.nfc-metric-card', ['border'], 2],
  ['.nfc-metric-card:last-child', ['border-right'], 1],
  ['.nfc-metric-card:hover', [], 1],
  ['.nfc-metric-value', ['margin-top'], 1],
  ['.nfc-system-controls-page .nfc-settings-grid', ['gap'], 1],
  ['.nfc-system-controls-page .nfc-settings-grid > .nfc-data-panel > .nfc-data-panel-header',
    ['min-height', 'padding'], 2],
  ['.nfc-system-controls-page .nfc-settings-grid > .nfc-data-panel > .nfc-data-panel-body',
    ['padding'], 1],
  ['.nfc-system-controls-page .nfc-settings-subpanel', ['border-radius'], 2],
  ['.nfc-directory-browser-row', ['min-height', 'padding'], 1],
];

describe('Pure White Stage 5E-H v049 late-authority convergence', () => {
  test('23 shadowed early declarations are gone but their exact-selector winners remain', () => {
    // All 122 exact-context retirements are pinned exhaustively in the
    // consolidated owner test; this keeps the key Stage 5E-H visual contracts.
    const checks: Array<[string,string,string,string]> = [
      ['.nfc-header.nfc-header','top','v056','12px'],
      ['.nfc-header-status','background','v056','transparent'],
      ['.nfc-page-header','background','v056','transparent'],
      ['.nfc-data-panel-header','min-height','v056','0'],
      ['.nfc-metric-card','border','v056','1px solid var(--nfc-w2-hairline)'],
      ['.nfc-metric-value','margin-top','v056','12px'],
      ['.nfc-system-controls-page .nfc-settings-grid','gap','v050','18px'],
      ['.nfc-system-controls-page .nfc-settings-subpanel','border-radius','v052','12px !important'],
    ];
    const sources: Record<string,string> = {
      v050:read('src/styles/v050-layout.css'),
      v052:read('src/styles/v052-final-audit.css'),
      v056,
    };
    for(const [selector,p,owner,value] of checks) {
      assert.ok(blocks(selector).every(rule=>property(rule,p)===undefined),
        'Earlier v049 property returned: '+selector+' '+p);
      const source=sources[owner], escaped=selector.replace(/\./g,'\\.');
      const pattern=new RegExp('(?:^|\\n)'+escaped+'\\s*\\{([^}]*)\\}','g');
      assert.ok([...source.matchAll(pattern)].some(x=>property(x[1],p)===value),
        'Authoritative later property changed: '+selector+' '+p);
    }
    assert.equal(blocks('.nfc-metric-card:last-child').length,0,
      'Retired empty last-child rule must not return');
    assert.match(v056,/\.nfc-metric-card:last-child\s*\{[^}]*border-right:\s*1px solid var\(--nfc-w2-hairline\)/);
  });

  test('retain meaningful base properties, important parity, and final geometry', () => {
    assert.ok(blocks('.nfc-header.nfc-header').some(rule=>
      property(rule,'border')==='1px solid var(--nfc-border-soft) !important'));
    assert.ok(blocks('.nfc-header.nfc-header').some(rule=>
      property(rule,'background')==='color-mix(in srgb, var(--nfc-nav-surface) 86%, transparent) !important'));
    assert.ok(blocks('.nfc-metric-card').some(rule=>
      property(rule,'border-right')==='1px solid var(--nfc-v49-line)'));
    assert.ok(blocks('.nfc-metric-card').some(rule=>
      property(rule,'transition')?.includes('box-shadow 150ms ease')));
    assert.ok(blocks('.nfc-metric-card:hover').some(rule=>
      property(rule,'box-shadow')?.includes('0 14px 34px')));
    assert.ok(blocks('.nfc-system-controls-page .nfc-settings-subpanel').some(rule=>
      property(rule,'border-bottom')==='1px solid var(--nfc-v49-line) !important'));
    assert.ok(blocks('.nfc-directory-browser-row').some(rule=>
      property(rule,'min-height')==='48px'));
    assert.match(v049,/@media \(max-width:\s*767px\)/);
    assert.match(v049,/@media \(prefers-reduced-transparency:\s*reduce\)/);
    assert.ok(entry.indexOf("import './styles/v049-workspace.css'") <
      entry.indexOf("import './styles/console-v2.css'"));
  });

  test('all existing read-only Chromium workspace cases and screenshot evidence remain in CI', () => {
    for (const token of [
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      "mode: 'system', system: 'dark', effective: 'dark'",
      'real six-page empty + five-page dense CSS/status gates',
      "request.method() !== 'GET'", 'url.origin !== BASE',
      'status: 405', 'assert.deepEqual(writes, []',
      'assert.deepEqual(outbound, []',
      '32/32 cases, 352 screenshots',
    ]) assert.ok(workspace.includes(token), token);
    for (const token of [
      'Checkout exact candidate HEAD', 'Verify candidate identity',
      'node scripts/browser-workspace-cascade.mjs',
      'node scripts/browser-indexes-ledger-states.mjs',
      'node scripts/browser-media-ledger-states.mjs',
      'frontend/artifacts/browser-workspace-cascade/*.png',
      'frontend/artifacts/browser-media-ledger-states/*.png',
    ]) assert.ok(workflow.includes(token), token);
  });
});
