# NAS File Center v0.3.4 Gate4 — Implementation & Acceptance Walkthrough

## 1. Scope (本次范围)
- **核心目标**: 全面交付 NAS File Center v0.3.4 Gate4 全部功能组件与前后端安全闭环：
  1. **Quarantine UI (隔离区页面与列表)**: 服务端分页、状态筛选（active/restored/purged/inconsistent/abandoned/skipped）、原路径与隔离路径模糊搜索、元数据（大小、哈希、时间戳、关联计划）展示。
  2. **Restore UI (单项恢复弹窗)**: 单项安全恢复，支持三种冲突策略（`skip` 默认安全跳过、`rename` 自动重命名规避冲突、`manual` 自定义安全目标路径）。只读模式（`ALLOW_MUTATION=false`）强制禁用恢复操作。
  3. **Purge Guard UI (永久清除防误删弹窗)**: 仅管理员可见且可用，强制用户在输入框中完整键入全大写 `"DELETE"` 方可激活确认按钮。未开启永久删除（`ALLOW_DELETE=false`）时给予高危封锁警告并禁止操作。
  4. **Retention Policy UI (保留策略配置)**: 在系统设置页面展示隔离区保留周期选项（0天不保留 / 7天 / 30天 / 90天），展示当前状态与过期时间计算规则。服务端严格持久化，**绝不启动后台静默自动删除线程**，过期数据仅供管理员人工预览与强确认清除。
  5. **Operation Journal UI (底层操作日志抽屉)**: 计划详情页抽屉展示底层物理变更 Before / After 严格对照（文件路径、大小、时间戳 `mtime_ns`、`inode`），支持展开查看原始 JSON，便于排查与审计。
  6. **Undo Plan UI & Flow (撤销计划完整生命周期与自反性)**: 针对已完成或部分完成的计划，提供“生成撤销计划”功能。生成的 Undo 计划为标准 `BatchPlan`（`kind="undo"`），包含对源计划的引用元数据；在 UI 上显示专属源计划 Alert 导流条并支持一键跳转；严格遵循 `Draft -> Freeze -> Validate -> Execute` 生命周期，绝不允许直接原地执行；支持对 Undo 计划再次生成 Undo 计划（自反撤销），源计划拓扑关系清晰追踪。
- **用户裁定的 3 个核心决策**:
  - **决策 1**: 初版只提供单项恢复 / 单项清除，不做批量恢复 / 批量清理。
  - **决策 2**: 隔离区保留策略只保存 `expires_at` 和配置，绝不启动后台静默自动删除线程；后续清理只能由管理员人工预览 + 强确认触发。
  - **决策 3**: 允许对 Undo 计划再次生成 Undo 计划（自反性）；所有 Undo 计划必须走 `Draft -> Freeze -> Validate -> Execute`，严禁直接原地执行。
- **范围红线**: 
  - 严禁进入 v0.3.5、Workflow、Scheduler、Media Similarity、MUI v9 迁移。
  - 严禁引入 Redis、RabbitMQ、Celery、PostgreSQL、公网 CDN。
  - 严格保持 0 数据库 Schema 变更（0 DB schema change, 0 Alembic migration）。
  - 严禁执行 `git push`、`git tag`、`docker push`。
  - 最终状态声明保持：`Gate4 implementation candidate ready for independent review`。

---

## 2. Technical Implementation Details (技术实现要点)

### 2.1 后端字段微调与服务层适配
- **零 Schema 变更**: 在 `app/service.py` 的 `plan_detail` 字典返回中补充 `"metadata": json.loads(plan.metadata_json or "{}")`，确保前端与 API 客户端能够直接读取 `is_undo`、`undo_of_plan_id`、`created_by_user_id` 等扩展字段，无需任何数据库迁移。
- **撤销计划反转语义与自反性**: `create_undo_plan` 根据 `OperationJournal` 倒序逆转操作，对于 `quarantine` 操作生成 `restore` 逆向操作，对于 `restore` 操作生成 `quarantine` 逆向操作，对于 `rename`/`move` 调换源目标路径，对于 `touch` 恢复原始 `mtime_ns`。生成的 Undo Plan 写入 `metadata.undo_of_plan_id`，为自反撤销提供完整的因果链追踪。

