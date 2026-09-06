# NAS File Center v0.3.5 Gate5-C-hotfix1 — Implementation & Verification Walkthrough

## 1. Context & Review Findings Addressed (背景与审查问题修复)

### 1.1 前序状态
```text
Gate2 = PASS
Gate3 = PASS
Gate4 = PASS
Gate5-A = PASS
Gate5-B = PASS / CLOSED (nas-file-center-v0.3.5-gate5b-hotfix4.zip)

Gate5-C candidate = HOLD
Gate5-C-hotfix1 = IN PROGRESS
v0.3.5 = NOT CLOSED
```

### 1.2 本轮修复的核心审查缺陷 (P1/P2/Concurrent Race)
- **P1-01: Organizer 规范默认值全量对齐 Gate5-B-hotfix4**：
  - 规范默认值：`recursive: false`, `rename_template: "{name}"`, `statistics_template: "[{images}P {videos}V {size}]"`, `preserve_tags: []`, `cleanup_patterns: []`, `numbering_mode: "none"`, `numbering_start: 1`, `numbering_padding: 3`, `mtime_mode: "none"`, `mtime_delay_seconds: 2.0`。
  - 彻底清除所有 `{name} {statistics}` 和 `[{images}P{?videos: {videos}V} {size}]` 旧 fallback。
  - 创建统一前端规范工厂 `createDefaultOrganizerSnapshot()`，全面覆盖 `StepList`、`OrganizerStepEditor`、`OrganizerProfileFields`、`ProfileFormModal`。
- **P1-02: Workflow Rename V1 纯字面量重命名契约**：
  - 移除所有正则/regex/$1/`^(.*)$` 文案与默认值，标签明确改为“字面量匹配文本”、“字面量替换文本”。
  - 默认值设为 `pattern: 'draft', replacement: 'final'`。
  - 实现纯字面量替换逻辑 `applyLiteralRename`。
- **P2-01: 线性构建器拓扑防呆与规则校验**：
  - File 模式：Scan 步骤必须且唯一位于 index 0，Filter 步骤必须位于所有 Action 之前，Quarantine 为终端步骤不可后继追加步骤；
  - Organizer 模式：严格限制为 `Scan -> Organize`；
  - `getAllowedInsertions`、`canMoveStep`、`canDeleteStep` 精确控制步骤插入、上下移动与删除；
  - 模式切换提供确认弹窗，确认后重置为合法初始拓扑。
- **P2-02: 显式 Preview 状态机与 409 防自肥保护**：
  - 移除自动 `useQuery` 编译，改为用户显式点击“生成预览 / 刷新预览”按钮触发 mutation；
  - 状态机包含 `CLEAN_SAVED`, `EDITING_DIRTY`, `SAVED_PREVIEW_REQUIRED`, `PREVIEWING`, `PREVIEW_READY`, `PREVIEW_STALE`；
  - 覆盖根目录或参数变更立即转为 `PREVIEW_STALE` 并清空 `compile_digest`；
  - 遇到 409 `PREVIEW_CHANGED`：**严禁自动 refetch/retry**，清空 digest，置为 `PREVIEW_STALE`，提示用户手动刷新；
  - `StaleRebuildDrawer` 同样彻底移除 409 下的 `refetch()`。
- **P2-03: 基于 `useAuth()` 的严格 RBAC 权限矩阵**：
  - Member 角色可只读浏览、预览和生成草稿计划，严格禁止创建工作流、保存新版本、归档和回滚；
  - 归档工作流进入完全只读封存态，禁用编辑、修改、预览、生成计划和回滚。
- **P2-04: 历史版本路由与 API 支持**：
  - 完整支持 `/workflows/:id?revision=N` 路由，调用 `workflowApi.getRevision(id, revision)`；
  - 只读查看历史版本，非归档状态下支持带 exact revision 预览与生成计划草稿；
  - 管理员支持一键回滚至该历史版本；
  - `RevisionDrawer` 提供“跳转查看”快捷入口。
