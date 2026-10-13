import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
const read = (p: string) => readFileSync(resolve(process.cwd(),p),'utf8');

describe('Console v2 reviewed v048 base CSS and safe branch cleanup', () => {
  test('reviewed v048 base layer has no AntD class selectors while retaining native colors and layout', () => {
    const css = read('src/styles/v048.css');
    assert.doesNotMatch(css, /\.(?:ant-[a-z][\w-]*|anticon\b)/);
    for (const marker of [
      ':root {', "[data-theme='dark'] {", '--nfc-premium-control: 38px',
      '.nfc-data-panel', '.nfc-data-panel-header', '.nfc-metric-grid',
      '.nfc-snapshot-note', '.nfc-form-note', '.nfc-dedupe-config-note',
      '.nfc-task-mobile-card', '@media (max-width: 767px)',
      '@media (prefers-reduced-motion: reduce)',
    ]) assert.ok(css.includes(marker), marker);
  });
  test('native overlay and pagination authority stays loaded later than legacy stylesheet', () => {
    const entry = read('src/main.tsx');
    assert.ok(entry.indexOf("import './styles/v048.css';") <
      entry.indexOf("import './styles/console-v2.css';"));
    const shell = read('src/styles/console-v2.css');
    const primitives = read('src/styles/console-v2-phase2.css');
    assert.ok(shell.includes('.nfc-v2-dialog'));
    assert.ok(primitives.includes('.nfc-console-pagination'));
    assert.ok(primitives.includes('.nfc-console-empty'));
  });
  test('CI guard includes v048 base and detail, while unreviewed index/v054 remain tracked', () => {
    const guard = read('scripts/check-console-css-ownership.mjs');
    assert.ok(guard.includes("'legacy-reviewed:v048.css'"));
    assert.ok(guard.includes("'legacy-reviewed:v048-detail.css'"));
    assert.ok(guard.includes("'settings:pages/settings.css'"));
    assert.ok(guard.includes('if (errors.length) process.exitCode = 1'));
    const docs=read('../docs/console-v2-css-ownership.md');
    assert.ok(docs.includes('PR #186'));
    assert.ok(docs.includes('index.css'));
    assert.ok(docs.includes('visual acceptance'));
  });
  test('cleanup tool defaults to a read-only preview and fails closed on protected, open or mismatched HEAD',()=>{
    const s=read('../scripts/cleanup_merged_branches.py');
    for (const token of [
      'parser.add_argument("--repo", required=True',
      'parser.add_argument("--execute", action="store_true"',
      'parser.add_argument("--min-age-days", type=int, default=7',
      'branch.get("protected")',
      'if any(p.get("state") == "open"',
      'if any(not p.get("merged_at")',
      'p.get("head", {}).get("sha") == branch["commit"]["sha"]',
      'latest["commit"]["sha"] != branch["commit"]["sha"]',
      '"/pulls?state=open&per_page=100"',
      'if not args.execute:',
      'method="DELETE"',
    ]) assert.ok(s.includes(token), token);
  });
});
