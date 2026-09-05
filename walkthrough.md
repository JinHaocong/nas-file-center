# NAS File Center v0.3.4 Gate4-hotfix1 — Implementation & Acceptance Walkthrough

## 1. Scope (本次范围)
- **核心目标**: 针对 Gate4 independent review 发现的 4 项工程质量、数据安全与前后端契约缺陷进行精确修复，完成全量自动化测试验证与发布包交付：
  1. **Purge 确认词严格恒等验证**: 前端 `PurgeConfirmModal` 与 `quarantine_rules.ts` 彻底移除 `trim()`，严格执行 `confirmInput === 'DELETE'`；将用户实际输入的 `confirmInput` 提交至后端，杜绝空白字符污染或误删。
  2. **Quarantine 列表搜索参数前后端对齐**: 前端 `quarantineApi.list` 规范化为向后端传递 `query` 参数；后端 `list_quarantine` 接口保持双向兼容（同时接收 `query` 与 `search`，`effective_query = query if query is not None else search`），确保 UI 搜索即时有效。
  3. **Undo Plan 生成前置状态硬约束**: 后端 `create_undo_plan` 显式强制限制 `plan.status in {"completed", "partial"}`，对 `draft`、`pending`、`ready`、`running`、`failed`、`cancelled`、`stale` 等非法状态统一拒绝并抛出 `StateConflictError` (HTTP 409)，封堵非终态计划生成 Undo 漏洞。
  4. **Release Provenance 规范化**: 消除压缩包内部自引用 SHA256 哈希冲突，文案采用标准声明：`Release SHA256: See external SHA256SUMS.txt generated after archive creation.`，并在压缩包外由 `sha256sum` 统一输出。
- **范围红线**:
  - 严禁进入 v0.3.5、Workflow、Scheduler、Media Similarity、MUI v9 迁移。
  - 严禁修改 Gate2 / Gate3 核心安全链路（PathGuard、Stale Validation、Final Fence、Worker Fencing）。
  - 严格保持 0 数据库 Schema 变更（0 DB schema change, 0 Alembic migration）。
  - 严禁执行 `git push`、`git tag`、`docker push`。
  - 最终状态声明保持：`Gate4-hotfix1 implementation candidate ready for independent review`，Gate4 保持 HOLD，严禁宣布 Gate4 PASS。

---

## 2. Technical Implementation Details (技术实现要点)

### 2.1 Purge 确认词精确校验与真实提交 (Hotfix 1)
- `frontend/src/components/quarantine/quarantine_rules.ts`:
  移除 `confirmationInput.trim() !== 'DELETE'` 中的 `trim()`，改为严格恒等 `confirmationInput !== 'DELETE'`。
- `frontend/src/pages/Quarantine/PurgeConfirmModal.tsx`:
  移除 `confirmInput.trim()` 校验，改为 `confirmInput === 'DELETE'` 控制按钮激活与提交前置校验；请求载荷由硬编码 `{ confirmation: 'DELETE' }` 改为提交原始输入 `{ confirmation: confirmInput }`。
- 测试覆盖：增加针对 `DELETE `、` DELETE`、`  DELETE  `、`DELETE\n`、`DELETE\t` 等尾随/前置空白字符的阻断断言，确保全链路 fail-closed。

### 2.2 Quarantine 搜索参数前后端对齐 (Hotfix 2)
- `app/api/router.py`:
  `list_quarantine` 新增参数 `search: str | None = Query(default=None)`，并通过 `effective_query = query if query is not None else search` 兼容前端传参。
- `frontend/src/api/quarantine.ts`:
  `quarantineApi.list` 接口入参支持 `query?: string; search?: string`，URL 查询参数统一组装为 `query`。
- `frontend/src/pages/Quarantine/index.tsx`:
  调用 `quarantineApi.list` 显式传入 `query: activeSearch`。

### 2.3 create_undo_plan 状态硬约束 (Hotfix 3)
- `app/service.py`:
  在 `create_undo_plan` 获取到 `plan` 后，立即校验：
  ```python
  if plan.status not in {"completed", "partial"}:
      raise StateConflictError(
          f"Cannot create undo plan: plan #{plan_id} status is '{plan.status}', must be 'completed' or 'partial'"
      )
  ```
- 异常映射：FastAPI 统一将其转换为 HTTP 409 Conflict。
- 测试覆盖：参数化验证全部非法状态（`draft`, `pending`, `ready`, `running`, `failed`, `cancelled`, `stale`）即使存在历史 journal 也必须返回 409。当状态合法为 `completed`/`partial` 且 journal 为空时返回 400。

### 2.4 文档自引用哈希修正 (Hotfix 4)
- 修正 `walkthrough.md` 与 Release Provenance 记录，彻底消除在 ZIP 内部写入自身未来 SHA256 哈希引发的不一致问题。

---

