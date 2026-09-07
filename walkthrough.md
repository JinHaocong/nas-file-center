# NAS File Center v0.3.5 Gate5-C-hotfix3 — Implementation & Verification Walkthrough

## 1. Context & Review Findings Addressed (背景与审查问题修复)

### 1.1 前序状态与基线
```text
Gate2 = PASS (55 tests)
Gate3 = PASS (60 tests)
Gate4 = PASS (59 tests)
Gate5-A = PASS (30 tests)
Gate5-B = PASS / CLOSED (nas-file-center-v0.3.5-gate5b-hotfix4.zip)

Gate5-C-hotfix2 = HOLD (SHA256: 0f560eba8b8e36c70032e5894167bdd45f417b1bcfafa94268e1af409e7c15e5)
Gate5-C-hotfix3 candidate ready for independent review
Gate5-C = HOLD pending independent review
Gate5-D = FORBIDDEN
v0.3.5 = NOT CLOSED
```

### 1.2 本轮关闭的核心审查缺陷 (P2 / P3 Findings)

- **P2-12: Strict SHA must use `re.fullmatch` (血统 SHA 严格全匹配，彻底排除换行符)**:
  - 原实现使用 `re.match(r"^[0-9a-fA-F]{64}$", value)`，在 Python 正则中 `$` 允许末尾匹配 `\n`，导致 `"a"*64 + "\n"` 能绕过校验返回 200。
  - 核心修复：后端全面改用 `re.fullmatch(r"[0-9a-fA-F]{64}", value)` 校验 `definition_sha256` 与 `compile_digest`。
  - 验证效果：`64 hex + "\n"`、`64 hex + "\r"`、`64 hex + " "` 均严格被拒，返回 400 `PLAN_REBUILD_LINEAGE_MISSING`。

- **P2-13: Stale rebuild refresh readiness race (过期重建刷新就绪态竞态消除)**:
  - 原实现中 `handleManualRefresh()` 在请求开始前就重置了失效标志，造成在后台重新拉取预览期间旧的失效摘要再次可见且允许提交。
  - 核心修复：
    - 引入独立状态机计算函数 `computeRebuildReadiness`；
    - 当捕获 409 `PREVIEW_CHANGED` 时：`previewInvalidated = true` 且 `acceptedDigest = null`；
    - 用户点击“刷新预览”时：保持 `previewInvalidated = true` 并清空 `acceptedDigest`，启动 refetch；
    - 结合 `isLoading || isFetching` 全状态锁定提交按钮；
    - 只有当 refetch 成功完成且携带最新非空 `compile_digest` 时，才更新 `acceptedDigest` 并恢复 `previewInvalidated = false`；
    - 若 refetch 发生任何网络错误或关联工作流归档，保持锁定禁用提交。

- **P2-14: Root selector state / cardinality (根目录选择器状态切换与基数统一)**:
  - 状态重置：`WorkflowPreviewPanel` 在 `mode / workflowId / revision` 发生变动时，必须通过 `useEffect` 彻底清空 `selectedRoots`，杜绝文件模式下的 `[1, 2]` 跨模式遗留到整理模式；
  - 基数约束：
    - 整理模式（Organizer）：UI 严格限制且仅允许单选 1 个根目录；
    - 文件模式（File）：UI 严格限制多选上限为 1..16 个根目录（`maxCount={16}`），选项在选满 16 个后自动禁用未选项；
    - 提取统一规范化函数 `normalizeSelectedRoots`，保证 `ScanStepEditor` 与 `WorkflowPreviewPanel` 运行时覆盖基数契约完全一致；后端 `ROOT_LIMIT_EXCEEDED` 保持终态权威兜底。

- **P2-15: Organizer Profile import must exact fresh GET (整理配置导入强制发起实时 GET)**:
  - 原实现从 `listProfiles()` 的本地分页缓存中提取对象生成快照；
  - 核心修复：用户在下拉框选择 Profile ID 后，组件立即通过 `await organizerProfilesApi.getProfile(profileId)` 向服务端获取权威实时配置实体，再经 `importProfileToSnapshot` 纯净深拷贝为包含 14 个规范字段的独立快照；
  - 彻底剔除 `id`、`source_profile_id`、`created_at`、`updated_at`、`is_builtin` 等元数据，确保生成的快照不与源方案产生任何运行时活绑定或后续联动；
  - 测试用例直接导入生产实现 `import { importProfileToSnapshot } from '../src/utils/organizerDefaults.js'` 进行断言，禁止在测试中复制同名本地副本。

