import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const scan = read('src/components/scans/ScanCreateModal.tsx');
const dedupe = read('src/components/dedupe/DedupeActionDialog.tsx');
const checkbox = read('src/components/ui/ConsoleCheckbox.tsx');
const ci = read('../.github/workflows/ui-v044-validation.yml');

describe('Pure White Stage 5E-M scan and dedupe modal submit guards', () => {
  test('scan creation guards rapid repeated submit synchronously and awaits settlement', () => {
    for (const token of [
      'const submitting = useRef(false);',
      'if (createMutation.isPending || submitting.current) return;',
      'const failure = validateScanCreateValues(values);',
      'const payload = toScanCreatePayload(values);',
      'submitting.current = true;',
      'await createMutation.mutateAsync(payload);',
      'submitting.current = false;',
      'onError: (err: Error) =>',
      "toast.error(message);",
    ]) assert.ok(scan.includes(token), token);
    assert.ok(scan.indexOf('const payload = toScanCreatePayload(values);')
      < scan.indexOf('submitting.current = true;'));
    assert.ok(scan.indexOf('submitting.current = true;')
      < scan.indexOf('await createMutation.mutateAsync(payload);'));
    assert.match(scan, /try \{[\s\S]*?await createMutation\.mutateAsync\(payload\);[\s\S]*?\} catch \{[\s\S]*?\} finally \{[\s\S]*?submitting\.current = false;/);
    assert.doesNotMatch(scan, /createMutation\.mutate\(/);
  });

  test('scan dismissal and edits fail closed while pending, including the render timing gap', () => {
    for (const token of [
      'if (createMutation.isPending || submitting.current) return;',
      'onOpenChange={next => { if (!next) close(); }}',
      'onEscapeKeyDown={event => { if (createMutation.isPending || submitting.current) event.preventDefault(); }}',
      'onPointerDownOutside={event => event.preventDefault()}',
      'disabled={createMutation.isPending} onClick={close}',
      'onClick={close}>取消',
      'if (createMutation.isPending || submitting.current) return;',
      '<DirectoryPicker multiple disabled={createMutation.isPending}',
    ]) assert.ok(scan.includes(token), token);
    assert.equal(scan.split('if (createMutation.isPending || submitting.current) return;').length - 1, 3,
      'close/submit/update each need the same synchronous guard');
  });

  test('scan form remains native and preserves payload fields and backend root authority', () => {
    for (const token of [
      '<form className="nfc-v2-scan-create-form" onSubmit={submit}>',
      '<ConsoleCheckbox checked={values.isolate}',
      "onCheckedChange={checked => update('isolate', checked)}",
      'type="text" required', '<textarea',
      "toScanCreatePayload(values)",
      'namePatternsText', 'excludePatternsText', 'minSize',
      'ALLOWED_ROOTS', 'multiple disabled={createMutation.isPending}',
      'scansApi.createScan(request)',
      "navigate('/scans/' + res.scan_job_id)",
    ]) assert.ok(scan.includes(token), token);
    assert.match(checkbox, /<input \{\.\.\.props\} ref=\{ref\} type="checkbox"/);
    assert.doesNotMatch(scan, /<input type="checkbox"|from ['"]antd['"]/);
  });

  test('advanced dedupe confirmation callbacks reject busy and absent notice', () => {
    for (const token of [
      'const cancelSafely = () => { if (!busy) onCancel(); };',
      'const confirmSafely = () => { if (!busy && kind !== null) onConfirm(); };',
      'onOpenChange={next => { if (!next) cancelSafely(); }}',
      'disabled={busy} onClick={cancelSafely}',
      'disabled={!kind || busy} loading={busy} onClick={confirmSafely}',
      'onEscapeKeyDown={event => { if (busy) event.preventDefault(); }}',
      'onPointerDownOutside={event => event.preventDefault()}',
    ]) assert.ok(dedupe.includes(token), token);
    assert.equal((dedupe.match(/disabled=\{busy\} onClick=\{cancelSafely\}/g) || []).length, 2);
    assert.doesNotMatch(dedupe, /onClick=\{onCancel\}|onClick=\{onConfirm\}/);
  });

  test('dedupe remains preview-to-Draft only and keeps warnings and state owner', () => {
    for (const token of [
      "kind !== 'generate' && errorMessage",
      'Hardlink 后两个路径共享同一个 inode',
      'Reflink 使用独立 inode',
      '生成后仅创建 Draft 状态计划',
      'Freeze -&gt; Validate -&gt; Execute',
      'PREVIEW_CHANGED', 'DEDUPE_SCAN_NOT_FOUND', 'DEDUPE_SCAN_NOT_COMPLETED',
      'DEDUPE_EMPTY_PLAN',
    ]) assert.ok(dedupe.includes(token), token);
    assert.doesNotMatch(dedupe, /fetch\(|useMutation|scansApi|quarantineApi|executePlan\(/);
  });

  test('all prior read-only browser suites continue on exact PR HEAD', () => {
    for (const token of [
      'Checkout exact candidate HEAD', 'Verify candidate identity',
      'node scripts/browser-task-overlays.mjs',
      'node scripts/browser-quarantine-plan-overlays.mjs',
      'node scripts/browser-workflow-preview.mjs',
      'node scripts/browser-organizer-dedupe.mjs',
      'node scripts/browser-workspace-cascade.mjs',
      'node scripts/browser-indexes-ledger-states.mjs',
      'node scripts/browser-media-ledger-states.mjs',
      'Upload visual evidence',
    ]) assert.ok(ci.includes(token), token);
    const browser = read('scripts/browser-workspace-cascade.mjs');
    for (const token of ["request.method() !== 'GET'", 'assert.deepEqual(writes, []',
      'assert.deepEqual(outbound, []', '32/32 cases, 352 screenshots']) {
      assert.ok(browser.includes(token), token);
    }
  });
});
