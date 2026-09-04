# NAS File Center v0.3.3-step2-fixed8-hotfix3 验收报告与实现文档
## Plan Detail Non-404 Error Priority Final Fix

## 1. Baseline（基线说明）
- **基线版本**：`NAS File Center v0.3.3-step2-fixed8-hotfix2`（Commit: `9893dc5`）。
- **性质定位**：Plan Detail 非 404 错误（500 服务端异常、网络中断等）展示优先级缺陷终局修复。
- **严格约束**：
  - **Backend production diff = 0**：`app/**` 零修改；
  - 零数据库 Schema 变更、零迁移变更、零新增依赖；
  - 严格保持已有 Plan Engine、Worker Concurrency、Scan Lifecycle。

---

## 2. 根因剖析与修复实现（RED → GREEN）

### A. 首次加载/无缓存下 !plan 提前拦截导致的“假 404”（Non-404 Error Misclassification Root Cause）
- **真实场景与缺陷根因**：
  1. 用户初次打开计划详情页（例如 `/plans/18`）或浏览器缓存为空；
  2. 此时 TanStack Query 发起 `GET /api/plans/18`；
  3. 若后端返回 500 Internal Server Error，或者遭遇网络不可达/超时错误：
     - TanStack Query 状态为：`isLoading = false`, `isError = true`, `error = { status: 500 }`, `plan = undefined`；
     - `getPlanDetailRenderState()` 正确计算出 `renderState = 'error'`；
  4. 然而，原组件 `PlanDetail.tsx` 内的渲染判断顺序为：
     ```tsx
     if (renderState === 'not-found' || renderState === 'empty' || !plan) {
       return <Alert message="计划不存在" ... />;
     }
     if (renderState === 'error') {
       return <Alert message="加载计划失败" ... />;
     }
     ```
  5. 由于初次加载失败时 `plan` 为 `undefined`，导致 `!plan === true`。
  6. 执行流在到达 `renderState === 'error'` 之前就被第一条分支拦截，错误地将 500 或网络故障渲染为“计划不存在”（未找到 ID 为 #18 的批处理计划），严重误导用户认为是数据不存在，而非系统故障或网络故障。

---

### B. RED 阶段验证
- 在 `frontend/tests/plan_cleanup.test.ts` 中针对无缓存 500 及网络错误场景构建关键回归用例（Case G、Case H）：
  - 模拟状态：`isLoading = false`, `isError = true`, `error = { status: 500 }`, `hasPlan = false`。
  - 在原实现逻辑下，由于组件先检测 `!plan`，因此会错误渲染 not-found 视图，断言失败，精准复现。

---

### C. GREEN 阶段实现与渲染优先级（Strict View Hierarchy）
1. 在 [`frontend/src/components/plans/plan_cleanup.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/plans/plan_cleanup.ts) 建立纯函数视图决策：
   - 导出 `PlanDetailView`: `'loading' | 'not-found' | 'error' | 'ready'`。
   - `getPlanDetailView(renderState, hasPlan)`：
     ```typescript
     if (renderState === 'loading') return 'loading';
     if (renderState === 'not-found') return 'not-found';
     if (renderState === 'error') return 'error'; // 关键：即便 hasPlan 为 false，仍然优先进入 error
     if (renderState === 'empty' || !hasPlan) return 'not-found';
     return 'ready';
     ```
2. 在 [`frontend/src/pages/Plans/PlanDetail.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/pages/Plans/PlanDetail.tsx) 重构分支渲染流程：
   - 使用 `getPlanDetailView(renderState, !!plan)` 严格遵循：
     1. `loading`：展示加载 Spin 指示器；
     2. `not-found`：展示“计划不存在”，提供“返回计划列表”按钮；
     3. `error`：展示“加载计划失败”，展示真实错误描述并提供“重试”按钮；
     4. `empty` / `!plan`：计划不存在兜底；
     5. `ready`：正常渲染计划内容。
   - 彻底杜绝了 500 / 网络错误被篡改为 404 的问题。

---

## 3. 测试矩阵与自动化回归验证

### 1. 前端测试（Node Test Runner）
- 扩展覆盖用例（Cases G ~ M）：
  - Case G：无缓存 (hasPlan: false) + 500 错误 $\rightarrow$ 严格返回 `'error'`，绝非 `'not-found'`；
  - Case H：无缓存 (hasPlan: false) + 网络错误 $\rightarrow$ 严格返回 `'error'`，绝非 `'not-found'`；
  - Case I：陈旧缓存 (hasPlan: true) + 500 错误 $\rightarrow$ 严格返回 `'error'`；
  - Case J：404 错误（无论有无缓存）$\rightarrow$ 严格返回 `'not-found'`；
  - Case K：加载中（无论有无数据）$\rightarrow$ 严格返回 `'loading'`；
  - Case L：空数据且无错误 $\rightarrow$ 严格返回 `'not-found'`；
  - Case M：就绪且数据存在 $\rightarrow$ 严格返回 `'ready'`。
- **执行结果**：
  ```text
  # tests 112
  # suites 31
  # pass 112
  # fail 0
  ```
  **112 / 112 passed**（相比 hotfix2 的 105 tests 净增 7 个，零失败）。
- **TypeScript 类型检查**：`npm run typecheck` 退出码 0，**0 错误**。
- **生产打包构建**：`npm run build` 成功完成，耗时 3.80s。

### 2. 后端全量测试（Pytest）
- 运行环境：遵循 Rule 62（`-v "$PWD":/src:ro -w /tmp/project`），完全只读挂载并在容器内部副本运行。
- **执行结果**：
  ```text
  ======================= 283 passed, 4 warnings in 38.51s =======================
  ```
  **283 / 283 passed**（100% 通过，零回归）。

### 3. Docker 镜像与容器冒烟验证
- **镜像构建**：`docker build -t kerwinjhc/nas-file-center:0.3.3-step2-fixed8-hotfix3 .` 成功。
- **容器冒烟测试**：
  - `/health` 返回 200 OK；
  - 未认证访问 `/api/plans` 严格返回 401 Unauthorized。

---

## 4. 干净发布包验证与 Release Decision

- **干净归档**：使用 `git archive` 打包，排除 `.git`、`node_modules`、缓存与临时数据库。
- **解压独立验证**：在 `/tmp/verify_clean_step2_fixed8_hotfix3` 独立解压运行前端测试、TypeScript 校验、构建及后端 Docker 全量测试，100% 验证通过。
- **Release Decision**：**PASS / APPROVED**。