### 2.2 前端架构与组件封装
1. **类型定义 (`frontend/src/types/`)**:
   - `quarantine.ts`: 严格定义 `QuarantineEntry`、`QuarantineListResponse`、`QuarantineRestoreRequest`、`QuarantinePurgeRequest`、`QuarantineRetentionPolicy` 等接口。
   - `journal.ts`: 严格定义 `OperationJournalEntry`、`OperationJournalListResponse`、`UndoPlanResponse`。
2. **API 客户端 (`frontend/src/api/quarantine.ts`, `domain.ts`)**:
   - `quarantineApi`: `list`、`get`、`restore`、`purge`、`getRetentionPolicy`、`updateRetentionPolicy`。
   - `plansApi.createUndoPlan(planId)` & `plansApi.getOperationJournal(planId)`。
3. **页面与交互组件 (`frontend/src/pages/`)**:
   - `Quarantine/index.tsx`: 具备分页、状态筛选（Tab / Select）、路径搜索框、刷新、单项恢复与清除按钮。
   - `Quarantine/RestoreModal.tsx`: 冲突策略选择（`skip` 默认 / `rename` / `manual`），只读保护禁用提示，自定义路径输入与校验。
   - `Quarantine/PurgeConfirmModal.tsx`: 永久删除强确认，提示危险性，仅全大写 `"DELETE"` 激活按钮，`ALLOW_DELETE=false` 时阻断。
   - `Settings/index.tsx`: 保留策略下拉卡片（0/7/30/90天），实时更新生效状态，标明无后台线程的安全说明。
   - `Plans/PlanDetail.tsx`: 顶部 Undo 专属 Alert Banner（标注源计划并提供回跳链接），“操作日志”抽屉入口按钮，“生成撤销计划 (Undo)”按钮及二次确认弹窗。
   - `Plans/OperationJournalDrawer.tsx`: 抽屉按执行时序展示物理变更 Before / After 对照表，支持展开查看原始 JSON。
   - `components/Sidebar.tsx` & `router/index.tsx`: 挂载 `/quarantine` 页面与导航菜单。

---

## 3. Automated Test Verification (自动化测试结果)

### 3.1 后端全量测试 (495 passed, 100% PASS)
- 命令: `docker run --rm -e PYTHONPATH=/app -v "$(pwd)":/app -w /app nas-test-env:latest pytest -q`
- 结果: **495 passed, 0 failed in 59.8s (100% PASS)**
- 新增专项后端测试: `tests/test_gate4_backend_quarantine_undo.py` (6 tests 全部通过):
  - `test_restore_conflict_policy_skip`: 目标存在时 `skip` 返回 skipped，保护源与目标文件 0 破坏。
  - `test_restore_conflict_policy_rename`: 目标存在时 `rename` 自动生成 non-colliding 新路径，原文件与恢复文件共存。
  - `test_restore_conflict_policy_manual`: 目标存在时 manual 阻断报错；提供合法 custom_target 成功恢复至指定位置。
  - `test_purge_guard_rules`: 普通用户 403 拒绝；错误确认词 400 拒绝；`ALLOW_DELETE=false` 400 拒绝；管理员 + "DELETE" + `ALLOW_DELETE=true` 成功彻底物理删除。
  - `test_create_undo_plan_invalid_states_and_empty_journal`: Draft/Pending/未执行计划拒绝创建撤销；0 journal 项计划拒绝。
  - `test_undo_plan_full_lifecycle_and_reflexivity`: 原计划执行 -> 生成 Undo Plan (Draft) -> 严禁直接执行 -> Freeze -> Validate -> Execute -> 成功物理复原；对 Undo 计划生成自反 Undo 计划 -> 执行成功重新应用变更。

### 3.2 前端全量测试 (171 passed / 51 suites, 100% PASS)
- 命令: `cd frontend && npm test -- --run`
- 结果: **171 passed, 51 suites, 0 failed (100% PASS)**
- 新增专项前端测试: `frontend/tests/gate4_quarantine_undo.test.ts` (12 tests 全部通过):
  - 覆盖 Undo Plan 按钮可用性逻辑矩阵。
  - 覆盖 Purge Guard 权限与确认词验证逻辑。
  - 覆盖 Restore 冲突策略默认值与有效性校验。
  - 覆盖保留策略合法枚举值与天数推导计算。

