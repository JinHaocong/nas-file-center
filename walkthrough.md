# NAS File Center v0.3.3-step2-fixed8-hotfix2 验收报告与实现文档
## Plan Detail 404 Stale Cache Final Fix

## 1. Baseline（基线说明）
- **基线版本**：`NAS File Center v0.3.3-step2-fixed8-hotfix1`（Commit: `b1156eb`）。
- **性质定位**：Plan Detail 404 后端真值与 TanStack Query 陈旧缓存优先级（Error-Truth vs Stale Cache）终局修复。
- **严格约束**：
  - **Backend production diff = 0**：`app/service.py`、`app/api/router.py`、`app/models.py`、`app/tasks/**` 保持 100% 零改动；
  - 零数据库 Schema 变更、零迁移变更、零新增第三方依赖；
  - 维持现有 Plan Engine、Worker Concurrency、Scan Lifecycle 零改动。

---

## 2. 根因剖析与修复实现（RED → GREEN）

### A. TanStack Query 陈旧数据与 Refetch 错误机制（Stale Data + Refetch Error Root Cause）
- **真实场景与缺陷根因**：
  1. 窗口 A 访问并加载了 Plan #18（状态为 `ready`），TanStack Query 缓存了该数据，页面展示详情及操作按钮（包括 `[删除]`）。
  2. 窗口 B 删除了 Plan #18（数据库中该记录已不存在）。
  3. 窗口 A 点击 `[删除]` 按钮触发删除，后端返回 `404 Not Found`。
  4. 依据 hotfix1 的机制，前端触发缓存失效：`queryClient.invalidateQueries({ queryKey: ['planDetail', 18] })`。
  5. TanStack Query 在后台发起重新请求 `GET /api/plans/18`，后端返回 `404 Not Found`。
  6. **关键行为**：TanStack Query 在已有缓存数据（data）的情况下，若重新请求（refetch）失败，默认保留旧的 `data`，同时设置 `isError: true` 及 `error`。TanStack Query **不会**在 refetch error 时自动清空旧 `data`。
  7. **为什么 `if (!plan)` 不足**：此前 [`PlanDetail.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/pages/Plans/PlanDetail.tsx) 仅通过 `if (!plan)` 判断是否展示“计划不存在”提示。由于 `plan` 依然持有 stale cache 中的旧数据（truthy），该判断被绕过，页面继续渲染旧 Plan #18 的正常视图与操作按钮（包含 `[删除]`、`[执行]` 等），产生虚假能力（Fake Capability）与陈旧态死循环。

---

### B. RED 阶段验证
- 在 `frontend/tests/plan_cleanup.test.ts` 中构建关键回归用例（Case B）：
  - 模拟状态：`isLoading = false`, `isError = true`, `error = { status: 404 }`, `hasPlan = true`（存在 stale cache）。
  - 在原实现逻辑下（仅判 `!plan`），该状态会被判定为 `ready` 并渲染正常操作界面，无法识别 404 后端真实状态，断言失败，精准复现。

---

### C. GREEN 阶段实现与渲染优先级（Error Truth Priority）
1. 在 [`frontend/src/components/plans/plan_cleanup.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/plans/plan_cleanup.ts) 建立精确的状态机辅助纯函数：
   - `isPlanNotFoundError(error)`：通过 `error.status === 404 || error.response?.status === 404` 准确识别 HTTP 404 错误。
   - `getPlanDetailRenderState({ isLoading, isError, error, hasPlan })`：
     ```typescript
     if (isLoading) return 'loading';
     if (isError && isPlanNotFoundError(error)) return 'not-found';
     if (isError) return 'error';
     if (!hasPlan) return 'empty';
     return 'ready';
     ```
2. 渲染优先级与行为准则：
   - **404 优先于 stale cache**：只要最新请求返回 404，不论缓存中是否有旧数据，均严格阻断普通计划渲染，展示 Alert*“计划不存在：未找到 ID 为 #${planId} 的批处理计划”*并提供 `[返回计划列表]` 按钮；
   - **非 404 错误（500、网络错误等）**：展示 Alert*“加载计划失败”*并提供 `[重试]` 按钮，拒绝将旧缓存伪装成当前系统真实状态；
   - **409 行为保持一致**：当删除遇到 409 Conflict 时，失效触发重新读取，获取最新跃迁状态（如 `executing`），正常展示执行中界面并将删除按钮置灰，展示“计划正在校验或执行中，禁止删除”；
   - **hotfix1 的失效逻辑完好保留**：`invalidatePlanDeleteFailure()` 继续在删除失败后全面失效相关 query，两层防护共同闭环。

---

## 3. 测试矩阵与自动化回归验证

### 1. 前端测试（Node Test Runner）
- 扩展测试用例（覆盖 Cases A ~ G）：
  - Case A：无缓存 + 404 $\rightarrow$ `not-found`；
  - Case B：存在 stale 缓存 + 404 $\rightarrow$ `not-found`（核心回归用例通过）；
  - Case C：存在 stale 缓存 + 500 $\rightarrow$ `error`（拒绝展示为 ready）；
  - Case D：存在计划数据 + 无错误 $\rightarrow$ `ready`；
  - Case E：loading 状态 $\rightarrow$ `loading`；
  - Case F：无数据 + 无错误 $\rightarrow$ `empty`；
  - Case G：`isPlanNotFoundError` 精确识别各种 ApiError 结构并排除 403/409/500。
- **执行结果**：
  ```text
  # tests 105
  # suites 31
  # pass 105
  # fail 0
  ```
  **105 / 105 passed**（相比 hotfix1 的 98 tests 净增 7 个，零失败）。
- **TypeScript 类型检查**：`npm run typecheck` 退出码 0，**0 错误**。
- **生产打包构建**：`npm run build` 成功完成，耗时 3.54s。

### 2. 后端全量测试（Pytest）
- 运行环境：遵循 Rule 62（`-v "$PWD":/src:ro -w /tmp/project`），完全只读挂载并在容器内部副本运行。
- **执行结果**：
  ```text
  ======================= 283 passed, 4 warnings in 38.62s =======================
  ```
  **283 / 283 passed**（100% 通过，零回归）。

### 3. Docker 镜像与容器冒烟验证
- **镜像构建**：`docker build -t kerwinjhc/nas-file-center:0.3.3-step2-fixed8-hotfix2 .` 成功。
- **容器冒烟测试**：
  - `/health` 返回 200 OK；
  - 未认证访问 `/api/plans`、`/api/plans/legacy/summary`、`/api/plans/clear-history` 均严格返回 401 Unauthorized。

---

## 4. 干净发布包验证与 Release Decision

- **干净归档**：使用 `git archive` 打包，排除 `.git`、`node_modules`、缓存与临时数据库。
- **解压独立验证**：在 `/tmp/verify_clean_step2_fixed8_hotfix2` 独立解压运行前端测试、TypeScript 校验、构建及后端 Docker 全量测试，100% 验证通过。
- **Release Decision**：**PASS / APPROVED**。
