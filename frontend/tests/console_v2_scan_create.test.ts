import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  splitScanLines, validateScanCreateValues, toScanCreatePayload,
  type ScanCreateValues,
} from '../src/components/scans/scan_create';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

const base: ScanCreateValues = {
  name: ' NAS duplicate scan ', roots: ['/data/Movies', ' /data/Photos '],
  isolate: true, minSize: ' 100M ', namePatternsText: '*.mp4\n\n*.mkv ',
  excludePatternsText: '*.tmp\n*.part',
};

describe('Console v2 Scan Creation form', () => {
  test('rejects missing names and empty root list without bypassing backend path validation', () => {
    assert.equal(validateScanCreateValues({ ...base, name: '   ' }), '请输入任务名称');
    assert.equal(validateScanCreateValues({ ...base, roots: [] }), '请至少选择或输入一个待扫描路径');
    assert.equal(validateScanCreateValues({ ...base, roots: ['  '] }), '请至少选择或输入一个待扫描路径');
    assert.equal(validateScanCreateValues(base), null);
  });

  test('preserves every scan API payload field and trimmed pattern semantics', () => {
    assert.deepEqual(toScanCreatePayload(base), {
      name: 'NAS duplicate scan', roots: ['/data/Movies', '/data/Photos'],
      isolate: true, min_size: '100M',
      name_patterns: ['*.mp4', '*.mkv'], exclude_patterns: ['*.tmp', '*.part'],
    });
    assert.deepEqual(toScanCreatePayload({
      ...base, isolate: false, minSize: '', namePatternsText: '',
      excludePatternsText: '\n',
    }), {
      name: 'NAS duplicate scan', roots: ['/data/Movies', '/data/Photos'],
      isolate: false, min_size: null, name_patterns: null, exclude_patterns: null,
    });
    assert.deepEqual(splitScanLines(' a \n\n b\r\n'), ['a', 'b']);
  });

  test('form uses native input/textarea/checkbox and preserves path picker semantics', () => {
    const code = read('src/components/scans/ScanCreateModal.tsx');
    for (const token of [
      '<form className="nfc-v2-scan-create-form" onSubmit={submit}>',
      'type="text" required', 'type="checkbox"', '<textarea',
      '<DirectoryPicker multiple disabled={createMutation.isPending}',
      "validateScanCreateValues(values)", 'toScanCreatePayload(values)',
      'createMutation.isPending', 'createMutation.mutate(',
      'keyboard={!createMutation.isPending}',
      'maskClosable={!createMutation.isPending}',
      'closable={!createMutation.isPending}',
      'ALLOWED_ROOTS',
      "queryClient.invalidateQueries({ queryKey: ['scansList'] })",
      "queryClient.invalidateQueries({ queryKey: ['workJobsList'] })",
      "navigate('/scans/' + res.scan_job_id)",
    ]) assert.ok(code.includes(token), token);
    assert.doesNotMatch(code, /<Form\b|<Form.Item\b|<Input\b|<Switch\b/);
  });

  test('scan list no longer imports Ant controls; modal only remains until DirectoryPicker overlay migration', () => {
    const page = read('src/pages/Scans/index.tsx');
    const form = read('src/components/scans/ScanCreateModal.tsx');
    assert.doesNotMatch(page, /from ['"]antd['"]|@ant-design\/icons|Form\.useForm/);
    assert.match(page, /<ScanCreateModal open=\{isModalOpen\}/);
    assert.match(form, /import \{ Modal \} from 'antd'/);
    assert.match(form, /from '..\/DirectoryPicker'/);
    assert.match(form, /onError: \(err: Error\) =>/);
    assert.match(form, /toast\.error\(message\)/);
  });

  test('form CSS remains portal aware, responsive, and has dark-mode tokens', () => {
    const css = read('src/styles/console-v2-scan-create.css');
    const main = read('src/main.tsx');
    for (const token of [
      '.nfc-v2-scan-create-modal', '.nfc-v2-scan-create-field',
      '.nfc-v2-scan-create-patterns', '.nfc-v2-scan-create-error',
      ".nfc-v2-scan-create-modal .nfc-console-button",
      "[data-theme='dark']", '@media (max-width: 767px)',
      'prefers-reduced-motion: reduce',
    ]) assert.ok(css.includes(token), token);
    assert.ok(main.indexOf("import './styles/console-v2-scan-create.css';") >
      main.indexOf("import './styles/console-v2-scan-detail.css';"));
  });
});
