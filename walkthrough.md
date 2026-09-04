# NAS File Center v0.3.3-step2-fixed10-hotfix1 验收报告与实现文档
## Audit Retention Apply Confirmation Truthfulness Fix

## 1. Baseline 与版本说明（Version & Baseline）
- **交付版本**：`NAS File Center v0.3.3-step2-fixed10-hotfix1`
- **基线版本**：`v0.3.3-step2-fixed10`
- **基线 Commit**：`d9c7e44890b59d72c641c1cb87bc85f733b08c08`
- **基线发布包 SHA256**：`732b810a37ced2559b1d9e89cea98451d792715ff5828b029bdb53b2be79ab5f`
- **基线 SHA 文档修正（Baseline Correction）**：
  在 fixed10 原说明文档中，引用 fixed9-hotfix1 基线发布包 SHA256 时误标为 fixed9 原始包哈希（`f68dc648...`），在此正式纠正为 fixed9-hotfix1 真实发布包 SHA256：`c9727acb2061beaf5873dc9826fd6f36529f014fd66370135529106fe2184c0f`。
- **提交作者**：`Jin Haocong <jinhaocong@outlook.com>`
- **发布产物**：`nas-file-center-v0.3.3-step2-fixed10-hotfix1.zip`
- **Docker 镜像**：`kerwinjhc/nas-file-center:0.3.3-step2-fixed10-hotfix1`

---

## 2. 缺陷根因与陈旧缓存确认窗口（Blocker Root Cause & Stale Cache Window）

### A. 缺陷根因
在 fixed10 实现中，用户在设置页点击“执行审计清理”时，前端处理函数直接从当前 React 闭包作用域中读取 `lifecyclePolicy` 与 `retentionPreview`，并直接弹出 `Modal.confirm`：
```tsx
// fixed10 原始实现
const handleConfirmApplyRetention = () => {
  Modal.confirm({
    content: (
      <div>
        <p>将按照系统已保存的策略（{formatAuditRetention(lifecyclePolicy?.audit_retention_days)}）...</p>
        <p>拟删除记录数：{retentionPreview?.delete_count ?? 0} 条。</p>
      </div>
    ),
    ...
  });
};
```
当出现以下真实场景时：
1. 数据库当前保留策略为 90 天，当前预览拟删除 100 条；
2. 用户将输入框修改为 30 天并点击“保存策略”；
3. 后端成功更新数据库 `DataLifecyclePolicy(audit_retention_days=30)`；
4. React Query 触发了 `invalidateQueries`，但网络重新请求尚未返回；
5. 用户在此微小窗口内点击“执行审计清理”；
6. 弹窗直接使用旧闭包数据，显示“已保存策略：90 天，拟删除：100 条”；
7. 用户确认后，后端 `apply_audit_retention()` 正确读取数据库最新策略（30 天）并实际删除了 500 条；
8. 导致用户在弹窗中确认的内容与后端实际执行的破坏性操作发生严重偏离（UI Truthfulness Divergence）。

此外，原始确认弹窗文案存在过度确定性（直接宣称“永久清理截止时间...之前的全部审计日志，拟删除记录数：X条”），未向用户声明预览仅为预计值、实际执行将按执行时刻数据库最新策略与最新数据重新计算，且未明确声明 NAS 物理文件及 Task/Scan/Plan/Index 业务实体的绝对安全边界。

---

## 3. 修复实现与真实验证语义（Hotfix Implementation & Semantics）

### A. 后端语义完全保持（Backend Production Diff = 0）
- 后端 [`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py) 与 [`app/api/router.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/api/router.py) 零改动；
- 后端 `POST /api/audit/apply-retention` 继续保持严格权威性：完全忽略客户端 days、cutoff 或预计删除行数，直接在 `BEGIN IMMEDIATE` 事务中读取当前持久化策略单例，原子执行清理并生成自审计；
- 数据库 Schema Diff = 0，Migration Diff = 0，依赖库 Diff = 0。

### B. 弹窗前主动刷新（Fresh Refetch Before Confirmation Modal）
在 [`frontend/src/pages/Settings/index.tsx`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/pages/Settings/index.tsx) 中重构触发链路：
1. **状态跟踪**：引入 `prepareApplyPending` 状态；
2. **准备链路（`handlePrepareApply`）**：
   - 点击“执行审计清理”后，不立即弹出 Modal，而是设置 `prepareApplyPending = true`；
   - 并行调用 `refetchPolicy()` 与 `refetchPreview()`，强制从服务端获取最新持久化策略与最新分析结果；
   - 提取最新返回的数据对象 `freshPolicy = policyResult.data` 与 `freshPreview = previewResult.data`；
   - **失败即关闭（Fail-Closed）**：若刷新失败或数据为空，不打开确认弹窗，不调用执行接口，提示用户刷新重试；
   - **永久保留阻断**：若 `freshPolicy.audit_retention_days === 0`，提示当前为永久保留，不打开确认弹窗；
   - **使用最新数据渲染**：将 `freshPolicy` 与 `freshPreview` 传入 `showApplyConfirmation()`，彻底杜绝陈旧闭包数据污染弹窗。