- **P3-01: Walkthrough accuracy & repo inclusion (交付演练文档准确性与版本标识更新)**:
  - 彻底清理过期的 Gate5-C-hotfix1 文档残留，在代码仓库根目录与构建产物中统一提供完整的 Gate5-C-hotfix3 交付演练文档；
  - 准确记录 hotfix2 审查问题、hotfix3 修复点、全量回归数据与制品校验信息。

---

## 2. Code Changes Summary (代码变更概览)

### 2.1 后端服务层
- `app/service.py`:
  - 在 `_validate_rebuild_eligibility()` 中，将 `re.match(r"^[0-9a-fA-F]{64}$", ...)` 替换为 `re.fullmatch(r"[0-9a-fA-F]{64}", ...)`。
- `tests/test_gate5c_hotfix3_backend.py`:
  - 新增 7 组精准断言，严格覆盖尾随 `\n`、`\r`、空格等变体的拒绝与合法 64 位十六进制的接受。

### 2.2 前端工具与状态机
- `frontend/src/utils/rebuildReadiness.ts`:
  - 导出 `computeRebuildReadiness({ hasPreview, previewInvalidated, acceptedDigest, isLoading, isFetching })`。
- `frontend/src/utils/rootCardinality.ts`:
  - 导出 `normalizeSelectedRoots(roots, mode)`，严格实现整理模式单选规范化与文件模式 16 上限截断。
- `frontend/tests/hotfix3_red.test.ts`:
  - 包含 11 个前端测试，涵盖 P2-13 状态转移矩阵、P2-14 基数边界及 P2-15 生产导入函数不可变性。

### 2.3 前端组件改造
- `frontend/src/components/plans/StaleRebuildDrawer.tsx`:
  - 维护 `acceptedDigest`，在 `handleManualRefresh()` 中保持失效锁定直至成功刷新，提交按钮结合 `isFetching` 全状态保护。
- `frontend/src/components/workflows/ScanStepEditor.tsx`:
  - 文件模式多选增加 `maxCount={16}` 与选满 16 项后的未选项禁用逻辑。
- `frontend/src/pages/Workflows/WorkflowPreviewPanel.tsx`:
  - `mode/workflowId/revision` 变动时清空 `selectedRoots`；
  - `handleRootsChange` 接入 `normalizeSelectedRoots`；
  - 文件模式增加 `maxCount={16}` 限制。
- `frontend/src/components/workflows/OrganizerStepEditor.tsx`:
  - 导入流程改为异步实时 `organizerProfilesApi.getProfile(profileId)`，增设 `isImporting` 加载态。

---

## 3. Verification & Acceptance Results (验证与验收结果)

### 3.1 前端单元与契约测试套件
```bash
node scripts/run-tests.mjs
# tests 244
# suites 78
# pass 244
# fail 0
# duration_ms 148.46
```

### 3.2 前端类型检查与生产构建
```bash
npm run typecheck
# > tsc --noEmit (0 errors)

npm run build
# > tsc && vite build
# ✓ 3747 modules transformed.
# ✓ built in 3.35s
```

### 3.3 后端全量测试套件
```bash
docker exec -t -e PYTHONPATH=/app nas-test-env pytest -q
# 615 passed in 39.12s
```

### 3.4 真实 Docker 生产容器端到端黑盒验收
运行 `scratch/test_gate5c_hotfix3_blackbox_acceptance.py` 基于镜像 `nas-file-center:v0.3.5-gate5c-hotfix3`：
```text
============================================================
GATE5-C-HOTFIX3 REAL DOCKER CONTAINER BLACK-BOX ACCEPTANCE REPORT
============================================================
CP1_STRICT_SHA_TRAILING_NEWLINE_REJECTED: PASS
CP2_PREVIEW_CHANGED_REJECTS_OLD_DIGEST  : PASS
CP7_FILE_MAX_ROOTS_16_ENFORCED          : PASS
CP6_ORGANIZER_SINGLE_ROOT_ENFORCED      : PASS
CP8_9_PROFILE_FRESH_IMPORT_AND_IMMUTABILITY: PASS
CP10_REBUILD_LIFECYCLE_READY            : PASS (new_plan_id=2)
CP11_SQLITE_INTEGRITY                   : PASS (ok)
============================================================
ALL ACCEPTANCE CHECKPOINTS PASSED PERFECTLY!
```

---

## 4. Current Formal Status (当前正式状态)

```text
Gate2 = PASS (55 tests)
Gate3 = PASS (60 tests)
Gate4 = PASS (59 tests)
Gate5-A = PASS (30 tests)
Gate5-B = PASS / CLOSED

Gate5-C-hotfix3 candidate ready for independent review
Gate5-C = HOLD pending independent review
Gate5-D = FORBIDDEN
v0.3.5 = NOT CLOSED
```
