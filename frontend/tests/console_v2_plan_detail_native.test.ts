import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  canPlanLifecycleAction, planConfirmationSnapshot, samePlanConfirmation,
} from '../src/utils/planDetailActions';
import type { Plan } from '../src/types';

const read = (p: string) => readFileSync(resolve(process.cwd(),p),'utf8');
const context = (status: Plan['status'], overrides: Record<string, unknown> = {}) => ({
  plan:{id:23,status,active_work_job_id:null},
  allowMutation:true,journalTotal:12,journalReady:true,pending:false,...overrides,
});
describe('Console v2 Plan Detail lifecycle safety and native UX', () => {
  test('Freeze only accepts draft, Validate only accepted frozen/ready/partial/stale', () => {
    for(const status of ['draft','frozen','validating','ready','executing',
      'completed','partial','failed','stale'] as Plan['status'][]) {
      assert.equal(canPlanLifecycleAction('freeze',context(status)),status==='draft',status);
      assert.equal(canPlanLifecycleAction('validate',context(status)),
        ['frozen','ready','partial','stale'].includes(status),status);
    }
  });
  test('Execute needs Ready/Partial, allowMutation and no active WorkJob', () => {
    for(const status of ['draft','frozen','validating','ready','executing',
      'completed','partial','failed','stale'] as Plan['status'][])
      assert.equal(canPlanLifecycleAction('execute',context(status)),
        ['ready','partial'].includes(status),status);
    assert.equal(canPlanLifecycleAction('execute',context('ready',{allowMutation:false})),false);
    assert.equal(canPlanLifecycleAction('execute',context('ready',{
      plan:{id:23,status:'ready',active_work_job_id:9}})),false);
    assert.equal(canPlanLifecycleAction('execute',context('ready',{pending:true})),false);
    assert.equal(canPlanLifecycleAction('execute',context('ready',{plan:null})),false);
    assert.equal(canPlanLifecycleAction('execute',context('ready',{
      plan:{id:0,status:'ready',active_work_job_id:null}})),false);
  });
  test('Undo only on completed/partial with journal evidence and no active WorkJob', () => {
    for(const status of ['draft','frozen','ready','completed','partial','stale'] as Plan['status'][])
      assert.equal(canPlanLifecycleAction('undo',context(status)),
        ['completed','partial'].includes(status),status);
    for(const missing of [{journalTotal:0},{journalTotal:-1},{journalTotal:0.2},
      {journalReady:false},{pending:true},{plan:{id:23,status:'partial',active_work_job_id:1}}])
      assert.equal(canPlanLifecycleAction('undo',context('partial',missing)),false);
  });
  test('Execute and Undo confirmations reject changed status, job, safe mode, journal, plan ID', () => {
    const confirmed=planConfirmationSnapshot('execute',context('ready'));
    assert.equal(confirmed?.id,23);
    assert.equal(samePlanConfirmation(confirmed,
      planConfirmationSnapshot('execute',context('ready'))),true);
    assert.equal(samePlanConfirmation(confirmed,
      planConfirmationSnapshot('execute',context('ready',{allowMutation:false}))),false);
    assert.equal(samePlanConfirmation(confirmed,
      planConfirmationSnapshot('execute',context('partial'))),false);
    assert.equal(samePlanConfirmation(confirmed,
      planConfirmationSnapshot('execute',context('ready',{
        plan:{id:24,status:'ready',active_work_job_id:null}})),false);
    assert.equal(samePlanConfirmation(confirmed,
      planConfirmationSnapshot('execute',context('ready',{
        plan:{id:23,status:'ready',active_work_job_id:2}})),false);
    const undo=planConfirmationSnapshot('undo',context('completed'));
    assert.equal(samePlanConfirmation(undo,
      planConfirmationSnapshot('undo',context('completed',{journalTotal:13}))),false);
    assert.equal(samePlanConfirmation(undo,confirmed),false);
    assert.equal(samePlanConfirmation(undo,null),false);
  });
  test('native Plan Detail retains server lifecycle, safe deletion and readonly journal/rebuild', () => {
    const s=read('src/pages/Plans/PlanDetail.tsx');
    for(const token of [
      "queryKey: ['planDetail', planId, page, pageSize]",
      'plansApi.getPlanDetail(planId, page, pageSize)',
      'plansApi.getOperationJournal(planId, 1, 1)',
      'plansApi.freezePlan(planId)', 'plansApi.validatePlan(planId)',
      'plansApi.executePlan(planId)', 'plansApi.createUndoPlan(planId)',
      'plansApi.deletePlan(planId)', 'invalidatePlanDeleteFailure(queryClient, planId)',
      'canPlanLifecycleAction(', 'planConfirmationSnapshot(',
      'samePlanConfirmation(', 'actionInFlight.current',
      '!settings?.allow_mutation', 'active_work_job_id',
      "plan.status === 'stale'", 'isStaleDedupePlan', 'isStaleWorkflowPlan',
      'Hardlink 计划', 'Reflink 计划',
      'UNDO', 'ALLOW_MUTATION=false', 'PLAN_STALE',
      'onDelete={() => deleteMutation.mutateAsync()}',
      '<PlanDeleteButton', '<OperationJournalDrawer', '<StaleRebuildDrawer',
      'onRebuildSuccess', '<ConsoleConfirmDialog', '<ConsoleButton',
      '<ConsolePagination', '<ResponsiveDataView', '<table',
      '<StatusBadge', '<CodePath', '<ConsoleEmpty',
      'Freeze → Validate → Execute',
      "'tasksList'", "'workJobs'",
    ])assert.ok(s.includes(token),token);
    assert.doesNotMatch(s,/from ['"]antd['"]|@ant-design\/icons|<Table\b|<Pagination\b|<Popconfirm\b|<Tooltip\b|<Alert\b|<Spin\b|message\.(success|error)/);
  });
  test('native styles keep keyboard focus, mobile, dark theme and reduced-motion', () => {
    const css=read('src/styles/console-v2-plan-detail.css');
    for(const token of ['.nfc-v2-plan-actions','.nfc-v2-plan-notice',
      '.nfc-v2-plan-table','.nfc-v2-plan-confirm',
      "data-theme='dark'",'max-width:767px','focus-visible',
      'min-height:44px','prefers-reduced-motion:reduce'])
      assert.ok(css.includes(token),token);
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-plan-detail.css';"));
  });
});