- **P2-05: FilterBuilder 算子矩阵与限制**：
  - 严格支持 Gate5-A 六大字段算子矩阵与时区感知 ISO 字符串、media_type 枚举、扩展名小写去点规范化；
  - 严格校验 Filter 深度 <= 5、子节点 <= 50、叶节点 <= 200。
- **P2-06: TypeScript 严格类型与元数据守卫**：
  - `FilterLeafNode.value: string | number | string[]`；
  - `isWorkflowPlanMetadata` 严格整型守卫（拦截浮点数 1.5, NaN, Infinity, 64-char 非十六进制, empty roots）。
- **Concurrent Archive Race Rebuild Protection (后端并发重构保护)**：
  - `rebuild_plan` 在 `BEGIN IMMEDIATE` 独占事务后调用 `session.expire_all()`，从数据库实时重新加载 `Workflow` 与 `WorkflowRevision`；
  - 复核 `source_wf.archived_at is None` 与 `source_rev.definition_sha256 == metadata["definition_sha256"]`；
  - 任何并发篡改或归档直接 ROLLBACK 抛 409 `PREVIEW_CHANGED` / `WORKFLOW_ARCHIVED`，0 Draft 生成。

---

## 2. Code Changes Summary (代码变更概览)

### 2.1 后端核心服务
- `app/service.py`:
  - 在 `rebuild_plan` 的独占事务开始时执行 `session.expire_all()`，重新获取不可变基线数据并做强一致性复核，若归档或版本 SHA 改变则直接抛出 409 `WorkflowDigestMismatchError`。
- `tests/test_gate5c_hotfix1_backend.py`:
  - 新增 2 个并发竞态测试（重建编译期间归档工作流、重建编译期间篡改 revision SHA256），确保 0 Draft 生成且报 409。
- `tests/test_gate5c_integration_acceptance.py`:
  - 由原 `test_gate5c_blackbox_acceptance.py` 更名，明确其定位为 TestClient 内存集成测试。

### 2.2 前端工具与状态机
- `frontend/src/utils/organizerDefaults.ts`:
  - 导出 `createDefaultOrganizerSnapshot()`，集中维护 14 项规范默认值。
- `frontend/src/utils/workflowRename.ts`:
  - 导出 `applyLiteralRename()` 纯字面量替换逻辑。
- `frontend/src/utils/workflowTopology.ts`:
  - 导出 `validateWorkflowStepOrder`、`getAllowedInsertions`、`canMoveStep`、`canDeleteStep`。
- `frontend/src/utils/workflowRbac.ts`:
  - 导出 `canCreateWorkflow`、`canSaveRevision`、`canArchiveWorkflow`、`canRollbackWorkflow`、`canPreviewWorkflow`、`canGenerateDraft`。
- `frontend/src/utils/workflowPreviewMachine.ts`:
  - 导出 `WorkflowPreviewState` 与 `transitionPreviewState`。
- `frontend/src/utils/filterMatrix.ts`:
  - 导出 `ALLOWED_OPERATORS_BY_FIELD`、`normalizeExtension`、`validateFilterLimits`。

### 2.3 前端组件与页面改造
- `frontend/src/types/workflow.ts`:
  - `FilterLeafNode.value: string | number | string[]`，`WorkflowDefinition.schema_version: 1`，`isWorkflowPlanMetadata` 严格数值与十六进制正则校验。
- `frontend/src/api/workflows.ts`:
  - 新增 `getRevision(id, revision)` 接口端点。
- `frontend/src/components/workflows/StepList.tsx`:
  - 接入拓扑规则控制、规范默认值与字面量重命名。
- `frontend/src/components/workflows/StepCard.tsx`:
  - 标签更新为“字面量重命名”，透传 `canMoveUp`, `canMoveDown`, `canDelete`, `readOnly`。
- `frontend/src/components/workflows/RenameStepEditor.tsx`:
  - 移除正则文案，改为字面量输入框。
- `frontend/src/components/workflows/OrganizerProfileFields.tsx` & `OrganizerStepEditor.tsx` & `ProfileFormModal.tsx`:
  - 清理陈旧 fallback，复用集中规范默认值。