### C. 按钮可用性矩阵健全化（Apply Availability Matrix）
在 [`frontend/src/components/settings/data_lifecycle.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/src/components/settings/data_lifecycle.ts) 扩展 `getAuditRetentionApplyAvailability`：
- `isSavingPolicy`: 保存策略进行中，Apply 禁用（提示“正在保存保留策略，请稍候”）；
- `isPreparingApply`: 弹窗准备刷新中，Apply 禁用并展示 loading（提示“正在刷新最新保留策略与清理预览，请稍候”）；
- `isApplying`: 执行清理中，Apply 禁用并展示 loading；
- `isQueryError`: 查询错误时，Apply 禁用（提示“获取保留策略或清理预览失败，请刷新重试”）；
- `policy.audit_retention_days === 0`: 严格禁用（“当前保留策略为永久保留（0 天），不可执行清理”）；
- `preview.delete_count === 0`: 依然允许执行（保留 zero-candidate 自审计能力，标记 `isZeroCandidates: true`）。

### D. 确认弹窗文案真实性与安全边界声明（Truthful Disclosure Copy）
确认弹窗文本全面升级为真实、透明、合规的警示结构：
1. **当前生效策略**：明确标示 `当前已保存策略：保留最近 X 天`；
2. **预览预计属性**：明确标示 `当前最新预览：预计清理 X 条 Audit 历史记录`；
3. **重新计算披露（Recompute Disclosure）**：
   明确声明：*“当前预览仅为预计结果。实际执行时将根据数据库中最新保存的保留策略以及执行时最新的审计数据重新计算，最终删除数量可能与当前预览不同。”*
4. **安全边界（Safety Boundaries）**：
   明确声明：*“本操作仅清理符合保留期条件的 Audit 历史记录。不会删除 NAS 上的真实文件或目录，也不会删除 Task、Scan、Plan 或 Index 数据。”*
5. **不可逆警示**：*“审计历史清理不可撤销。”*
6. **成功反馈真实性**：清理成功提示严格使用后端返回的 `res.deleted_count`（`已清理 ${res.deleted_count} 条记录`），绝不使用预览数字冒充。

---

## 4. 验证矩阵与回归测试结果（Verification Matrix）

### A. 前端自动化测试（`npm test`）
- **测试文件**：[`frontend/tests/data_lifecycle.test.ts`](file:///Users/Kerwin/MyProject/nas-file-center/frontend/tests/data_lifecycle.test.ts)
- **新增用例**：
  1. `Settings/index.tsx includes truthful advisory and recomputation disclosure in confirmation`
  2. `Settings/index.tsx includes non-filesystem and non-task/scan/plan/index safety boundary in confirmation`
  3. `Settings/index.tsx executes fresh policy and preview refetch before Modal.confirm and uses fresh result`
  4. `getAuditRetentionApplyAvailability disables apply while saving policy, preparing apply, or applying`
  5. `zero-candidates with positive policy continues to allow apply (regression guard)`
  6. `policy 0 continues to strictly disable apply (regression guard)`
  7. `save policy never triggers apply retention (Save != Apply invariant)`
  8. `apply success feedback truthfully uses backend response.deleted_count`
- **测试结果**：**146 passed, 43 suites, 0 failed**（fixed10 基线为 138 passed，净增 8 个用例）；
- **类型检查**：`npm run typecheck` -> **0 errors**；
- **生产构建**：`npm run build` -> **0 errors**（Vite 生产构建成功）。

### B. 后端自动化测试（`pytest -q`）
- **运行结果**：**330 passed, 0 failed**（全部 330 个测试 100% 通过，无回归）；
- **真实告警报告**：20 个告警（18 个基线告警 + 2 个 Starlette/AnyIO 测试客户端废弃提示）。

### C. 生产 Docker 镜像与冒烟验证
- **镜像标签**：`kerwinjhc/nas-file-center:0.3.3-step2-fixed10-hotfix1`
- **构建测试**：`docker build --platform linux/amd64 -t kerwinjhc/nas-file-center:0.3.3-step2-fixed10-hotfix1 .` 成功；
- **冒烟测试项**：
  - `/health` -> `200 OK`
  - 未认证 `GET /api/data-lifecycle` -> `401 Unauthorized`
  - 管理员认证登录 -> `200 OK`
  - 缺失 Origin `PUT /api/data-lifecycle` -> `403 Forbidden`（CSRF 防护）
  - 合法 `PUT /api/data-lifecycle` -> `200 OK`
  - `GET /api/audit/retention-preview` -> `200 OK`
  - `POST /api/audit/apply-retention` -> `200 OK`
  - 前端 SPA 页面 -> `200 OK`。

---

## 5. 已知并发边界（Known Limitation）
- 本轮在弹出确认弹窗前主动刷新策略与预览，且通过弹窗文案明确披露执行时以数据库最新保存策略为准；
- 若用户在打开弹窗之后、点击确认之前的窗口内，其他管理员在另一个浏览器修改了策略，后端清理将按点击确认时刻的最新持久化策略执行；
- 本轮保持极小前端修复，未引入 policy version token、ETag 或 If-Match 乐观锁协议，该理论并发边界已通过真实文案向用户披露，符合架构预期。

---

## 6. 发布决议（Release Decision）
- **决议**：**PASS**
- **生产文件变更统计**：
  - 后端：0 个变更；
  - 数据库：0 个变更；
  - 前端生产：2 个文件变更（`Settings/index.tsx`, `data_lifecycle.ts`）；
  - 测试套件：1 个文件变更（`data_lifecycle.test.ts`）；
  - 交付文档：1 个文件变更（`walkthrough.md`）。
