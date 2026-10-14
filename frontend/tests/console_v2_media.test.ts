import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { api } from '../src/api/client';
import { mediaApi } from '../src/api/domain';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const source = () => read('src/pages/Media/index.tsx');

describe('Console v2 native Media integrity and direct-unlink safety', () => {
  test('Media page no longer imports Ant Design widgets or icon package', () => {
    const s = source();
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Table\b|<Select\b|<Modal\b|<Pagination\b|<Tag\b|<Tooltip\b|message\./);
    for (const token of ['<ResponsiveDataView', '<ConsoleButton', '<ConsoleIcon',
      '<ConsoleEmpty', '<ConsolePagination', '<ConsoleConfirmDialog',
      '@radix-ui/react-dialog', 'useConsoleToast()', '<table className="nfc-v2-media-table"']) {
      assert.ok(s.includes(token), token);
    }
  });
  test('media labels strictly differentiate healthy, corrupt, unknown and SHA256 states', () => {
    const s = source();
    for (const token of [
      "record.integrity_status === 'healthy'",
      "record.integrity_status === 'corrupt'",
      "status === 'corrupt' ? '损坏' : '未知'",
      "unverified: '未建立基线'", "baseline: '基线已建立'",
      "verified: 'SHA256 通过'", "changed: '内容变化'",
      "unknown: '无法校验'", 'label="SHA256 变化"',
    ]) assert.ok(s.includes(token), token);
  });
  test('native desktop and mobile share corrupt-only selection with admin permission', () => {
    const s = source();
    for (const token of [
      "Boolean(isAdmin && record.integrity_status === 'corrupt' && record.can_direct_delete)",
      'rows.filter(canSelect).map(record => record.id)',
      'checked={canSelect(record) && selectedIds.includes(record.id)}',
      'disabled={!canSelect(record) || deletePreviewBusy || deleteBusy}',
      'onCheckedChange={checked => toggleRow(record, checked)}',
      'pageEligibleIds.every(id => selectedIds.includes(id))',
      'togglePage(event.target.checked)', 'rowCheckbox(record)',
      'onClick={() => { void beginDeletePreview([record.id]); }}',
      'disabled={!isAdmin || selectedIds.length === 0 || deleteBusy || deletePreviewBusy}',
    ]) assert.ok(s.includes(token), token);
  });
  test('server list/query filtering and pagination are preserved and reset selection', () => {
    const s = source();
    for (const token of [
      "queryKey: ['mediaList', page, pageSize, rootKey, mediaKind, integrityStatus, verificationStatus, searchApplied]",
      'rootKey, mediaKind, integrityStatus, verificationStatus',
      'search: searchApplied || undefined',
      'setSearchApplied(search.trim())', 'setPage(1); resetSelection()',
      'setPageSize(nextSize)', 'resetSelection()',
      '<ConsolePagination page={page} pageSize={pageSize}',
      'total={mediaQuery.data?.total || 0} pageSizes={[20, 50, 100, 200]}',
    ]) assert.ok(s.includes(token), token);
  });
  test('both root-select dialogs stay read-only/queue-only and filter unavailable roots', () => {
    const s = source();
    for (const token of [
      "root.path_state !== 'available'",
      "kind: 'analyze' | 'verify'",
      'disabled={option.disabled}',
      'roots.some(root =>', '!option.disabled',
      "mediaApi.analyze(roots)",
      "mediaApi.verifyIntegrity(roots)",
      'queueInFlight.current = true',
      'await mutation.mutateAsync([...ids])',
      'onPointerDownOutside={event => event.preventDefault()}',
      '首次运行在索引身份匹配时建立 SHA256 基线',
    ]) assert.ok(s.includes(token), token);
  });
  test('direct file deletion retains explicit Preview before a separate confirmation', () => {
    const s = source();
    for (const token of [
      'const beginDeletePreview = async (ids: number[]) => {',
      'await mediaApi.previewCorruptDelete(uniqueIds)',
      'setDeleteSnapshot({ ids: uniqueIds, preview, selectionVersion: version })',
      '<ConsoleConfirmDialog open={deleteSnapshot !== null}',
      'title={', '预计释放',
      '该操作不会移动到文件隔离区',
      '原文件将直接 unlink，应用内无法恢复',
    ]) assert.ok(s.includes(token), token);
  });
  test('Preview snapshot rejects mismatch, missing digest, blocked or ineligible members', () => {
    const s = source();
    for (const token of [
      'const uniqueIds = [...new Set(ids)]',
      '!equalIds(preview.selected_media_asset_ids, uniqueIds)',
      '!preview.preview_digest',
      'preview.items.length !== uniqueIds.length',
      '!equalIds(preview.items.map(item => item.media_asset_id), uniqueIds)',
      'preview.blocked_count > 0',
      'preview.eligible_count !== uniqueIds.length',
      'preview.items.some(item => !item.eligible)',
      'selectionVersion.current !== version',
    ]) assert.ok(s.includes(token), token);
  });
  test('Preview requests cannot be started in parallel and fail closed on errors', () => {
    const s = source();
    for (const token of [
      'const previewInFlight = useRef(false)',
      'previewInFlight.current = true', 'previewInFlight.current = false',
      'setDeletePreviewBusy(true)', 'setDeletePreviewBusy(false)',
      'selectionVersion.current += 1',
      'setDeleteSnapshot(null)',
      '损坏媒体永久删除 Preview 失败',
    ]) assert.ok(s.includes(token), token);
  });
  test('confirmed destructive operation keeps original Plan → Freeze → Validate → Execute sequence', () => {
    const s = source();
    const a=s.indexOf('mediaApi.createCorruptDeletePlan(snapshot.ids, snapshot.preview.preview_digest)');
    const b=s.indexOf('plansApi.freezePlan(created.id)');
    const c=s.indexOf('plansApi.validatePlan(created.id)');
    const d=s.indexOf("validated.status !== 'ready'");
    const e=s.indexOf('plansApi.executePlan(created.id)');
    assert.ok(a>0 && b>a && c>b && d>c && e>d, 'sequence');
    assert.ok(s.includes('queryKey: [\'mediaSummary\']'));
    assert.ok(s.includes("queryKey: ['mediaList']"));
  });
  test('destructive mutation snapshots IDs/digest and guards admin, duplicate and stale submit', () => {
    const s=source();
    for(const token of [
      'if (!isAdmin || !snapshot || deleteInFlight.current || deleteBusy',
      'selectionVersion.current !== snapshot.selectionVersion',
      'snapshot.preview.blocked_count !== 0',
      'snapshot.preview.eligible_count !== snapshot.ids.length',
      'deleteInFlight.current = true; setDeleteBusy(true)',
      'await deleteMutation.mutateAsync(snapshot)',
      'deleteInFlight.current = false; setDeleteBusy(false)',
      'setDeleteSnapshot(null)',
      'if (!next && !deleteInFlight.current && !deleteBusy) setDeleteSnapshot(null)',
    ]) assert.ok(s.includes(token), token);
  });
  test('server API freezes selected corrupt evidence digest and special confirmation token', async () => {
    const original = api.post;
    let url = '';let payload: unknown;
    api.post = (async (p: string, body: unknown) => {
      url=p; payload=body;
      return {id: 123, status:'draft', preview_digest:'signed'};
    }) as typeof api.post;
    try {
      await mediaApi.createCorruptDeletePlan([17,20], 'digest-token');
      assert.equal(url, '/api/media/corrupt-delete/plan');
      assert.deepEqual(payload, {
        media_asset_ids: [17,20],
        expected_preview_digest: 'digest-token',
        confirmation:'DELETE_CORRUPT_FILES',
      });
    } finally { api.post=original; }
  });
  test('Preview API uses dedicated corrupt-delete endpoint instead of direct unlink', async () => {
    const original=api.post;
    let url=''; let payload:unknown;
    api.post=(async(p:string, body:unknown)=>{
      url=p;payload=body;
      return {selected_media_asset_ids:[17],eligible_count:1,blocked_count:0,items:[],preview_digest:'x'};
    }) as typeof api.post;
    try {
      await mediaApi.previewCorruptDelete([17]);
      assert.equal(url,'/api/media/corrupt-delete/preview');
      assert.deepEqual(payload,{media_asset_ids:[17]});
    } finally {api.post=original;}
  });
  test('the queue status reports Worker enqueue, not synchronous physical file erasure',()=>{
    const s=source();
    assert.ok(s.includes('已校验并加入 Worker 队列'));
    assert.ok(s.includes('workJobId: queued.work_job_id'));
    assert.ok(s.includes('任何变化都会 fail-closed'));
    assert.doesNotMatch(s, /已物理擦除|数据不可恢复地完全销毁|磁盘字节已擦除/);
  });
  test('dark mobile focus reduced-motion styling and portal root picker are present',()=>{
    const css=read('src/styles/console-v2-media.css');
    for(const token of [
      '.nfc-v2-media-page','.nfc-v2-media-table',
      '.nfc-v2-media-mobile','.nfc-v2-media-status',
      '.nfc-v2-media-queue-dialog','.nfc-v2-media-root-options',
      "data-theme='dark'",'max-width:767px',
      'prefers-reduced-motion:reduce','focus-visible','min-height:44px',
    ]) assert.ok(css.includes(token),token);
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-media.css';"));
  });
  test('all 3 dialogs remain controlled, with busy escape/outside-click protection',()=>{
    const s=source();
    for(const token of [
      '<Dialog.Root open={open}', '<Dialog.Portal',
      '<Dialog.Title', '<Dialog.Description',
      'onEscapeKeyDown={event => { if (busy) event.preventDefault(); }}',
      'onPointerDownOutside={event => event.preventDefault()}',
      'busy={deleteBusy}', 'onOpenChange={closeDelete}',
      'onConfirm={() => { void handleConfirmedDelete(); }}',
    ]) assert.ok(s.includes(token),token);
  });
});