- `frontend/src/components/workflows/FilterBuilder.tsx`:
  - 算子矩阵过滤，时区感知 ISO 字符串，media_type 枚举，递归安全校验。
- `frontend/src/components/workflows/RevisionDrawer.tsx`:
  - 支持 `isArchived` 只读模式，集成“跳转查看”版本路由，回滚操作 RBAC 防护。
- `frontend/src/pages/Workflows/WorkflowPreviewPanel.tsx`:
  - 接入显式预览状态机与 mutation，409 PREVIEW_CHANGED 禁止自动重试，参数修改切入 PREVIEW_STALE 并清空摘要。
- `frontend/src/components/plans/StaleRebuildDrawer.tsx`:
  - 移除 409 PREVIEW_CHANGED 下的自动 `refetch()`。
- `frontend/src/pages/Workflows/WorkflowBuilder.tsx`:
  - 完整接入 `/workflows/:id?revision=N` 路由、RBAC 控制、模式切换拓扑重置与归档只读警示。
- `frontend/src/pages/Workflows/WorkflowList.tsx`:
  - 完整接入 RBAC 权限控制，普通成员隐藏新建与归档操作。

---

## 3. Verification & Acceptance Results (验证与验收结果)

### 3.1 前端单元与契约测试套件
```bash
npm test
# tests 222
# suites 69
# pass 222
# fail 0
# duration_ms 134.93
```
涵盖 8 大独立审查找出的回归用例（`frontend/tests/hotfix1_red.test.ts`），全量通过。

### 3.2 前端类型检查与生产构建
```bash
npm run build
# > tsc && vite build
# vite v6.4.3 building for production...
# transforming...
# ✓ 3745 modules transformed.
# ✓ built in 3.60s
```
TypeScript 严格模式 0 警告、0 错误，静态资源打包完毕。

### 3.3 后端全量测试套件
```bash
docker exec -t -e PYTHONPATH=/app nas-test-env pytest -q
# ........................................................................ [ 11%]
# ........................................................................ [ 23%]
# ........................................................................ [ 35%]
# ........................................................................ [ 47%]
# ........................................................................ [ 59%]
# ........................................................................ [ 71%]
# ........................................................................ [ 82%]
# ........................................................................ [ 94%]
# ................................                                         [100%]
# 100% PASS
```
包含原集成套件及 `tests/test_gate5c_hotfix1_backend.py` 2 个并发竞态测试，全部通过。

### 3.4 真实 Docker 生产容器端到端黑盒验收
基于 `Dockerfile` 重新构建的真实生产镜像 `nas-file-center:v0.3.5-gate5c-hotfix1`，运行黑盒测试脚本 `scratch/test_gate5c_hotfix1_blackbox_acceptance.py`：
```text
============================================================
GATE5-C-HOTFIX1 REAL DOCKER CONTAINER BLACK-BOX ACCEPTANCE REPORT
============================================================
RBAC_MEMBER_FORBIDDEN_CREATE       : PASS
WORKFLOW_CREATE                    : PASS (id=1)
CANONICAL_ORGANIZER_DEFAULTS       : PASS
TOPOLOGY_VIOLATION_REJECTED        : PASS
WORKFLOW_PREVIEW                   : PASS (compile_digest=f222e21fbf...)
GENERATE_DRAFT_PLAN                : PASS (plan_id=1)
STALE_REBUILD_PREVIEW              : PASS
CONCURRENT_ARCHIVE_RACE_REJECTED   : PASS (code=WORKFLOW_ARCHIVED)
SQLITE_INTEGRITY                   : PASS (ok)
============================================================
ALL ACCEPTANCE CHECKPOINTS PASSED PERFECTLY!
```

---

## 4. Current Formal Status (当前正式状态)

```text
Gate2 = PASS
Gate3 = PASS
Gate4 = PASS
Gate5-A = PASS
Gate5-B = PASS / CLOSED

Gate5-C-hotfix1 candidate ready for independent review
Gate5-C = HOLD pending independent review
v0.3.5 = NOT CLOSED
```