## 3. Automated Test Verification (自动化测试结果)

### 3.1 后端全量测试 (496 passed, 100% PASS)
- 命令: `docker run --rm -e PYTHONPATH=/app -v "$(pwd)":/app -w /app nas-test-env:latest pytest -q`
- 结果: **496 passed, 0 failed in 60.1s (100% PASS)**
- 专项测试集验证:
  - `tests/test_gate4_backend_quarantine_undo.py`: 7 passed
  - `tests/test_gate2_*.py`: 55 passed
  - `tests/test_gate3_stale_plan.py` & `tests/test_organizer_blockers_regression.py`: 60 passed
  - `tests/test_quarantine_*.py`: 52 passed

### 3.2 前端全量测试 (171 passed / 51 suites, 100% PASS)
- 命令: `cd frontend && npm test -- --run`
- 结果: **171 passed, 51 suites, 0 failed (100% PASS)**
- 专项前端测试: `frontend/tests/gate4_quarantine_undo.test.ts`
  - 覆盖 Purge Guard 针对 `DELETE `、` DELETE`、`DELETE\n` 等非精确输入的严格拒绝。
  - 覆盖 Quarantine 列表 `query` 与 `search` 参数组装。

### 3.3 前端静态检查与生产构建
- 命令: `cd frontend && npm run typecheck && npm run build`
- 结果:
  - `tsc --noEmit`: **0 errors**
  - `vite build`: **Success (3.91s)**, 生成完整本地静态文件，零外部 CDN 引用。

---

## 4. Native Docker NAS Blackbox Acceptance (黑盒环境端到端验收)

运行黑盒验证套件，在隔离 Docker named volumes 上执行真实 NAS 环境端到端验收：

| 检查点 | 验证项目 | 验收结果 | 核心断言与安全表现 |
| :--- | :--- | :---: | :--- |
| **CP 1** | React SPA 本地加载与 No-CDN 规范 | **PASS** | HTML 本地加载成功，0 cdn.jsdelivr / unpkg / cloudflare 引用 |
| **CP 2** | Worker 容器心跳与状态健康 | **PASS** | Worker 状态为 online，心跳活跃，租赁锁正常持有 |
| **CP 3** | 计划执行与文件入隔离区 | **PASS** | Worker 成功执行隔离操作，源文件移入 `.nas-file-center-trash` |
| **CP 4** | Quarantine 列表检索兼容性 | **PASS** | 支持 `query` 与 `search` 参数搜索，返回准确项与元数据 |
| **CP 5** | Restore 冲突策略 `skip` 安全防覆盖 | **PASS** | 目标已存在时返回 `skipped`，现有文件与隔离文件均 100% 保持完好 |
| **CP 6** | Restore 冲突策略 `rename` 自动避让 | **PASS** | 目标已存在时生成 `stem.restored-1.suffix`，原文件未被覆盖 |
| **CP 7** | Restore 冲突策略 `manual` 自定义恢复 | **PASS** | 成功将隔离项恢复至自定义合法目录路径 |
| **CP 8** | Purge Guard 权限与全词强确认 | **PASS** | 拒绝非管理员；拒绝带空格等非严格输入；输入精确 `DELETE` 彻底物理删除 |
| **CP 9** | Retention Policy 保存且无后台偷跑线程 | **PASS** | 成功更新配置，Task 队列中 0 后台自动删除常驻任务 |
| **CP 10** | Operation Journal 底层物理变更记录 | **PASS** | 记录详细 before/after（包含路径、mtime_ns、大小），供前端抽屉渲染 |
| **CP 11** | Undo Plan 状态拦截与严格生命周期 | **PASS** | Draft 状态生成 Undo 被 409 拦截；完成计划生成 Undo 走 Draft->Freeze->Validate->Execute 物理还原 |
| **CP 12** | Reflexive Undo Plan 自反撤销因果链 | **PASS** | 对已执行 Undo Plan 再次生成 Undo Plan，成功反向执行且源计划引用链完整 |
| **CP 13** | SQLite 数据库物理完整性检查 | **PASS** | `PRAGMA integrity_check;` 返回 `ok` |
| **CP 14** | 零数据损坏与零意外变更 | **PASS** | 全流程无非预期文件损坏或未受控变更 |

---

## 5. Artifact & Provenance (交付工件与溯源信息)
- **Git HEAD Commit**: `<COMMIT_PLACEHOLDER>`
- **Release Package**: `nas-file-center-v0.3.4-gate4-hotfix1.zip`
- **ZIP Comment**: `<COMMIT_PLACEHOLDER>`
- **Release SHA256**: See external SHA256SUMS.txt generated after archive creation.

## 6. Current Status (当前状态)
```text
Gate2 = PASS
Gate3 = PASS
Gate4-hotfix1 implementation candidate ready for independent review
Gate4 remains HOLD
v0.3.5 remains FORBIDDEN
```
