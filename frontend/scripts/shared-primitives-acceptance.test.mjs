/**
 * Audit the complete live TSX inventory, not a hand-selected collection of pages.
 * Scope: source-level native/Radix migration and destructive-control ownership.
 * Final visual/accessibility, live NAS testing and owner sign-off are separate gates.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve, relative, join } from 'node:path';

const root = resolve(process.cwd(), 'src');
const discover = dir => readdirSync(dir, { withFileTypes: true })
  .flatMap(entry => {
    const full = join(dir, entry.name);
    return entry.isDirectory() ? discover(full) : entry.isFile() && entry.name.endsWith('.tsx') ? [full] : [];
  });
const files = discover(root).map(full => ({
  path: relative(root, full).replaceAll('\\', '/'),
  source: readFileSync(full, 'utf8'),
}));
const byPath = new Map(files.map(file => [file.path, file.source]));
const sourceOf = path => {
  const source = byPath.get(path);
  assert.ok(source, 'Required live UI module not found: ' + path);
  return source;
};
const occurrences = (source, expression) => [...source.matchAll(expression)].length;

test('inventory covers every live TSX component/page, including newly added modules', () => {
  assert.ok(files.length >= 115, 'UI coverage shrank unexpectedly: ' + files.length);
  const pages = files.filter(file => file.path.startsWith('pages/'));
  assert.ok(pages.length >= 40, 'Live page inventory has unexpected gaps');
  for (const file of files) {
    assert.doesNotMatch(file.source, /from\s*['"](?:antd|@ant-design\/icons)['"]|require\(['"]antd['"]\)/,
      'Legacy AntD import in ' + file.path);
    assert.doesNotMatch(file.source, /\b(?:window\.)?confirm\s*\(/,
      'Blocking browser confirmation bypasses controlled UI in ' + file.path);
  }
});

test('shared native controls have explicit semantics and do not own API authority', () => {
  const button = sourceOf('components/ui/ConsoleButton.tsx');
  const checkbox = sourceOf('components/ui/ConsoleCheckbox.tsx');
  const select = sourceOf('components/ui/ConsoleSelect.tsx');
  const confirm = sourceOf('components/ui/ConsoleConfirmDialog.tsx');
  const sheet = sourceOf('components/ui/ConsoleSheet.tsx');
  for (const word of ['type={type}', "type = 'button'", 'disabled={disabled || loading}',
    'aria-busy={loading || undefined}']) assert.ok(button.includes(word), word);
  for (const word of ['type="checkbox"', 'checked={checked}', 'disabled={disabled}',
    'event.currentTarget.matches(\':disabled\')',
    "closest('[aria-disabled=\"true\"], [inert], [hidden]')",
    'onCheckedChange(event.currentTarget.checked)']) assert.ok(checkbox.includes(word), word);
  for (const word of ['<select', 'aria-label={label}', 'isSelectableConsoleOption(next, options)',
    'disabled={option.disabled}']) assert.ok(select.includes(word), word);
  for (const word of ['<Dialog.Root', '<Dialog.Portal>', '<Dialog.Title>',
    'onPointerDownOutside={event => event.preventDefault()}',
    'onClick={() => { if (!busy && !disabled) onConfirm(); }}',
    '!target.matches(\':disabled\')']) assert.ok(confirm.includes(word), word);
  for (const word of ['<Dialog.Root', '<Dialog.Portal>', '<Dialog.Title>',
    '<Dialog.Description', 'onCloseAutoFocus={event => {',
    '!target.matches(\':disabled\')']) assert.ok(sheet.includes(word), word);
  assert.doesNotMatch(button + checkbox + select + confirm + sheet,
    /\bfetch\s*\(|\buseMutation\s*\(|\b(?:deleteTask|deleteScan|purgePlan|executePlan)\s*\(/);
});

test('all shared control consumers remain accounted for across the full UI', () => {
  const count = name => files.reduce((sum, file) =>
    sum + occurrences(file.source, new RegExp('<' + name + '\\b', 'g')), 0);
  const minimums = {
    ConsoleButton: 150,
    ConsoleCheckbox: 8,
    ConsoleSelect: 4,
    ConsoleConfirmDialog: 21,
    ConsoleSheet: 6,
  };
  for (const [name, minimum] of Object.entries(minimums)) {
    assert.ok(count(name) >= minimum, name + ' usages fell below audited baseline');
  }
  const checkboxConsumers = files.filter(file => /<ConsoleCheckbox\b/.test(file.source)).map(file => file.path);
  for (const path of [
    'pages/Media/index.tsx', 'pages/Quarantine/index.tsx',
    'components/plans/PlanHistoryCleanupModal.tsx',
    'components/tasks/TaskHistoryCleanupModal.tsx',
    'components/scans/ScanCreateModal.tsx',
  ]) assert.ok(checkboxConsumers.includes(path), 'Missing shared checkbox consumer ' + path);
  for (const path of ['pages/Tasks/index.tsx', 'pages/Quarantine/index.tsx',
    'components/tasks/TaskLogTable.tsx']) {
    assert.match(sourceOf(path), /<ConsoleSelect\b/, 'Missing shared native select in ' + path);
  }
});

test('every native JSX form owns explicit submit handling; every Radix root renders content', () => {
  const forms = [];
  const dialogs = [];
  for (const file of files) {
    const formOpenings = [...file.source.matchAll(/<form\b[^>]*>/g)];
    if (formOpenings.length) {
      forms.push(file.path);
      for (const tag of formOpenings) {
        assert.ok(tag[0].includes('onSubmit='), file.path + ': native form missing submit handler');
      }
    }
    if (/<Dialog\.Root\b/.test(file.source)) {
      dialogs.push(file.path);
      assert.match(file.source, /<Dialog\.Portal\b/, 'Radix portal missing: ' + file.path);
      assert.match(file.source, /<Dialog\.Content\b/, 'Radix content missing: ' + file.path);
    }
  }
  assert.ok(forms.length >= 12, 'Form ownership coverage unexpectedly shrank');
  assert.ok(dialogs.length >= 20, 'Radix modal ownership coverage unexpectedly shrank');
  assert.ok(forms.includes('components/ChangePasswordModal.tsx'));
  assert.ok(forms.includes('pages/Scheduler/ScheduleEditorModal.tsx'));
  assert.ok(forms.includes('pages/Workflows/WorkflowBuilder.tsx'));
  console.log('[SHARED PRIMITIVE AUDIT]', JSON.stringify({
    tsxFiles: files.length,
    formOwners: forms.length,
    radixOwners: dialogs.length,
    sharedCheckboxInstances: files.reduce((n, file) =>
      n + occurrences(file.source, /<ConsoleCheckbox\b/g), 0),
    sharedConfirmInstances: files.reduce((n, file) =>
      n + occurrences(file.source, /<ConsoleConfirmDialog\b/g), 0),
    sharedSelectInstances: files.reduce((n, file) =>
      n + occurrences(file.source, /<ConsoleSelect\b/g), 0),
    sharedSheetInstances: files.reduce((n, file) =>
      n + occurrences(file.source, /<ConsoleSheet\b/g), 0),
    formPaths: forms,
    radixPaths: dialogs,
  }));
});

test('destructive actions retain caller-owned RBAC, safe-mode and async single-flight gates', () => {
  const taskDelete = sourceOf('components/tasks/TaskDeleteButton.tsx');
  const scanDelete = sourceOf('components/scans/ScanDeleteButton.tsx');
  const media = sourceOf('pages/Media/index.tsx');
  const quarantine = sourceOf('pages/Quarantine/index.tsx');
  const settings = sourceOf('pages/Settings/index.tsx');
  const verification = sourceOf('pages/DownloadVerification/index.tsx');
  for (const [source, token] of [
    [taskDelete, 'getTaskDeleteAvailability(task)'],
    [taskDelete, 'deleteInFlight.current'],
    [scanDelete, 'getScanDeleteAvailability(scan)'],
    [scanDelete, 'deleteInFlight.current'],
    [media, "record.integrity_status === 'corrupt'"],
    [media, 'previewCorruptDelete'],
    [quarantine, 'selectedEntryIds.length === 0 || !isAdmin || isSafeMode || !allowDelete'],
    [settings, 'confirmBusy'],
    [verification, '<ConsoleConfirmDialog'],
  ]) assert.ok(source.includes(token), 'Missing destructive safety gate: ' + token);
  const workflow = readFileSync(resolve(process.cwd(), '../.github/workflows/ui-v044-validation.yml'), 'utf8');
  for (const script of [
    'node scripts/browser-overlay-smoke.mjs',
    'node scripts/browser-task-overlays.mjs',
    'node scripts/browser-quarantine-plan-overlays.mjs',
    'node scripts/browser-quarantine-bulk-overlays.mjs',
    'node scripts/browser-workflow-preview-overlays.mjs',
    'node scripts/browser-organizer-dedupe-overlays.mjs',
    'node scripts/browser-workspace-cascade.mjs',
  ]) assert.ok(workflow.includes(script), 'Read-only browser evidence not registered: ' + script);
});
