import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { getIndexRemoveAvailability, getIndexPathStatePresentation } from
  '../src/components/indexes/index_lifecycle';
import { indexesApi } from '../src/api/domain';
import { api } from '../src/api/client';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const index = () => read('src/pages/Indexes/index.tsx');

describe('Console v2 native Indexes ledger and safety gates', () => {
  test('Indexes page removes all Ant Design UI and uses semantic responsive table', () => {
    const s = index();
    for (const token of [
      '<ResponsiveDataView', '<table className="nfc-v2-indexes-table">',
      '<thead><tr>', '<tbody>{items.map(record => (',
      'nfc-index-mobile-card', '<ConsolePagination',
      '<ConsoleButton', '<ConsoleIcon', '<ConsoleEmpty',
      'useConsoleToast()', '<ConsoleConfirmDialog',
      '@radix-ui/react-dialog',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Table\b|<Pagination\b|<Popconfirm\b|<Modal\b|<Form\b|message\.(success|error)/);
  });

  test('server paginated indexes and native refresh preserve query identity', () => {
    const s = index();
    for (const token of [
      "queryKey: ['indexesList', page, pageSize]",
      'indexesApi.listIndexes(page, pageSize)',
      'isLoading', 'isFetching', 'isError', 'error',
      '<ConsolePagination page={page} pageSize={pageSize}',
      'total={data?.total || 0} onChange={changePage}',
      'setPageSize(nextSize)', 'setPage(1)', 'setPage(nextPage)',
      'void refetch()',
    ]) assert.ok(s.includes(token), token);
  });

  test('path state preserves missing metadata snapshot and blocked ALLOWED_ROOTS warning', () => {
    const s = index();
    for (const token of [
      'getIndexPathStatePresentation(state)',
      'getIndexPathStatePresentation(record.path_state)',
      'title={pres.tooltip}',
      "record.path_state === 'available'",
      'record.files.toLocaleString()', 'record.folders.toLocaleString()',
      'record.has_active_job && record.active_job_id',
    ]) assert.ok(s.includes(token), token);
    assert.match(getIndexPathStatePresentation('missing').tooltip || '', /不是实时文件系统结果/);
    assert.match(getIndexPathStatePresentation('blocked').tooltip || '', /ALLOWED_ROOTS/);
  });

  test('create flow continues using controlled native DirectoryPicker single absolute path', () => {
    const s = index();
    for (const token of [
      '<DirectoryPicker multiple={false} allowManualInput={true}',
      'value={rootDraft} disabled={createMutation.isPending}',
      'setRootDraft(', "const root = rootDraft.trim()",
      "if (!root.startsWith('/'))", '请选择或输入要索引的目录绝对路径',
      'ALLOWED_ROOTS', 'disabled={!rootDraft.trim()}',
      'await createMutation.mutateAsync(root)',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /Form\.useForm|form\.validateFields|form\.resetFields/);
  });

  test('create and reindex retain exact backend queue contracts and invalidation', async () => {
    const original = api.post;
    let url = ''; let sent: unknown;
    api.post = (async (p: string, data: unknown) => {
      url = p; sent = data;
      return { work_job_id: 456, status: 'queued' };
    }) as typeof api.post;
    try {
      const reply = await indexesApi.createIndex('/data/Folder');
      assert.equal(url, '/api/indexes');
      assert.deepEqual(sent, { root: '/data/Folder' });
      assert.equal(reply.work_job_id, 456);
    } finally { api.post = original; }
    const s = index();
    assert.ok(s.includes('await createMutation.mutateAsync(record.root)'));
    assert.ok(s.includes("queryKey: ['indexesList']"));
    assert.ok(s.includes("queryKey: ['dashboardSummary']"));
    assert.ok(s.includes('索引任务 #'));
  });

  test('reindex disabled for blocked and missing states, regardless of button location', () => {
    const s = index();
    for (const token of [
      "record.path_state === 'available'",
      "if (record.path_state !== 'available' || createInFlight.current || createMutation.isPending) return;",
      'disabled={!isAvailable || createMutation.isPending}',
      'renderActions(record)', 'renderActions(record, true)',
    ]) assert.ok(s.includes(token), token);
  });

  test('remove availability blocks active jobs and can_remove false', () => {
    assert.equal(getIndexRemoveAvailability(null).canRemove, false);
    assert.equal(getIndexRemoveAvailability({ has_active_job: true, can_remove: true }).canRemove, false);
    assert.equal(getIndexRemoveAvailability({ has_active_job: false, can_remove: false }).canRemove, false);
    assert.equal(getIndexRemoveAvailability({ has_active_job: false, can_remove: true }).canRemove, true);
    const s = index();
    assert.ok(s.includes('getIndexRemoveAvailability(record)'));
    assert.ok(s.includes('disabled={!remove.canRemove || deleteMutation.isPending || removePending}'));
  });

  test('remove is explicit and double gated before submitting metadata-only API', () => {
    const s = index();
    for (const token of [
      'const [removeTarget, setRemoveTarget] = useState<IndexRoot | null>(null)',
      'const removeInFlight = useRef(false)',
      'if (!getIndexRemoveAvailability(record).canRemove',
      'if (!getIndexRemoveAvailability(removeTarget).canRemove) return;',
      'removeInFlight.current = true;',
      'setRemovePending(true)',
      'await deleteMutation.mutateAsync(record.id)',
      'removeInFlight.current = false',
      '<ConsoleConfirmDialog open={removeTarget !== null}',
      'busy={removePending}',
      'confirmText="移除" danger',
    ]) assert.ok(s.includes(token), token);
  });

  test('remove dialog discloses exact metadata and historical safety boundaries', () => {
    const s = index();
    for (const token of [
      'IndexedPath', '不会删除 NAS 上的任何真实文件或目录',
      'Task、Scan、Plan 或 Audit 历史记录',
      'INDEX_REMOVE_DESCRIPTION',
      'setRemoveTarget(null)',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /删除 NAS 上所有|移除真实文件|彻底删除文件/);
  });

  test('remove keeps existing exact API endpoint and onFailure list invalidation', async () => {
    const original = api.delete;
    let url = '';
    api.delete = (async (p: string) => {
      url = p;
      return { deleted: true, deleted_indexed_paths: 44 };
    }) as typeof api.delete;
    try {
      const reply = await indexesApi.deleteIndex(23);
      assert.equal(url, '/api/indexes/23');
      assert.equal(reply.deleted_indexed_paths, 44);
    } finally { api.delete = original; }
    const s = index();
    assert.ok(s.includes("toast.error(getStructuredApiError(err).message || '移除索引失败')"));
    assert.ok(s.includes("void queryClient.invalidateQueries({ queryKey: ['indexesList'] })"));
  });

  test('native create Dialog cannot be dismissed during background request', () => {
    const s = index();
    for (const token of [
      '<Dialog.Root open={modalOpen}', '<Dialog.Portal>',
      '<Dialog.Overlay', '<Dialog.Content',
      '<Dialog.Title>', '<Dialog.Description',
      'onPointerDownOutside={event => event.preventDefault()}',
      'createMutation.isPending || createInFlight.current',
      'if (createInFlight.current || createMutation.isPending) return;',
      'type="submit" loading={createMutation.isPending}',
    ]) assert.ok(s.includes(token), token);
  });

  test('empty / loading / server error states are independent and actionable', () => {
    const s = index();
    for (const token of [
      'isError &&', 'isLoading &&', 'items.length === 0',
      '<ConsoleEmpty title="暂无索引根目录"',
      'role="alert"', 'role="status"',
      '获取索引根目录失败',
      'getStructuredApiError(error)',
      '正在读取索引根目录',
      '重新加载',
    ]) assert.ok(s.includes(token), token);
  });

  test('owned responsive CSS supplies mobile/dark/reduced-motion/focus styles', () => {
    const css = read('src/styles/console-v2-indexes.css');
    for (const token of [
      '.nfc-v2-indexes-page', '.nfc-v2-indexes-table',
      '.nfc-v2-indexes-mobile', '.nfc-v2-index-create-dialog',
      '.nfc-v2-index-form', '.nfc-v2-index-actions',
      "[data-theme='dark']", 'focus-visible',
      'max-width:767px', 'prefers-reduced-motion:reduce',
      'min-height:44px',
    ]) assert.ok(css.includes(token), token);
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-indexes.css';"));
  });

  test('desktop and mobile use shared action guards and controlled dialogs', () => {
    const s = index();
    assert.ok(s.includes('renderActions(record)'));
    assert.ok(s.includes('renderActions(record, true)'));
    assert.ok(s.includes('getIndexRemoveAvailability(record)'));
    assert.ok(s.includes('openRemove(record)'));
    assert.ok(s.includes('setRemoveTarget(record)'));
  });
});