### 3.3 前端静态检查与生产构建
- 命令: `cd frontend && npm run typecheck && npm run build`
- 结果:
  - `tsc --noEmit`: **0 errors**
  - `vite build`: **Success (3.35s)**, 生成完整的 `dist/` 本地静态资源，无任何外部 CDN 引用。

### 3.4 Docker 生产镜像构建
- 命令: `docker build --platform linux/amd64 -t nas-file-center:v0.3.4-gate4 .`
- 结果: **Successfully built and tagged `nas-file-center:v0.3.4-gate4`** (Manifest sha256 exported)。

---

## 4. Native Docker NAS Blackbox Acceptance (黑盒环境端到端验收)
运行测试脚本 `scratch/test_gate4_nas_blackbox_acceptance.py`，在纯隔离 Docker named volumes (`nas_gate4_accept_config`, `nas_gate4_accept_data`) 上启动独立 API 与 Worker 容器，模拟真实 NAS 部署运行：

| 检查点 | 验证项目 | 验收结果 | 核心断言与安全表现 |
| :--- | :--- | :---: | :--- |
| **CP 1** | React SPA 本地加载与 No-CDN 规范 | **PASS** | HTML 本地加载成功，0 cdn.jsdelivr / unpkg / cloudflare 引用 |
| **CP 2** | Worker 容器心跳与状态健康 | **PASS** | Worker 状态为 online，心跳活跃，租赁锁正常持有 |
| **CP 3** | 计划执行与文件入隔离区 | **PASS** | Worker 成功执行隔离操作，源文件移入 `.nas-file-center-trash` |
| **CP 4** | Quarantine 列表与详情 API 契约 | **PASS** | `/api/quarantine` 正确返回 active 项与完整元数据 |
| **CP 5** | Restore 冲突策略 `skip` 安全防覆盖 | **PASS** | 目标已存在时返回 `skipped`，现有文件与隔离文件均 100% 保持完好 |
| **CP 6** | Restore 冲突策略 `rename` 自动避让 | **PASS** | 目标已存在时生成 `stem.restored-1.suffix`，原文件未被覆盖，内容完全吻合 |
| **CP 7** | Restore 冲突策略 `manual` 自定义恢复 | **PASS** | 成功将隔离项恢复至自定义合法目录路径 |
| **CP 8** | Purge Guard 权限与全词强确认 | **PASS** | 普通用户 403；小写或错误词 400；输入全大写 `DELETE` 后物理删除并转 `purged` |
| **CP 9** | Retention Policy 保存且无后台偷跑线程 | **PASS** | 成功更新配置，Task 队列中 0 后台自动删除常驻任务 |
| **CP 10** | Operation Journal 底层物理变更记录 | **PASS** | 记录详细 before/after（包含路径、mtime_ns、大小），供前端抽屉渲染 |
| **CP 11** | Undo Plan 严格生命周期流转与物理还原 | **PASS** | 生成 Draft -> 直接执行被 409 拦截 -> Freeze -> Validate -> Execute 成功复原源文件 |
| **CP 12** | Reflexive Undo Plan 自反撤销因果链 | **PASS** | 对已执行 Undo Plan 再次生成 Undo Plan，成功反向执行且源计划引用链完整 |
| **CP 13** | SQLite 数据库物理完整性检查 | **PASS** | `PRAGMA integrity_check;` 返回 `ok` |
| **CP 14** | 零数据损坏与零意外变更 | **PASS** | 全流程无非预期文件损坏或未受控变更 |

---

## 5. Artifact & Provenance (交付工件与溯源信息)
- **Git HEAD Commit**: `5c738631303ec3bd027a25980b6bad2535fa9648`
- **Release Package**: `nas-file-center-v0.3.4-gate4.zip`
- **ZIP Comment**: `5c738631303ec3bd027a25980b6bad2535fa9648`
- **Release SHA256**: `5c3b6cb7756dfb725d94fba6c7f1f1d5ec1e0a0f90bf64b24d50f382e173152b`

## 6. Current Status (当前状态)
```text
Gate2 = PASS
Gate3 = PASS
Gate4 implementation candidate ready for independent review
v0.3.5 = FORBIDDEN
```
