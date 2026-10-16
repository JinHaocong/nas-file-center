import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const primitive = read('src/components/ui/ConsoleCheckbox.tsx');
const media = read('src/pages/Media/index.tsx');
const quarantine = read('src/pages/Quarantine/index.tsx');
const ci = read('../.github/workflows/ui-v044-validation.yml');
const mediaBrowser = read('scripts/browser-media-ledger-states.mjs');
const workspaceBrowser = read('scripts/browser-workspace-cascade.mjs');

describe('Pure White Stage 5E-J shared native checkbox selection boundary', () => {
  test('primitive remains controlled native input without implicit permissions or mutations', () => {
    for (const token of [
      "React.forwardRef<HTMLInputElement, ConsoleCheckboxProps>",
      "'type' | 'checked' | 'defaultChecked' | 'onChange'",
      'checked: boolean;', 'onCheckedChange: (checked: boolean) => void;',
      '<input {...props} ref={ref} type="checkbox" checked={checked} disabled={disabled}',
      'event.currentTarget.checked',
      "ConsoleCheckbox.displayName = 'ConsoleCheckbox'",
    ]) assert.ok(primitive.includes(token), token);
    assert.doesNotMatch(primitive, /useState|useMutation|fetch\(|\bapi\.|isAdmin|can_direct_delete|executePlan|purge|unlink/);
    assert.doesNotMatch(primitive, /<button|role="checkbox"|onClick/);
  });

  test('Media uses the shared checkbox for available-only queue roots and frozen corrupt evidence', () => {
    assert.equal((media.match(/<ConsoleCheckbox\b/g) || []).length, 3);
    for (const token of [
      "import { ConsoleCheckbox } from '../../components/ui/ConsoleCheckbox'",
      'checked={roots.includes(option.value)}',
      'disabled={option.disabled}',
      'onCheckedChange={checked => onChange(checked',
      'roots.filter(value => value !== option.value)',
      "Boolean(isAdmin && record.integrity_status === 'corrupt' && record.can_direct_delete)",
      'checked={canSelect(record) && selectedIds.includes(record.id)}',
      'disabled={!canSelect(record) || deletePreviewBusy || deleteBusy}',
      'onCheckedChange={checked => toggleRow(record, checked)}',
      'checked={pageAllSelected}',
      'disabled={!isAdmin || pageEligibleIds.length === 0 || deleteBusy || deletePreviewBusy}',
      'onCheckedChange={togglePage}',
      'aria-label="选择本页可永久删除的损坏媒体"',
      'selectionVersion.current !== deleteSnapshot.selectionVersion',
      'mediaApi.previewCorruptDelete(uniqueIds)',
    ]) assert.ok(media.includes(token), token);
    assert.doesNotMatch(media, /<input type="checkbox"/);
  });

  test('Quarantine reuses only-active row/page controls without changing bulk gates or Plan lifecycle', () => {
    assert.equal((quarantine.match(/<ConsoleCheckbox\b/g) || []).length, 2);
    for (const token of [
      "import { ConsoleCheckbox } from '../../components/ui/ConsoleCheckbox'",
      "record.state === 'active' && selectedEntryIds.includes(record.id)",
      "disabled={record.state !== 'active'}",
      'onCheckedChange={checked => toggleSelected(record, checked)}',
      'checked={currentPageAllSelected}',
      'disabled={currentPageSelectableIds.length === 0}',
      'onCheckedChange={toggleCurrentPage}',
      'aria-label="选择当前页所有 active 隔离条目"',
      'getBulkSelectableEntryIds(items)',
      'selectedEntryIds.length === 0 || !isAdmin || isSafeMode || !allowDelete',
      'quarantineApi.resolveBulkFilteredEntryIds(snapshot)',
    ]) assert.ok(quarantine.includes(token), token);
    assert.doesNotMatch(quarantine, /<input type="checkbox"/);
  });


  test('real Chrome audits 64 native Media/Quarantine keyboard checkbox focus cases', () => {
    const mediaCss = read('src/styles/console-v2-media.css');
    const quarantineCss = read('src/styles/console-v2-quarantine-ledger.css');
    const source = read('scripts/browser-workspace-cascade.mjs');
    const manifest = 'frontend/artifacts/browser-workspace-cascade/checkbox-keyboard-audit.json';
    assert.match(mediaCss,
      /\.nfc-v2-shell \.nfc-v2-media-page \.nfc-v2-media-checkbox:focus-visible\s*\{\s*outline:3px solid var\(--nfc-media-accent\) !important;/);
    assert.match(quarantineCss,
      /\.nfc-v2-shell \.nfc-v2-quarantine-ledger \.nfc-v2-quarantine-checkbox:focus-visible\s*\{\s*outline:3px solid var\(--nfc-q-ledger-accent\) !important;/);
    for (const css of [mediaCss, quarantineCss]) assert.match(css,
      /outline-offset:2px;\s*transition:none !important;/);
    for (const phrase of [
      "import { computedContrastRatio } from './computed-contrast.mjs'",
      'inspectNativeCheckboxKeyboard(page, item, width, theme)',
      'const eligibleId = media ? 802 : 901',
      'const blockedIds = media ? [801, 803] : [902, 903]',
      "page.getByRole('checkbox'",
      "await page.keyboard.press('Tab')",
      "await page.keyboard.press('Shift+Tab')",
      "input.matches(':focus-visible')",
      "const layers = []",
      "node = node.parentElement",
      "No opaque painted ancestor for native checkbox",
      "const paintedBackground = 'rgb('",
      "surfaceBackground: paintedBackground",
      "computedContrastRatio(state.outlineColor, state.surfaceBackground)",
      "state.outlineWidth >= 3 && contrast >= 3",
      "assert.equal(state.checked, before",
      "assert.equal(await eligible.isChecked(), before",
      "assert.equal(state.transitionDuration, '0s'",
      "checkboxKeyboardAudit.length, WIDTHS.length * THEMES.length * 2",
      "'checkbox-keyboard-audit.json'",
    ]) assert.ok(source.includes(phrase), 'Missing real read-only checkbox focus gate: ' + phrase);
    for (const phrase of [
      'const WIDTHS = visualViewports', 'const THEMES = visualThemes',
      "if (request.method() !== 'GET')",
      'assert.deepEqual(writes, []',
      'assert.deepEqual(outbound, []',
      '32/32 cases, 352 screenshots',
    ]) assert.ok(source.includes(phrase), 'Missing safe workspace visual matrix: ' + phrase);
    assert.ok(ci.includes(manifest), 'CI must upload measured checkbox focus manifest');
  });

  test('computed paint parser accepts browser color(srgb / alpha) but rejects unknown color spaces', () => {
    const browser = read('scripts/browser-workspace-cascade.mjs');
    const rgbaSource = browser.match(/const rgb = \/(.+)\/\.exec\(color\);/);
    const srgbSource = browser.match(/const srgb = \/(.+)\/\.exec\(color\);/);
    assert.ok(rgbaSource && srgbSource, 'Both actual Chromium computed color formats must be parsed');
    const rgb = new RegExp(rgbaSource[1]);
    const srgb = new RegExp(srgbSource[1]);
    const transparent = rgb.exec('rgba(0, 0, 0, 0)');
    assert.equal(transparent?.[4], '0');
    assert.equal(rgb.exec('rgb(255, 255, 255)')?.[4], undefined);
    const mixed = srgb.exec('color(srgb 0.960784 0.960784 0.952941 / 0.36)');
    assert.ok(mixed, 'real Chrome alpha-mixed surface must parse');
    assert.deepEqual(mixed?.slice(1, 5).map(Number), [0.960784, 0.960784, 0.952941, 0.36]);
    assert.equal(srgb.test('color(srgb 1 1 1)'), true);
    assert.equal(srgb.test('color(display-p3 1 1 1 / 0.5)'), false);
    for (const clause of [
      'const parsePaintedColor = color =>',
      'const channels = match.slice(1, 4).map(Number)',
      'channels[i] *= 255',
      'alpha < 0 || alpha > 1',
      'No opaque painted ancestor for native checkbox',
      'composited = layer.rgb.map',
    ]) assert.ok(browser.includes(clause), clause);
  });

  test('existing Chromium matrix must still test read-only selections, disabled states and no NAS writes', () => {
    for (const needle of [
      "name: '选择可永久删除损坏媒体 #'",
      'Healthy media must not be selectable',
      'Corrupt media with frozen evidence may be selected',
      'Unknown media must never be selectable',
      'Blocked root must remain disabled',
      "request.method() !== 'GET'",
      'assert.deepEqual(writes, []',
      'assert.deepEqual(outbound, []',
      '32/32 cases, 256 screenshots',
    ]) assert.ok(mediaBrowser.includes(needle), needle);
    for (const needle of [
      'Only active quarantine entry #901 may be selected',
      'assert.deepEqual(writes, []',
      'assert.deepEqual(outbound, []',
      '32/32 cases, 352 screenshots',
    ]) assert.ok(workspaceBrowser.includes(needle), needle);
    for (const needle of [
      'Checkout exact candidate HEAD', 'Verify candidate identity',
      'node scripts/browser-workspace-cascade.mjs',
      'node scripts/browser-media-ledger-states.mjs',
      'node scripts/browser-quarantine-bulk-overlays.mjs',
      'frontend/artifacts/browser-media-ledger-states/*.png',
    ]) assert.ok(ci.includes(needle), needle);
  });
});
