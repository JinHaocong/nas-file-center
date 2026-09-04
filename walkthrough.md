# NAS File Center v0.3.3-step2-fixed10-hotfix2 验收报告与实现文档
## Audit Retention Query-Error Wiring Final Fix

## 1. Baseline 与版本说明（Version & Baseline）
- **交付版本**：`NAS File Center v0.3.3-step2-fixed10-hotfix2`
- **基线版本**：`v0.3.3-step2-fixed10-hotfix1`
- **基线 Commit**：`edcc62e4e06023193251ea92d4aa18d5e4d72001`
- **基线发布包 SHA256**：`f008163bccd445d3eda4acaecf80b97b0d7c595a66eaa3034ed03931fcf2e799`
- **提交作者**：`Jin Haocong <jinhaocong@outlook.com>`
- **发布产物**：`nas-file-center-v0.3.3-step2-fixed10-hotfix2.zip`
- **Docker 镜像**：`kerwinjhc/nas-file-center:0.3.3-step2-fixed10-hotfix2`

---

## 2. 缺陷根因与装配缺失分析（Root Cause & Wiring Gap Analysis）

### A. 缺陷根因
在 fixed10-hotfix1 中，辅助函数 `getAuditRetentionApplyAvailability` 已经完备支持了 `options.isQueryError`：
```ts
if (options?.isQueryError) {
  return {
    canApply: false,
    disabledReason: '获取保留策略或清理预览失败，请刷新重试',
  };
}
```
并且在单元测试中验证了 `isQueryError: true` 时能够严格禁用清理按钮并提示刷新重试。

然而，在业务组件 `frontend/src/pages/Settings/index.tsx` 的实际装配代码中：
```tsx
// fixed10-hotfix1 原始代码
const { data: lifecyclePolicy, refetch: refetchPolicy } = useQuery({
  queryKey: ['dataLifecyclePolicy'],
  queryFn: () => dataLifecycleApi.getPolicy(),
});

const { data: retentionPreview, isLoading: previewLoading, refetch: refetchPreview } = useQuery({
  queryKey: ['auditRetentionPreview'],
  queryFn: () => auditApi.getRetentionPreview(),
});

...

const availability = getAuditRetentionApplyAvailability(
  lifecyclePolicy,
  retentionPreview,
  {
    isSavingPolicy: savePolicyMutation.isPending,
    isPreparingApply: prepareApplyPending,
    isApplying: applyRetentionMutation.isPending,
  }
);
```

存在以下装配缺失（Wiring Gap）：
1. 组件未从 `dataLifecyclePolicy` 查询中解构 `isError`；
2. 组件未从 `auditRetentionPreview` 查询中解构 `isError`；
3. `getAuditRetentionApplyAvailability` 调用的配置参数中遗漏了 `isQueryError`。

### B. 潜在生产影响
TanStack Query 在后台静默刷新失败（例如网络抖动、临时 500 错误、网关超时等）时，其内部行为是：
- 维持既有缓存数据 `data` 不变（仍然为 truthy 对象）；
- 将 `isError` 置为 `true`。

由于页面仅检查了 `!policy`，当存在旧缓存且后台查询出错时，`lifecyclePolicy` 仍为旧对象，导致前端按钮依然保持“可执行”状态。若用户点击执行，可能基于已损坏或过期的状态触发操作。

---

## 3. 修复实现与规范装配（Hotfix Implementation & Wiring）

### A. 变更范围与严格基线
- **后端代码零变更（Backend Production Diff = 0）**：`app/**` 绝对零修改；
- **数据库零变更**：Schema 零修改，Migration 零修改；
- **依赖零变更**：`package.json`, `pnpm-lock.yaml`, `pyproject.toml` 零修改；
- **组件辅助函数零修改**：`frontend/src/components/settings/data_lifecycle.ts` 零修改；
- **审计页面零修改**：`frontend/src/pages/Audit/index.tsx` 零修改。

