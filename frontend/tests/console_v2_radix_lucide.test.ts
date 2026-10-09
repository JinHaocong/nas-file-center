import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 official Radix and Lucide foundation', () => {
  test('npm lockfile exactly pins official Radix and Lucide packages', () => {
    const pkg = JSON.parse(read('package.json'));
    const lock = JSON.parse(read('package-lock.json'));
    for (const name of ['lucide-react', '@radix-ui/react-dialog']) {
      assert.ok(pkg.dependencies[name], name);
      assert.equal(lock.packages[''].dependencies[name], pkg.dependencies[name]);
      assert.equal(lock.packages['node_modules/' + name].version, pkg.dependencies[name]);
      assert.ok(lock.packages['node_modules/' + name].integrity);
    }
  });

  test('console icon bridge uses actual Lucide components, not hand-written SVG paths', () => {
    const icon = read('src/components/ui/ConsoleIcon.tsx');
    assert.match(icon, /from 'lucide-react'/);
    assert.match(icon, /satisfies Record<string, LucideIcon>/);
    assert.match(icon, /const Icon = icons\[name\]/);
    assert.doesNotMatch(icon, /const paths:/);
    assert.doesNotMatch(icon, /<svg\b/);
  });

  test('administrator dialog uses official Radix focus and dismissal semantics', () => {
    const dialog = read('src/components/ChangePasswordModal.tsx');
    assert.match(dialog, /@radix-ui\/react-dialog/);
    for (const part of ['Dialog.Root', 'Dialog.Portal', 'Dialog.Overlay',
      'Dialog.Content', 'Dialog.Title', 'Dialog.Description']) {
      assert.ok(dialog.includes('<' + part), part);
    }
    assert.match(dialog, /onEscapeKeyDown=/);
    assert.match(dialog, /onPointerDownOutside=/);
    assert.match(dialog, /if \(!next && !submitting\) close\(\)/);
    assert.match(dialog, /authApi\.changePassword/);
    assert.match(dialog, /validatePasswordChange/);
    assert.doesNotMatch(dialog, /from ['"]antd['"]/);
  });

  test('dialog portal is above content and mobile navigation, with modal overlay', () => {
    const css = read('src/styles/console-v2.css');
    assert.match(css, /\.nfc-v2-dialog-overlay[\s\S]*z-index:\s*1100/);
    assert.match(css, /\.nfc-v2-dialog\[data-state='open'\][\s\S]*z-index:\s*1101/);
    assert.match(css, /prefers-reduced-motion: reduce/);
  });
});
