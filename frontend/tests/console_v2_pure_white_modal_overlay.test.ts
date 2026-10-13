import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const shell = read('src/styles/console-v2.css');

const findRules = (source: string, selector: string): string[] => {
  const escaped = selector.replace(/[.*+?^$\x7b\x7d()|[\]\\]/g, '\\$&');
  return [...source.matchAll(new RegExp('(?:^|\\n)\\s*' + escaped + '\\s*\\{([^}]*)\\}', 'g'))].map(match => match[1]);
};

const expectZ = (source: string, selector: string, level: number) => {
  const rules = findRules(source, selector);
  assert.ok(rules.length > 0, 'Missing ' + selector);
  assert.ok(rules.some(rule => new RegExp('z-index:\\s*' + level + '\\b').test(rule)),
    selector + ' must have z-index ' + level);
};

describe('Pure White portal overlay clarity and stacking', () => {
  test('shared Radix scrim dims with neutral gray without blurring a dialog', () => {
    const light = findRules(shell, '.nfc-v2-dialog-overlay');
    const dark = findRules(shell, "[data-theme='dark'] .nfc-v2-dialog-overlay");
    assert.equal(light.length, 1);
    assert.equal(dark.length, 1);
    assert.match(light[0], /background:\s*rgba\(32, 32, 31, \.46\)/);
    assert.match(light[0], /backdrop-filter:\s*none;/);
    assert.match(light[0], /-webkit-backdrop-filter:\s*none;/);
    assert.doesNotMatch(light[0], /blur\s*\(/);
    assert.match(dark[0], /background:\s*rgba\(0, 0, 0, \.64\)/);
  });

  test('native dialog fallback is also unblurred and theme aware', () => {
    const light = findRules(shell, '.nfc-v2-dialog::backdrop');
    const dark = findRules(shell, "[data-theme='dark'] .nfc-v2-dialog::backdrop");
    assert.equal(light.length, 1);
    assert.equal(dark.length, 1);
    assert.match(light[0], /backdrop-filter:\s*none;/);
    assert.match(light[0], /-webkit-backdrop-filter:\s*none;/);
    assert.doesNotMatch(light[0], /blur\s*\(/);
    assert.match(dark[0], /background:\s*rgba\(0, 0, 0, \.64\)/);
  });

  test('every known nested Radix portal keeps its content strictly above its scrim', () => {
    const task = read('src/styles/console-v2-task-overlays.css');
    const scan = read('src/styles/console-v2-scan-create.css');
    const directory = read('src/styles/console-v2-directory-modal.css');
    const revision = read('src/styles/console-v2-workflow-revisions.css');
    for (const [source, overlay, content, low, high] of [
      [shell, '.nfc-v2-dialog-overlay', ".nfc-v2-dialog[data-state='open']", 1100, 1101],
      [task, '.nfc-v2-sheet-overlay', '.nfc-v2-sheet.nfc-overlay-drawer', 1100, 1101],
      [scan, '.nfc-v2-scan-create-overlay', '.nfc-v2-scan-create-modal', 1190, 1191],
      [directory, '.nfc-v2-directory-overlay', '.nfc-v2-directory-dialog', 1200, 1201],
      [task, '.nfc-v2-confirm-overlay', ".nfc-v2-confirm-dialog.nfc-v2-dialog[data-state='open']", 1300, 1301],
      [revision, '.nfc-v2-revision-inspect-overlay', ".nfc-v2-revision-inspect.nfc-v2-dialog[data-state='open']", 1400, 1401],
    ] as const) {
      expectZ(source, overlay, low);
      expectZ(source, content, high);
      assert.ok(high > low);
    }
  });

  test('Radix pairing and focus/escape safety remain wired through actual components', () => {
    for (const path of [
      'src/components/scans/ScanCreateModal.tsx',
      'src/components/DirectoryPicker/DirectoryPickerModal.tsx',
      'src/components/ui/ConsoleConfirmDialog.tsx',
    ]) {
      const source = read(path);
      assert.ok(source.includes('<Dialog.Portal>'), path);
      assert.ok(source.includes('<Dialog.Overlay'), path);
      assert.ok(source.includes('<Dialog.Content'), path);
      assert.ok(source.includes('onEscapeKeyDown'), path);
      assert.ok(source.includes('onPointerDownOutside'), path);
    }
  });
});
