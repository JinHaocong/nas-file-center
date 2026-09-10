# Gate5-E / E4-hotfix4 Walkthrough: Enforce Safe Quarantine Root Binding in Crash Reconciliation

## 1. 任务背景与唯一授权基线

本任务为 NAS File Center Gate5-E / E4 阶段的受限安全修复（Bounded Safety Fix）**hotfix4**。
无新的 Architecture Amendment，沿用所有者批准的权威 `docs/history/gate5e/gate5e-e4-hotfix2-architecture-freeze-amendment.md`。

- **远程仓库**：`https://github.com/JinHaocong/nas-file-center`
- **目标分支**：`v0.3.5-gate5c-hotfix4`
- **起始授权基线 HEAD (`BASE_HEAD`)**：`ff0b5d9bf21f9aa4bf355ec4c089817bf8f0c036`
- **权威 Amendment 提交**：`9d8bfc2d8cee562ba2edec0b956fb89a502c5a40`

---

## 2. 独立审查发现与修复方案

### Independent Review BLOCKER
- **缺陷表现**：
  在 `app/tasks/handlers.py::_reconcile_executing_item()` 的 `rmdir_empty` 崩溃对账逻辑中，State A/B/C 分类阶段仍通过路径名直接检查确定性隔离区目标：
  ```python
  os.path.lexists(q_target)
  q_target.is_symlink()
  q_target.stat(follow_symlinks=False)
  q_target.is_dir()
  ```
  只有在分类进入 State C 回滚时才调用了 `acquire_safe_quarantine_root_fd(...)`。
  因此，如果配置的 `QUARANTINE_ROOT` 叶子本身是符号链接（symlink alias），而该链接指向的真实隔离区目录中存在确定性 `q_name` 且物理身份与 Frozen X 一致，对账逻辑会直接通过路径解引用判定存在，错误进入 `State B -> completed` 并生成成功的 `OperationJournal`，完全绕过了现行 Freeze 关于隔离区根目录必须为真目录、叶子不得为软链接、必须绑定文件描述符物理身份并 fail-closed 的强契约。

- **修复方案**：
  1. `rmdir_empty` 崩溃对账在观察任何隔离区目标之前，必须首先调用：
     ```python
     q_root_fd, q_root_path, q_root_stat = acquire_safe_quarantine_root_fd(settings.quarantine_root)
     ```
     若获取失败（软链接、非目录、无法安全打开），立即 fail-closed：
     - `item.state = "failed"`，记录 conflict 原因；
     - 严禁标记 completed，严禁生成 OperationJournal，严禁进行任何变更。
  2. 使用 `with contextlib.ExitStack()` 确保 `q_root_fd` 始终可靠关闭。
  3. State A/B/C/D/E 对确定性隔离区目标的检查全面改为基于文件描述符的相对查询：
     ```python
     st_q = os.stat(q_name, dir_fd=q_root_fd, follow_symlinks=False)
     ```
     通过 `stat.S_ISDIR(st_q.st_mode)` 与 `not stat.S_ISLNK(st_q.st_mode)` 以及 `st_q.st_dev / st_q.st_ino` 判定其物理身份。完全废除路径名 `os.path.lexists(q_target)`、`q_target.stat(...)` 等非锚定检查。
  4. State C 回滚直接复用已安全绑定的 `q_root_fd`，配合 `safe_open_parent_fd(src, allowed_roots)` 与 `rename_noreplace_at` 执行安全无覆写回滚；若父目录或祖先存在任何风险则保留在隔离区并标记 conflict。

---

## 3. 严格 TDD 提交历程

开发全程严格遵循 TDD（RED -> GREEN -> 5 级回归 -> Commit -> Push）：

| 阶段 | Commit Hash | 提交信息 | 核心说明 |
| :--- | :--- | :--- | :--- |
| **RED Regression** | `fd18b37` | `test(gate5e): reproduce quarantine root symlink bypass during reconciliation` | 新增回归用例 `test_reconcile_rmdir_empty_quarantine_root_symlink_fails_closed`，在旧基线上稳定触发 `AssertionError: assert 'completed' != 'completed'` |
| **Minimal Fix** | `30a5e4d` | `fix(gate5e): enforce safe quarantine root binding in rmdir_empty crash reconciliation` | 实施最小安全修复，前置绑定 `q_root_fd`，全状态基于描述符判断，RED 测试转为 GREEN |

---

## 4. 5 级全量回归测试套件验证结果

所有测试均在真实 Linux Docker 容器环境（`nas-test-env:latest`, Python 3.12.14）中独立完整运行：

### Level 1: hotfix2 / hotfix3 / hotfix4 专项测试
```text
docker run --rm -e PYTHONPATH=. -v "$(pwd)":/app -w /app nas-test-env:latest pytest tests/test_gate5e_e4_hotfix2.py -v
============================== 29 passed in 2.65s ==============================
```

### Level 2: 全部 E4 套件
```text
docker run --rm -e PYTHONPATH=. -v "$(pwd)":/app -w /app nas-test-env:latest pytest tests/test_gate5e_e4_*.py
====================== 110 passed, 2 warnings in 9.07s =======================
```

### Level 3: Gate5-E 全阶段套件 (E1 + E2 + E3 + E4)
```text
docker run --rm -e PYTHONPATH=. -v "$(pwd)":/app -w /app nas-test-env:latest pytest tests/test_gate5e_e1_*.py tests/test_gate5e_e2_*.py tests/test_gate5e_e3_*.py tests/test_gate5e_e4_*.py
====================== 292 passed, 2 warnings in 15.87s ======================
```

### Level 4: 核心架构回归套件
```text
docker run --rm -e PYTHONPATH=. -v "$(pwd)":/app -w /app nas-test-env:latest pytest tests/test_planning.py tests/test_gate3*.py tests/test_execution.py tests/test_gate2_hotfix2_undo_algebra.py tests/test_gate2_hotfix4_reconciliation_evidence.py
======================= 66 passed, 2 warnings in 5.54s =======================
```

### Level 5: 全量回归测试 (Entire Test Suite)
```text
docker run --rm -e PYTHONPATH=. -v "$(pwd)":/app -w /app nas-test-env:latest pytest tests/
==================== 1109 passed, 18 warnings in 104.71s (0:01:44) ====================
```

### 静态生产代码与工作区安全检查
- `git diff --check`: clean (0 issues)
- `git status --short`: clean

---

## 5. 严格零范围发散（Zero Scope Drift）

- **零数据库迁移**：无任何 Alembic 迁移脚本或数据库 schema 变动。
- **零前端改动**：无任何前端代码或接口调整。
- **零 Worker 协议重新设计**：完全复用现有状态与 Journal 协议。
- **零工作流变动**：无流程更改。
- **零 E1/E2/E3 语义变更**：完全保持向前兼容。
- **零 Gate5-F**：绝无后续 Gate 特性提前进入。
- **零破坏性系统调用**：无 `os.rmdir`、无 `os.unlink`、无 `shutil.rmtree`、无 `copy+delete`。
- **零非安全直接路径调用**：State A/B/C/D/E 隔离区判断全面基于 `dir_fd=q_root_fd`。

---

## 6. 状态声明（Strict Declaration）

```text
Gate5-E / E4-hotfix4 IMPLEMENTATION COMPLETE
READY FOR INDEPENDENT REVIEW
```
