# NAS File Center v0.3.3-step2-fixed8-hotfix1 验收报告与实现文档
## Plan Cleanup Truthful UI & Stale-State Hotfix

## 1. Baseline（基线说明）
- **基线版本**：`NAS File Center v0.3.3-step2-fixed8`（Commit: `a2d9381`）。
- **性质定位**：UI 真实性与陈旧状态（Truthful UI & Stale-State）窄范围专项 Hotfix。
- **严格约束**：
  - **Backend production diff = 0**：`app/service.py`、`app/api/router.py`、`app/models.py`、`app/tasks/**` 保持完全零改动；
  - 零数据库 Schema 变更、零迁移变更、零新增第三方依赖；
  - 维持现有 Plan Engine、Worker Concurrency、Scan Lifecycle 零改动。

---

## 2. 核心问题根因与修复（RED → GREEN）

### Problem A: Audit 破坏性确认文案失真（Audit Destructive Confirmation Mismatch）
- **根因与失真点**：
  在 fixed8 中，删除计划确认弹窗出现文案：*“删除仅清理计划记录与审计流水，不会撤销 NAS 文件操作（Delete ≠ Undo）”*。事实上真实后端在删除 `BatchPlan` / `BatchPlanItem` 时，**严格持久化保留**了 `AuditEvent`、`WorkJob`、`ScanJob` 与 NAS 真实物理文件。原错误文案会让用户误以为审计流水也会被抹除，违反了破坏性操作真实性原则。
- **RED 阶段**：
  在 `frontend/tests/plan_cleanup.test.ts` 中针对执行过的计划确认文案增加断言，验证不得包含“清理计划记录与审计流水”，且必须包含“Audit 审计记录仍会保留”。在 fixed8 基线代码下测试失败，复现原实现缺陷。
- **GREEN 阶段**：
  在 `frontend/src/components/plans/plan_cleanup.ts` 抽离纯函数 `getPlanDeleteConfirmationContent(plan)`，并由 `PlanDeleteButton.tsx` 统一消费：
  - **已执行计划（`partial`, `completed`, `failed`）**：
    `该计划可能包含已经执行过的文件操作。删除仅清理计划及计划条目元数据，不会撤销已经执行的 NAS 文件操作（Delete ≠ Undo）。Audit 审计记录仍会保留。`
  - **未执行计划（`draft`, `frozen`, `ready`）**：
    `仅删除该计划及其计划条目元数据，不会修改 NAS 上的任何真实文件。Audit 审计记录不会受到影响。`

---

### Problem B: 旧版计划清理受影响扫描语义失真（affected_scan_count Semantic Mismatch）
- **根因与失真点（为什么 affected != unlocked）**：
  后端接口 `GET /api/plans/legacy/summary` 与 `POST /api/plans/legacy/clear` 返回的 `affected_scan_count` 字段真实语义为：*“有多少 Scan 曾被 legacy Plan 引用关联”*，而不是*“清理后一定有多少 Scan 可以直接删除”*。若某一扫描同时关联了当前的 `BatchPlan`，在清理旧版计划后，由于 `BatchPlan` 依赖仍然存在，该扫描仍然处于被锁状态（`has_dependent_plan=true`）。原 UI 文案“已清理 N 个旧版兼容计划，解锁 K 个扫描记录”与“清理后可安全恢复扫描记录的删除权限”存在误导。
- **RED 阶段**：
  在 `frontend/tests/legacy_plan_cleanup.test.ts` 中断言清理成功提示与横幅文案：不得包含“解锁 N 个扫描”，必须说明仅移除旧版依赖，并明确指出若仍存在当前批处理计划关联，删除限制仍会继续保留。在原实现下断言失败，复现缺陷。
- **GREEN 阶段**：
  在 `plan_cleanup.ts` 中实现格式化纯函数并在 `LegacyPlanCleanup.tsx` 中应用：
  - **成功消息**：`已清理 ${res.deleted_count} 个旧版计划，并移除 ${res.affected_scan_count} 个扫描记录上的旧版计划依赖（若仍关联当前批处理计划，删除限制将继续保留）。`
  - **横幅说明**：`发现 ${summary.plan_count} 个旧版计划，包含 ${summary.item_count} 个旧版计划项，涉及 ${summary.affected_scan_count} 个扫描记录。这些记录已不参与当前 Plan 执行链路，但仍可能作为旧版依赖阻止关联扫描记录删除。清理后会移除 legacy Plan / PlanItem 元数据；如果扫描仍关联当前 BatchPlan，其删除限制仍会继续保留。`
  - **二次确认说明**：`该操作仅删除旧版 Plan / PlanItem 元数据。不会删除当前 BatchPlan / BatchPlanItem、Scan 记录、Task / WorkJob、Audit 审计记录或 NAS 上的真实文件。清理后会移除 legacy Plan 对 Scan 的依赖；如果 Scan 仍关联当前 BatchPlan，其删除限制不会解除。`

