import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const view = read('src/pages/ArchiveRecovery/index.tsx');
const css = read('src/styles/console-v2-archive-recovery.css');

describe('Archive Recovery follows Pure White visual and safety contracts', () => {
  test('existing router and file-tool navigation remain first-class', () => {
    const nav = read('src/components/layout/navItems.ts');
    const routes = read('src/router/index.tsx');
    assert.match(nav, /path:\s*'\/archive-recovery',\s*label:\s*'压缩包恢复'/);
    assert.ok(routes.includes('ArchiveRecovery'));
    assert.match(view, /nfc-archive-recovery-page/);
    assert.match(view, /nfc-archive-recovery-layout/);
  });

  test('unified panels preserve real directory picker, filtering and accessible selection', () => {
    assert.match(view, /<PageHeader eyebrow="File tools" title="压缩包检测与恢复"/);
    assert.match(view, /className="nfc-archive-recovery-select-panel"/);
    assert.match(view, /className="nfc-archive-recovery-run-panel"/);
    assert.match(view, /<DirectoryPicker value=\{folder\}/);
    assert.match(view, /role="group" aria-labelledby="recovery-folder-label"/);
    assert.match(view, /aria-pressed=\{selected === entry\.path\}/);
    assert.ok(view.includes('archiveRows.length === 0'));
    assert.ok(view.includes('filesystemApi.listDirectory(folder, false, page, 100, search)'));
  });

  test('cannot launch recovery without both server preflight permissions', () => {
    assert.ok(view.includes('mutationFn: archiveRecoveryApi.check'));
    assert.ok(view.includes('archiveRecoveryApi.start(selected, password, deep)'));
    assert.match(view, /disabled=\{!selected \|\| !check\.data\?\.can_write \|\| !check\.data\?\.dependency_available \|\| passwordChannelBlocked \|\| start\.isPending \|\| Boolean\(taskId\)\}/);
    assert.match(view, /setPassword\(''\);/);
    assert.match(view, /type="password" autoComplete="off"/);
  });

  test('password channel preflight fails closed for legacy/unavailable API without blocking password-free jobs', () => {
    const api = read('src/api/archiveRecovery.ts');
    const router = read('../app/archive_recovery/router.py');
    for (const source of [router, api]) assert.ok(source.includes('password_channel_available'));
    assert.ok(router.includes("'password_channel_available': tmpfs_available()"));
    assert.ok(router.includes("if payload.password and not tmpfs_available():"));
    assert.ok(view.includes('const passwordChannelBlocked = Boolean(password) &&'));
    assert.ok(view.includes('check.data?.password_channel_available !== true'));
    assert.ok(view.includes('|| passwordChannelBlocked || start.isPending'));
    assert.ok(view.includes('密码恢复暂不可启动'));
    assert.ok(view.includes('compose.komodo.archive-recovery-secrets.yaml'));
    assert.ok(view.includes('重新点击“检测”'));
    assert.ok(view.includes('密码通道（API 侧）'));
    assert.ok(view.includes("archiveRecoveryApi.start(selected, password, deep)"));
  });

  test('keeps all 7z AES/LZMA2 and read-only recovery limitations visible', () => {
    for (const detail of [
      '原压缩包只读', '结果存放同级唯一文件夹',
      '7z AES + LZMA2 重同步', 'CRC 完好的 7z 文件头',
      'RAR Solid 深度重同步', '32 MiB', '8 MiB',
      '10,000 个、4 GiB、30 分钟',
    ]) assert.ok(view.includes(detail), detail);
    assert.ok(view.includes('nfc-archive-recovery-help'));
    assert.ok(view.includes('nfc-archive-recovery-check-result'));
  });

  test('task log, cancellation, report evidence and status filtering are preserved', () => {
    assert.match(view, /queryFn: \(\) => tasksApi\.getTaskDetail\(taskId!\)/);
    assert.ok(view.includes("navigate('/tasks?task=' + taskId)"));
    assert.ok(view.includes('tasksApi.cancelTask(taskId!)'));
    assert.ok(view.includes('archiveRecoveryApi.report(taskId!)'));
    assert.ok(view.includes('anchor.download ='));
    assert.ok(view.includes("type: 'application/json'"));
    assert.ok(view.includes('report.data.aes_lzma2_deep'));
    assert.ok(view.includes('Object.entries(STATUS)'));
    assert.ok(view.includes('shown.slice(0, 500)'));
  });

  test('white card and charcoal selection rules are scoped to recovery UI', () => {
    assert.match(css, /\.nfc-v2-shell \.nfc-archive-recovery-layout\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1\.07fr\) minmax\(0,\s*\.93fr\);/);
    assert.match(css, /\.nfc-v2-shell \.nfc-archive-recovery-page \.nfc-data-panel\s*\{[^}]*border:\s*1px solid var\(--v2-line\) !important;/);
    assert.match(css, /\.nfc-v2-shell \.nfc-archive-recovery-file\.is-selected\s*\{[^}]*background:\s*var\(--v2-indigo-soft\) !important;/);
    assert.match(css, /\.nfc-v2-shell \.nfc-archive-recovery-page \.nfc-console-button-primary\s*\{[^}]*background:\s*#262625;/);
    assert.doesNotMatch(css, /#2878ef|#276fec|#83b5ff|linear-gradient/);
  });

  test('light, dark, focus, small screens and reduced motion are deliberately handled', () => {
    assert.match(css, /\[data-theme='dark'\] \.nfc-v2-shell \.nfc-archive-recovery-page \.nfc-console-button-primary\s*\{[^}]*background:\s*#e9e9e6;/);
    assert.ok(css.includes('nfc-archive-recovery-file:focus-visible'));
    assert.match(css, /@media \(max-width: 1023px\)/);
    assert.match(css, /@media \(max-width: 767px\)/);
    assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
    assert.match(css, /\.nfc-v2-shell \.nfc-archive-recovery-warning\s*\{[^}]*background:\s*#fff8eb;/);
    assert.match(css, /\[data-theme='dark'\] \.nfc-v2-shell \.nfc-archive-recovery-warning\s*\{[^}]*background:\s*#392d1c;/);
    assert.ok(css.includes('overflow-wrap: anywhere'));
  });

  test('scoped CSS is imported last, audited and executed in full frontend test suite', () => {
    const entry = read('src/main.tsx');
    assert.ok(entry.indexOf("import './styles/console-v2-archive-recovery.css';") >
      entry.indexOf("import './styles/console-v2-plan-detail.css';"));
    const audit = read('scripts/check-console-css-ownership.mjs');
    assert.ok(audit.includes("readdirSync(root)"));
    assert.ok(audit.includes("Incomplete CSS inventory coverage"));
    const runner = read('scripts/run-tests.mjs');
    assert.ok(runner.includes('tests/console_v2_archive_recovery_pure_white.test.ts'));
    assert.ok(runner.includes('dist-test/tests/console_v2_archive_recovery_pure_white.test.js'));
  });
});
