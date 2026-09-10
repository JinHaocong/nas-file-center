# Gate5-E / E4-hotfix5 Walkthrough: Quarantined Directory Emptiness Verification in State B Reconciliation

## 1. 任务背景与唯一授权基线

本任务为 NAS File Center Gate5-E / E4 阶段的受限安全修复（Bounded Safety Fix）**hotfix5**。
无新的 Architecture Amendment，沿用所有者批准的权威 `docs/history/gate5e/gate5e-e4-hotfix2-architecture-freeze-amendment.md`。

- **远程仓库**：`https://github.com/JinHaocong/nas-file-center`
- **目标分支**：`v0.3.5-gate5c-hotfix4`
- **起始授权基线 HEAD (`BASE_HEAD`)**：`14fc5bd84318c095c407f5404939e271faee02f7`
- **权威 Amendment 提交**：`9d8bfc2d8cee562ba2edec0b956fb89a502c5a40`

---

## 2. 独立审查发现与修复方案

### Independent Review BLOCKER
- **缺陷表现**：
  在 `app/tasks/handlers.py::_reconcile_executing_item()` 的 `rmdir_empty` State B 对账逻辑中，当确定性隔离区目标存在且物理身份（`dev`, `ino`）等于 Frozen X 时，直接标记 `item.state = "completed"` 并生成 `OperationJournal`，但从未重新确认该隔离区目录内部**是否依然为空**。
- **并发与崩溃漏洞**：
  若目录在原子迁移入隔离区后、执行完成前的微小窗口内发生崩溃，且该目录在此期间被并发句柄或外部写入了子文件，对账时仅凭 `dev/inode == Frozen X` 就会误判为逻辑删除已成功，将包含数据的目录判定为已删除。
- **架构契约要求**：
  - 成功的逻辑删除必须同时满足两项物理证据：**物理身份与 Frozen X 一致** 且 **隔离区中的目录依然为空**。
  - 若在隔离区中观察到非空目录，必须执行 Outcome C：**绝对不得删除目录内部任何子文件**，尝试进行原子无覆写回滚（`rename_noreplace_at`）；若回滚受阻（原路径被占用），则将目录及全部内容完好保存在隔离区中，标记 `item = failed/conflict`。

### 修复方案
1. 在 `State B` 做出 `completed` 判定之前，利用已绑定的 `q_root_fd`，以 `os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW` 描述符安全打开隔离区目录对象：
   ```python
   target_fd = os.open(q_name, flags, dir_fd=q_root_fd)
   ```
2. 通过 `os.fstat(target_fd)` 校验其为真实目录且物理身份与 Frozen X 完全一致。
3. 通过 `os.listdir(target_fd)` 立即执行只读空状态探测，并在 `finally` 块中关闭 `target_fd`。
4. **Outcome A（State B 成功）**：仅在 `directory` + `dev/inode == Frozen X` + `is_empty == True` 时，标记 `completed` 并补录 Journal。
5. **Outcome C（非空冲突恢复）**：若 `dev/inode == Frozen X` 但目录非空（`is_empty == False`）：
   - 绝不标记成功，绝不补录完成 Journal；
   - 零子项删除，零递归清理；
   - 标记 `item.state = "failed"`，记录 `quarantined directory is non-empty` 冲突原因；
   - 若原源路径未被占用（`not src_exists`），通过 `safe_open_parent_fd(src, allowed_roots)` 锚定父目录，执行 `rename_noreplace_at(q_root_fd, q_name, src_parent_fd, leaf_name)` 将非空目录原样安全回滚回原路径（包含全部子文件）；
   - 若原路径已被占用（rollback collision），绝不覆盖占用者，将非空目录及其全部内容完好保存在隔离区。

---

## 3. 严格 TDD 提交历程

开发全程严格遵循 TDD 规范（RED -> GREEN -> 5 级回归 -> Commit -> Push）：

| 阶段 | Commit Hash | 提交信息 | 核心说明 |
| :--- | :--- | :--- | :--- |
| **RED Regressions** | `b91a2a7` | `test(gate5e): reproduce non-empty quarantined directory reconciliation race` | 增加非空隔离目录对账回滚及冲突用例，在旧基线上稳定触发 `AssertionError: assert 'completed' != 'completed'` |
| **Minimal Fix** | `b086ce7` | `fix(gate5e): verify emptiness before State B completion and rollback non-empty directory` | State B 前置描述符只读空状态校验，非空进入 Outcome C 安全回滚与隔离保护，两项 RED 测试全部转为 GREEN |

---

## 4. 5 级全量回归测试套件验证结果

所有测试均在真实 Linux Docker 容器环境（`nas-test-env:latest`, Python 3.12.14）中独立完整运行：

### Level 1: hotfix2 / hotfix3 / hotfix4 / hotfix5 专项测试
```text
docker run --rm -e PYTHONPATH=. -v "$(pwd)":/app -w /app nas-test-env:latest pytest tests/test_gate5e_e4_hotfix2.py -v
============================== 31 passed in 1.08s ==============================
```

### Level 2: 全部 E4 套件
```text
docker run --rm -e PYTHONPATH=. -v "$(pwd)":/app -w /app nas-test-env:latest pytest tests/test_gate5e_e4_*.py
====================== 112 passed, 2 warnings in 3.75s =======================
```

### Level 3: Gate5-E 全阶段套件 (E1 + E2 + E3 + E4)
```text
docker run --rm -e PYTHONPATH=. -v "$(pwd)":/app -w /app nas-test-env:latest pytest tests/test_gate5e_e1_*.py tests/test_gate5e_e2_*.py tests/test_gate5e_e3_*.py tests/test_gate5e_e4_*.py
====================== 294 passed, 2 warnings in 13.83s ======================
```

### Level 4: 核心架构回归套件
```text
docker run --rm -e PYTHONPATH=. -v "$(pwd)":/app -w /app nas-test-env:latest pytest tests/test_planning.py tests/test_gate3*.py tests/test_execution.py tests/test_gate2_hotfix2_undo_algebra.py tests/test_gate2_hotfix4_reconciliation_evidence.py
======================= 66 passed, 2 warnings in 5.45s =======================
```

### Level 5: 全量回归测试 (Entire Test Suite)
```text
docker run --rm -e PYTHONPATH=. -v "$(pwd)":/app -w /app nas-test-env:latest pytest tests/
==================== 1111 passed, 18 warnings in 100.09s (0:01:40) ====================
```

### 静态代码与工作区安全检查
- `git diff --check`: clean (0 issues)
- `git status --short`: clean

---

## 5. 严格零范围发散保证（Zero Scope Drift）

- **零数据库迁移**：无任何 Alembic 迁移脚本或数据库表结构变动。
- **零前端改动**：无任何前端代码或接口变更。
- **零 Worker 协议重构**：完全复用现有状态与 Journal 契约。
- **零工作流变动**：无流程更改。
- **零 E1/E2/E3 语义变更**：完全保持向前兼容。
- **零 Gate5-F**：绝无任何后续特性提前引入。
- **零破坏性系统调用**：无 `os.rmdir`、无 `os.unlink`、无 `shutil.rmtree`、无 `copy+delete`。
- **零子项破坏**：非空隔离区目录中的所有文件 100% 完好保留，绝不物理清理。

---

## 6. 状态声明（Strict Declaration）

```text
Gate5-E / E4-hotfix5 IMPLEMENTATION COMPLETE
READY FOR INDEPENDENT REVIEW
```