---

### Problem C: Plan Delete 失败后的陈旧状态滞留（409 Stale-State UX Bug）
- **根因与陈旧状态表现**：
  当用户端缓存计划为 `ready` 状态并显示 `[删除]` 按钮时，如果后台或其他操作将该计划转为 `executing`，用户点击删除触发 `DELETE /api/plans/{id}`，后端正确返回 `409 Conflict`。此前前端的 `onError` 仅弹窗报错 `message.error()`，未主动使前端缓存失效，导致 UI 仍维持 `ready` 和可点击的 `[删除]` 按钮，形成陈旧操作态（Stale Capability）。
- **RED 阶段**：
  编写测试验证 `invalidatePlanDeleteFailure(queryClient, planId)` 是否正确对 `plansList` 和 `planDetail` 触发缓存失效。在未引入统一失效机制前，断言失败。
- **GREEN 阶段**：
  实现统一失效机制 `invalidatePlanDeleteFailure(queryClient, planId)`：
  - 当删除遇到任何错误（400、403、404、409、500 或网络错误）时：
    1. 提示真实错误信息；
    2. 主动调用 `queryClient.invalidateQueries({ queryKey: ['plansList'] })`；
    3. 主动调用 `queryClient.invalidateQueries({ queryKey: ['planDetail', planId] })` 与 `['planDetail']`；
  - 列表与详情页重新自后端获取真实状态（例如转为 `executing` 后，删除按钮自动变为禁用并展示“计划正在校验或执行中，禁止删除”；若遇 404 则平滑呈现不存在提示），彻底消除前端陈旧态。
  - 在 `PlanDeleteButton.tsx`、`Plans/index.tsx` 以及 `Plans/PlanDetail.tsx` 全链路集成。

---

### PlanHistoryCleanupModal 细化修正
- 修复 `PlanHistoryCleanupModal.tsx` 说明中“BatchPlan 及 PlanItem”的不严谨表述，修正为真实数据对象：**“BatchPlan 及 BatchPlanItem”**。
- 继续保持：Audit 保留、NAS 文件不删除、Delete ≠ Undo 原则不变。

---

## 3. 测试矩阵与自动化回归验证

### 1. 前端测试（Node Test Runner）
- 扩展测试：
  - `frontend/tests/plan_cleanup.test.ts`：增加真实确认文案断言与失败缓存失效断言；
  - `frontend/tests/legacy_plan_cleanup.test.ts`：增加旧版计划清理真实性语义断言（移除虚假解锁描述）。
- **执行结果**：
  ```text
  # tests 98
  # suites 30
  # pass 98
  # fail 0
  ```
  **98 / 98 passed**（相比 fixed8 的 92 tests 净增 6 个，零失败）。
- **TypeScript 类型检查**：`npm run typecheck` 退出码 0，**0 错误**。
- **生产打包构建**：`npm run build` 成功完成，耗时 3.69s。

### 2. 后端全量测试（Pytest）
- 运行环境：遵循 Rule 62（`-v "$PWD":/src:ro -w /tmp/project`），完全只读挂载并在容器内部副本运行。
- **执行结果**：
  ```text
  ======================= 283 passed, 4 warnings in 38.62s =======================
  ```
  **283 / 283 passed**（零失败、零回归）。

### 3. Docker 镜像与容器冒烟验证
- **镜像构建**：`docker build -t kerwinjhc/nas-file-center:0.3.3-step2-fixed8-hotfix1 .` 成功。
- **容器冒烟测试**：
  - `/health` 返回 200 OK；
  - 未认证访问 `/api/plans`、`/api/plans/legacy/summary`、`/api/plans/clear-history` 均严格返回 401 Unauthorized。

---

## 4. 干净发布包验证与 Release Decision

- **干净归档**：使用 `git archive` 打包，彻底排除 `.git`、`node_modules`、缓存与临时数据库。
- **解压独立验证**：在 `/tmp/verify_clean_step2_fixed8_hotfix1` 进行解压后独立验证：
  - `npm ci && npm test && npm run typecheck && npm run build` 100% 通过；
  - Docker 全量测试 `283 / 283 passed` 100% 通过。
- **Release Decision**：**PASS / APPROVED**。
