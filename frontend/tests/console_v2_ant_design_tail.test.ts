import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { computeRebuildReadiness } from '../src/utils/rebuildReadiness';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const audit = () => read('src/pages/Audit/index.tsx');
const rebuild = () => read('src/components/plans/StaleRebuildDrawer.tsx');

describe('Console v2 residual Ant Design cleanup — audited native safety', () => {
  test('four migrated runtime components no longer use AntD dependencies', () => {
    for (const path of [
      'src/pages/Audit/index.tsx',
      'src/components/tasks/TaskStatusTag.tsx',
      'src/components/tasks/WorkerStatusCard.tsx',
      'src/components/plans/StaleRebuildDrawer.tsx',
      'src/contexts/AuthContext.tsx',
      'src/pages/Organizer/index.tsx',
      'src/hooks/useResponsive.ts',
    ]) {
      const source = read(path);
      assert.doesNotMatch(source, /from ['"]antd['"]|from ['"]@ant-design\/icons['"]/);
      assert.doesNotMatch(source, /<(?:Table|Modal|Popconfirm|Drawer|Alert|Tag|Spin|Skeleton)\b/);
    }
  });

  test('global import audit script enumerates runtime source and denies new imports', () => {
    const source = read('scripts/check-ant-design-tail.mjs');
    for (const token of [
      "resolve(frontend, 'src')", 'const allowed = new Set([',
      "'src/components/workflows/CompletedScanPicker.tsx'",
      "'src/components/workflows/OrganizerProfileFields.tsx'",
      "'src/contexts/ThemeContext.tsx'",
      "'src/pages/Login/index.tsx'",
      "'src/pages/Plans/OperationJournalDrawer.tsx'",
      "'src/pages/Plans/PlanDetail.tsx'",
      "'src/pages/Workflows/UtilityWorkflowPreviewPanel.tsx'",
      "'src/pages/Workflows/WorkflowPreviewPanelLegacy.tsx'",
      'modulePattern', 'readdirSync(dir)', 'statSync(full).isDirectory()',
      'matches.sort(', 'const unexpected = matches.filter(item => !item.approved)',
      'if (missing.length || unexpected.length) process.exitCode = 1',
    ]) assert.ok(source.includes(token), token);
    assert.ok(read('scripts/run-tests.mjs').includes('node scripts/check-ant-design-tail.mjs'));
  });

  test('Audit displays retained events and retention policy using native controls', () => {
    const source = audit();
    for (const token of [
      "queryKey: ['auditEvents', page, pageSize, searchText]",
      'auditApi.listEvents(page, pageSize, searchText || undefined)',
      "queryKey: ['dataLifecyclePolicy']",
      'formatAuditRetention(lifecyclePolicy.audit_retention_days)',
      'isSuccessResult(event.result)', '<StatusBadge',
      '<CodePath value={event.path}', '<ResponsiveDataView',
      '<table className="nfc-v2-audit-table"',
      'nfc-audit-mobile-card', '<ConsolePagination',
      'pageSizes={[10, 20, 50, 100]}', 'setPage(1)',
    ]) assert.ok(source.includes(token), token);
  });

  test('Audit never mutates records and preserves raw JSON detail in accessible Radix dialog', () => {
    const source = audit();
    for (const token of [
      'useState<AuditEvent | null>(null)',
      '<Dialog.Root open={selectedEvent !== null}',
      '<Dialog.Title>审计事件详情',
      '<Dialog.Description>原始操作与元数据记录（只读）。</Dialog.Description>',
      'selectedEvent.details, null, 2',
      'setSelectedEvent(event)', 'setSelectedEvent(null)',
      'onPointerDownOutside={event => event.preventDefault()}',
      '详细元数据 JSON',
    ]) assert.ok(source.includes(token), token);
    assert.doesNotMatch(source, /useMutation|auditApi\.(delete|clear|update)/);
  });

  test('Audit clean empty/loading/error states preserve explicit retry', () => {
    const source = audit();
    for (const token of [
      'isError &&', 'isLoading &&', 'items.length === 0',
      '<ConsoleEmpty title="暂无审计事件"',
      '审计事件读取失败', 'getStructuredApiError(error).message',
      'role="alert"', 'role="status"', 'void refetch()',
    ]) assert.ok(source.includes(token), token);
  });

  test('TaskStatusTag still uses all canonical labels and native StatusBadge', () => {
    const s = read('src/components/tasks/TaskStatusTag.tsx');
    assert.ok(s.includes('TASK_STATUS_CONFIG[status as TaskStatus]'));
    assert.ok(s.includes('<StatusBadge status={status ||'));
    assert.ok(s.includes("config?.label || status || '-'"));
    const mapping = read('src/components/tasks/task_utils.ts');
    for (const status of ['queued', 'running', 'paused', 'cancel_requested', 'cancelled', 'failed', 'completed']) {
      assert.ok(mapping.includes(status + ':'), status);
    }
  });

  test('Worker status polling/retry/offline fallback and heartbeat facts unchanged', () => {
    const s = read('src/components/tasks/WorkerStatusCard.tsx');
    for(const token of [
      "queryKey: ['workerStatus']", 'tasksApi.getWorkerStatus()',
      'refetchInterval: 5000', 'retry: 1',
      "data?.status || 'offline'",
      'WORKER_STATUS_BADGE_MAP[workerStatus] || WORKER_STATUS_BADGE_MAP.offline',
      'formatDateTime(data?.started_at)',
      'formatDateTime(data?.heartbeat_at)',
      'formatHeartbeatAge(data?.heartbeat_age_seconds)',
      'role="alert"', 'role="status"', 'aria-label="调度 Worker 状态"',
    ]) assert.ok(s.includes(token), token);
  });

  test('Stale Rebuild retains plan-specific paginated preview and authoritative lineage', () => {
    const s = rebuild();
    for (const token of [
      "queryKey: ['rebuildPlanPreview', planId, page, pageSize]",
      'workflowApi.rebuildPlanPreview(planId, { page, page_size: pageSize })',
      "enabled: open && !!planId",
      'preview.workflow_id', 'preview.workflow_revision',
      'preview.planned_operations_count', 'preview.matched_count',
      'preview.compile_digest', 'preview.definition_sha256',
      '<ConsolePagination page={page} pageSize={pageSize}',
      'pageSizes={[20, 50, 100]}',
      'nfc-rebuild-mobile-card', '<CodePath value={item.source_path}',
    ]) assert.ok(s.includes(token), token);
  });

  test('Rebuild digest freshness is rejected while loading, invalidated or mismatched', () => {
    assert.deepEqual(computeRebuildReadiness({
      hasPreview: false, previewInvalidated: false, acceptedDigest: 'x',
      isLoading: false, isFetching: false,
    }), { canSubmit: false, submitDigest: null });
    for(const field of ['previewInvalidated', 'isLoading', 'isFetching'] as const) {
      const v = { hasPreview: true, previewInvalidated: false, acceptedDigest: 'evidence',
        isLoading: false, isFetching: false };
      v[field] = true;
      assert.equal(computeRebuildReadiness(v).canSubmit, false, field);
    }
    const s = rebuild();
    for (const token of [
      'setPreviewInvalidated(true)', 'setAcceptedDigest(null)',
      'computeRebuildReadiness({', 'readiness.canSubmit',
      'readiness.submitDigest', 'await refetch()',
      'PREVIEW_CHANGED', 'workflowApi.rebuildPlan(planId, {',
      'expected_compile_digest: digest', 'customPlanName.trim() || undefined',
    ]) assert.ok(s.includes(token), token);
  });

  test('Rebuild only creates Draft, prevents double submit and close while mutation is active', () => {
    const s = rebuild();
    for (const token of [
      'const submitInFlight = useRef(false)',
      'const [submitBusy, setSubmitBusy] = useState(false)',
      'if (!open || submitInFlight.current || submitBusy || rebuildMutation.isPending) return',
      'submitInFlight.current = true', 'setSubmitBusy(true)',
      'await rebuildMutation.mutateAsync(readiness.submitDigest)',
      'submitInFlight.current = false', 'setSubmitBusy(false)',
      '!submitInFlight.current && !submitBusy && !rebuildMutation.isPending',
      '只生成新的 Draft Plan',
      'Freeze → Validate → Execute',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /plansApi\.executePlan|freezePlan|validatePlan\(/);
  });

  test('Rebuild explicit errors remain differentiated and compile snapshot is never silently replaced', () => {
    const s = rebuild();
    for (const token of [
      "structured.code === 'PREVIEW_CHANGED'",
      "structured.code === 'WORKFLOW_ARCHIVED'",
      "structured.code === 'DEDUPE_RESCAN_REQUIRED'",
      'formatDedupeErrorMessage(err)',
      'setPreviewInvalidated(true)',
      'setAcceptedDigest(null)',
      '重建操作受阻',
      '关联工作流已归档，无法重新生成计划',
    ]) assert.ok(s.includes(token), token);
  });


  test('auth/organizer preserve server mutations while routing notifications through native toast provider', () => {
    const app = read('src/App.tsx');
    assert.match(app, /<ConsoleToastProvider>[\s\S]*<AuthProvider>/);
    const auth = read('src/contexts/AuthContext.tsx');
    for (const token of [
      'useConsoleToast()', 'await authApi.login(payload)',
      'await authApi.logout()', "setUser(null)", "navigate('/login', { replace: true })",
      'toast.success(', 'toast.info(',
    ]) assert.ok(auth.includes(token), token);
    const organizer = read('src/pages/Organizer/index.tsx');
    for (const token of [
      'useConsoleToast()', 'organizerProfilesApi.updateProfile',
      'organizerProfilesApi.createProfile', 'toast.success(', 'toast.error(',
      "editingProfile?.is_builtin", "queryKey: ['organizer-profiles']",
    ]) assert.ok(organizer.includes(token), token);
  });

  test('native responsive hook preserves 768px md / 1200px xl thresholds and resize cleanup', () => {
    const s=read('src/hooks/useResponsive.ts');
    for(const token of [
      'useSyncExternalStore(subscribe, readWidth, () => 0)',
      'window.addEventListener(', 'window.removeEventListener(',
      'width < 768', 'width >= 1200',
      'const isTablet = !isMobile && !isDesktop',
      "typeof window !== 'undefined'",
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /from ['"]antd['"]|Grid\.useBreakpoint|useBreakpoint\(/);
  });

  test('native owned audit and rebuild styles expose dark/mobile/focus/reduced motion', () => {
    const styles = ['src/styles/console-v2-audit-and-worker.css',
      'src/styles/console-v2-stale-rebuild.css'];
    for (const path of styles) {
      const css = read(path);
      for (const token of ["data-theme='dark'", 'focus-visible',
        'max-width:767px', 'prefers-reduced-motion:reduce']) {
        assert.ok(css.includes(token), path + ':' + token);
      }
    }
    const main = read('src/main.tsx');
    assert.ok(main.includes("import './styles/console-v2-audit-and-worker.css'"));
    assert.ok(main.includes("import './styles/console-v2-stale-rebuild.css'"));
  });
});