### B. 生产代码修改（`frontend/src/pages/Settings/index.tsx`）
1. 在查询解构中捕获策略查询错误与预览查询错误：
```tsx
const { data: lifecyclePolicy, isError: policyQueryError, refetch: refetchPolicy } = useQuery({
  queryKey: ['dataLifecyclePolicy'],
  queryFn: () => dataLifecycleApi.getPolicy(),
});

const { data: retentionPreview, isLoading: previewLoading, isError: previewQueryError, refetch: refetchPreview } = useQuery({
  queryKey: ['auditRetentionPreview'],
  queryFn: () => auditApi.getRetentionPreview(),
});
```
2. 将查询错误合成后传入可用性判断：
```tsx
const availability = getAuditRetentionApplyAvailability(
  lifecyclePolicy,
  retentionPreview,
  {
    isSavingPolicy: savePolicyMutation.isPending,
    isPreparingApply: prepareApplyPending,
    isApplying: applyRetentionMutation.isPending,
    isQueryError: policyQueryError || previewQueryError,
  }
);
```

当保留策略查询失败或清理预览查询失败的任一场景发生时，`isQueryError` 立即为 `true`，执行按钮严格置灰，并真实提示：“获取保留策略或清理预览失败，请刷新重试”。

---

## 4. 验证矩阵与回归测试结果（Verification Matrix）

### A. 前端自动化测试（`npm test`）
- **测试文件**：[`frontend/tests/data_lifecycle.test.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/tests/data_lifecycle.test.ts)
- **新增用例（Hotfix 2: Query-Error Wiring Integration）**：
  1. `Settings/index.tsx destructures isError from dataLifecyclePolicy query`（源码契约验证解构 `policyQueryError`）
  2. `Settings/index.tsx destructures isError from auditRetentionPreview query`（源码契约验证解构 `previewQueryError`）
  3. `Settings/index.tsx passes isQueryError into getAuditRetentionApplyAvailability`（源码契约验证传递 `policyQueryError || previewQueryError`）
  4. `getAuditRetentionApplyAvailability returns canApply=false and truthful disabledReason on isQueryError`（验证辅助函数在 `isQueryError` 时输出 `canApply=false` 及真实禁用文案）
- **测试结果**：**150 passed, 44 suites, 0 failed**（fixed10-hotfix1 为 146 passed，净增 4 个测试）；
- **类型检查**：`npm run typecheck` -> **0 errors**；
- **生产构建**：`npm run build` -> **0 errors**（Vite 生产构建成功）。

### B. 后端自动化测试（`pytest -q`）
- **隔离环境**：Docker Rule 62 隔离环境运行（`python:3.12-slim` + 内存工作目录）；
- **运行结果**：**330 passed, 0 failed**（全部 330 个测试 100% 通过，无回归）；
- **告警**：20 个已知安全/协议告警。

### C. 生产 Docker 镜像与冒烟验证
- **镜像标签**：`kerwinjhc/nas-file-center:0.3.3-step2-fixed10-hotfix2`
- **构建测试**：`docker build --platform linux/amd64 -t kerwinjhc/nas-file-center:0.3.3-step2-fixed10-hotfix2 .`；
- **冒烟验证项**：
  - `/health` -> `200 OK`
  - 未认证 `GET /api/data-lifecycle` -> `401 Unauthorized`
  - 管理员认证登录 -> `200 OK`
  - 缺失 Origin `PUT /api/data-lifecycle` -> `403 Forbidden`（CSRF 防护）
  - 合法 `PUT /api/data-lifecycle` -> `200 OK`
  - `GET /api/audit/retention-preview` -> `200 OK`
  - `POST /api/audit/apply-retention` -> `200 OK`
  - 前端 SPA 静态托管 -> `200 OK`。

---

## 5. 发布决议（Release Decision）
- **决议**：**PASS**
- **生产文件变更统计**：
  - 后端：0 个修改；
  - 数据库：0 个修改；
  - 前端生产：1 个文件修改（`frontend/src/pages/Settings/index.tsx`）；
  - 测试套件：1 个文件修改（`frontend/tests/data_lifecycle.test.ts`）；
  - 交付文档：1 个文件修改（`walkthrough.md`）。
