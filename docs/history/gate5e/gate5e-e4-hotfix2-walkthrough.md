# Gate5-E / E4-hotfix2 Walkthrough: Quarantine-First Logical Removal

## 1. 任务背景与授权基线

本任务为 NAS File Center Gate5-E / E4 阶段的紧急架构修订 **hotfix2**（Quarantine-First Logical Removal）。

- **远程仓库**：`https://github.com/JinHaocong/nas-file-center`
- **目标分支**：`v0.3.5-gate5c-hotfix4`
- **起始授权基线 HEAD**：`73fc9ac7d3fc952da5593bd3b1024b712e992d49`（Independent Review Blocker 结论记录提交）
- **Amendment 冻结提交**：`9d8bfc242b5a59345c26b38c227db043e0fc1a9f`
- **实现依据**：
  1. `docs/history/gate5e/gate5e-e4-hotfix2-architecture-freeze-amendment.md`
  2. `Gate5-E / E4-hotfix2 Quarantine-First Logical Removal Implementation Plan`

### 核心契约转变：彻底解决 Final-Component Replacement Race
在 E4-hotfix1 中，尽管已通过祖先目录描述符链（`parent_fd` 与 `O_NOFOLLOW`）收窄了路径攻击面，但在调用 `os.rmdir(leaf, dir_fd=parent_fd)` 之前，即便刚刚完成 `os.stat` 校验，仍存在微小并发竞态窗口：若外部进程在此刻将目标目录替换为另一个目录，`os.rmdir` 仍会按名称误删该替换目录。

为彻底消除物理破坏性删除的语义漏洞，E4-hotfix2 架构修订案规定：
1. **全面废除物理删除**：生产执行路径中零 `os.rmdir`、零 `os.unlink`、零 `shutil.rmtree`、零 `copy+delete`、零 `EXDEV` 跨设备降级。
2. **原子无覆写隔离区迁移**：采用基于文件描述符的 `rename_noreplace_at`（Linux `renameat2(..., RENAME_NOREPLACE)`）将目标目录原子迁移至内部隔离区（`QUARANTINE_ROOT`）下的确定性命名目录。
3. **迁移后身份与空状态两阶段验证**：
   - 若迁移后的目录物理身份（`st_dev`, `st_ino`）与 Freeze 预期一致且为空，标记成功（Outcome A）；
   - 若遭遇并发替换或非空，立即执行无覆写原子回滚（rollback）；若原位置被占用导致回滚失败，完好保存在隔离区并记录冲突证据（Outcome B/C/D），**绝不物理销毁替换对象**。
4. **精确物理对象恢复（Restore Preserved Inode）**：Undo 逆向操作由原结构性 `mkdir_empty` 全面升级为 `restore_empty_dir`，通过反向原子迁移将隔离区中完好保存的原目录迁移回原路径，恢复相同 inode。

---

## 2. 生产代码修改边界（Zero Scope Drift）

严格遵循架构冻结与修订案边界，所有代码改动严格限制于 E4 相关模块，无越界修改：
- `app/fs_ops.py`: 新增基于文件描述符的原子无覆写重命名原语 `rename_noreplace_at`（Linux `renameat2` / Darwin `renameatx_np`），严格遵循 POSIX 错误码契约。
- `app/batch_utilities/empty_dir_quarantine.py` (新增模块): 实现确定性隔离区命名规则 `build_e4_quarantine_name` 与可恢复安全迁移/回滚引擎 `relocate_empty_dir_to_quarantine`。
- `app/execution/executor.py`: `rmdir_empty` 全面切入 `relocate_empty_dir_to_quarantine`，返回隔离区路径；新增内部执行原语 `restore_empty_dir`，实现原子反向迁移恢复。
- `app/service.py`: 
  - `freeze_plan`: 支持 `restore_empty_dir` 身份捕获，验证源在隔离区内且为目录；
  - `validate_plan`: 支持 `restore_empty_dir` 校验隔离区源的新鲜度、目标非存在性及嵌套恢复链式校验；
  - `create_undo_plan`: 成功完成的 `rmdir_empty` 生成 `restore_empty_dir`，浅优先（shallowest-first）逆序排列；保留旧无隔离区路径日志的 `mkdir_empty` 兼容分支；支持 `restore_empty_dir` 逆转为 `rmdir_empty`。
- `app/tasks/handlers.py`:
  - 运行时 `OperationJournal` 完整记录 `logical_removed=True`, `preserved=True`, `quarantine_path` 及隔离区快照；
  - 崩溃对账 `_reconcile_executing_item()` 全面实现确定性隔离区 State A~E 状态机以及 `restore_empty_dir` 崩溃恢复。

**严正确认**：
- 零 DB migration（完全复用现有表结构与 metadata 存储）。
- 零新 Worker 进程或协议变更。
- 零 E1/E2/E3 语义破坏或功能回退。
- 零目录 Purge 或定时物理清理逻辑引入。
- 零 Gate5-F 特性进入。
- 生产执行链路绝对无 `os.rmdir`、`os.unlink`、`shutil.rmtree`。

---

## 3. 核心机制详解

### 3.1 文件描述符级原子无覆写重命名（`rename_noreplace_at`）
在 `app/fs_ops.py` 中实现了底层原子重命名原语：
- Linux 环境通过 `ctypes` 调用 `libc.renameat2(source_dir_fd, source_name, target_dir_fd, target_name, RENAME_NOREPLACE)`（`RENAME_NOREPLACE = 1`）；
- macOS / Darwin 环境调用 `libc.renameatx_np(..., RENAME_EXCL)`；
- 严格遵循系统错误码：
  - 目标已存在时抛出 `FileExistsError`（`EEXIST` / `ENOTEMPTY`）；
  - 跨文件系统时抛出 `OSError(EXDEV)`，严禁且不提供降级 copy+delete 回退；
  - 源不存在时抛出 `FileNotFoundError`（`ENOENT`）。

### 3.2 确定性隔离区迁移与回滚引擎（`empty_dir_quarantine.py`）
- **确定性隔离区命名**：
  `.nfc-e4-p<plan_id>-s<sequence>-<sha256(source_path)[:16]>`
  该命名在同一 Plan 步骤下具有全局唯一且完全确定性的特点，为崩溃对账提供唯一权威依据。
- **两阶段安全迁移与回滚状态机**：
  1. 打开源父目录描述符 `parent_fd` 与隔离区根描述符 `quarantine_fd`（均使用 `O_RDONLY | O_DIRECTORY | O_NOFOLLOW`）；
  2. 调用 `rename_noreplace_at(parent_fd, leaf_name, quarantine_fd, quarantine_name)` 完成原子转移；
  3. 转移完成后立即在 `quarantine_fd` 内打开目标并执行 `fstat` 校验：
     - **Outcome A**：对象为真目录，物理身份（`dev`, `ino`）与 Freeze 预期完全吻合，且目录枚举为空 -> **成功完成**，返回 `quarantine_path`。
     - **Outcome B/C/D**：若发现非空、身份不符（竞争替换发生）或非目录：
       立即调用 `rename_noreplace_at(quarantine_fd, quarantine_name, parent_fd, leaf_name)` 进行**原子无覆写回滚**；
       - 若回滚成功：源目录恢复原状，返回 `failed`；
       - 若原位置已被第三方占用导致回滚遇到 `FileExistsError`：绝不覆盖占用者，将迁移对象安全保存在隔离区中，返回 `failed` 并附带冲突证据。

### 3.3 严格生命周期与精确 Inode 恢复（`restore_empty_dir`）
- **Freeze**：捕获隔离区源目录的当前物理身份（`device`, `inode`），写入 `expected_device`, `expected_inode`；
- **Validate**：校验隔离区源目录的新鲜度，验证目标路径在 `ALLOWED_ROOTS` 授权范围内、不位于隔离区、且尚未存在；支持嵌套目录的链式恢复（前序步骤恢复的父目录加入 `planned_mkdir_targets`，允许后续子目录校验通过）；
- **Execute**：仅要求 `ALLOW_MUTATION=True`（不需要 `ALLOW_DELETE`），通过文件描述符链将目录原子迁回目标位置，**恢复相同的 inode**。

### 3.4 崩溃对账状态机（Crash Reconciliation）
在 `app/tasks/handlers.py` 中实现了对账状态机：
- **State A**：源存在且为 Frozen X，隔离区目标不存在 -> 迁移未完成，退回 `planned` 可重试；
- **State B**：源不存在，隔离区目标存在且为 Frozen X -> 迁移已完成，标记 `completed` 并补录缺失的 OperationJournal（含 `quarantine_path`）；
- **State C**：隔离区目标存在但身份不是 Frozen X -> 误迁入竞态对象，安全尝试无覆写回滚，回滚受阻则保留在隔离区，标记 `failed` 冲突；
- **State D**：源 Frozen X 存在且隔离区目标也存在 -> 冲突状态，保持两者不动，标记 `failed`；
- **State E**：源与隔离区目标均不存在 -> 缺乏物理持久化证据，fail-closed 标记 `failed`，绝不虚构成功；
- **`restore_empty_dir` 对账**：隔离区源存在且目标无 -> 退回 `planned`；隔离区源无且目标存在为 Frozen X -> 标记 `completed` 并补录 Journal；两者皆在或身份冲突 -> 标记 `failed`。

---

## 4. TDD 提交历史与轨迹

本轮 hotfix2 开发严格遵循 TDD 规范（RED -> GREEN -> 回归验证 -> Commit -> Push），所有提交均已推送至远程工作分支 `v0.3.5-gate5c-hotfix4`：

| 任务 | Commit Hash | 提交类型与信息 | 核心改动说明 |
| :--- | :--- | :--- | :--- |
| **Amendment Freeze** | `9d8bfc2` | `docs(gate5e): record E4-hotfix2 architecture freeze amendment` | 正式固化所有者批准的 E4-hotfix2 架构修订案文档，建立权威基线 |
| **Task 1 (RED 复现)** | `0a3afb8` | `test(gate5e): reproduce E4 final-component replacement race` | 在旧代码上编写 final-component replacement 竞争用例，确认误删目录稳定抛出 AssertionError |
| **Task 2 (FD 原子重命名)** | `a641c63` | `feat(fs): add fd-relative atomic no-replace rename` | 在 `app/fs_ops.py` 实现 `rename_noreplace_at`（Linux `renameat2` / Darwin `renameatx_np`），通过单元测试 |
| **Task 3 (隔离区迁移引擎)** | `e5db5a2` | `feat(gate5e): add recoverable E4 quarantine relocation` | 新增 `empty_dir_quarantine.py`，实现两阶段迁移、Outcome A/B/C/D、以及无覆写回滚保障 |
| **Task 4 (Executor 生产切入)** | `2512ca2` | `fix(gate5e): switch E4 execution to quarantine-first removal` | `rmdir_empty` 切入隔离区迁移逻辑，新增 `restore_empty_dir` 执行分支，零破坏性调用，Task 1 RED 转 GREEN |
| **Task 5 (Freeze, Validate & Undo)** | `bf04b43` | `feat(undo): restore preserved E4 directory objects` | `service.py` 接入 `restore_empty_dir` 的 Freeze、Validate 与 Undo Plan 生成，适配浅优先恢复与旧计划兼容 |
| **Task 6 (Worker 对账与恢复)** | `613e1b6` | `fix(tasks): reconcile quarantine-first E4 directory operations` | `handlers.py` 实现 State A~E 隔离区对账状态机、`restore_empty_dir` 恢复逻辑与完整 Journal 留痕 |

---

## 5. 5 级回归测试套件验证结果

所有测试均在真实 Linux Docker 容器环境（`nas-test-env:latest`, Python 3.12.14）中独立完整运行，数据完全真实：

### Level 1: 专用 hotfix2 专项测试
```text
pytest tests/test_gate5e_e4_hotfix2.py -v
============================== 26 passed in 0.97s ==============================
```
- 覆盖测试项：
  - `test_rmdir_empty_final_identity_check_then_empty_replacement_is_never_destroyed`（Task 1 RED -> GREEN）
  - `test_rename_noreplace_at_success` / `test_rename_noreplace_at_target_exists_fails` / `test_rename_noreplace_at_source_not_found`
  - `test_relocate_empty_dir_outcome_a_clean_success`
  - `test_relocate_empty_dir_outcome_b_identity_mismatch_rolls_back`
  - `test_relocate_empty_dir_outcome_c_file_replaced_rolls_back`
  - `test_relocate_empty_dir_outcome_d_not_empty_rolls_back`
  - `test_relocate_empty_dir_rollback_conflict_preserves_quarantine_safely`
  - `test_execute_rmdir_empty_zero_destructive_syscalls_and_preserves_in_quarantine`
  - `test_execute_restore_empty_dir_restores_exact_inode`
  - `test_execute_restore_empty_dir_target_occupied_fails_safely`
  - `test_freeze_restore_empty_dir_captures_identity`
  - `test_freeze_restore_empty_dir_rejects_non_quarantine_or_non_dir`
  - `test_validate_restore_empty_dir_success_and_chaining`
  - `test_validate_restore_empty_dir_stale_on_identity_mismatch`
  - `test_create_undo_plan_produces_restore_empty_dir`
  - `test_undo_restore_empty_dir_inverts_to_rmdir_empty`
  - `test_reconcile_rmdir_empty_state_a_returns_to_planned`
  - `test_reconcile_rmdir_empty_state_b_relocated_completes_with_quarantine_journal`
  - `test_reconcile_rmdir_empty_state_c_quarantine_identity_mismatch_fails_safely`
  - `test_reconcile_rmdir_empty_state_d_both_source_and_quarantine_exist_conflicts`
  - `test_reconcile_rmdir_empty_state_e_both_absent_fails_closed`
  - `test_reconcile_restore_empty_dir_states`

### Level 2: 全部 E4 套件
```text
pytest tests/test_gate5e_e4_*.py
====================== 107 passed, 2 warnings in 3.55s =======================
```

### Level 3: Gate5-E 全阶段套件（E1 + E2 + E3 + E4）
```text
pytest tests/test_gate5e_e1_*.py tests/test_gate5e_e2_*.py tests/test_gate5e_e3_*.py tests/test_gate5e_e4_*.py
====================== 289 passed, 2 warnings in 14.10s ======================
```

### Level 4: 核心架构回归套件（Planning + Gate3 + Execution + Gate2 Undo & Reconciliation）
```text
pytest tests/test_planning.py tests/test_gate3*.py tests/test_execution.py tests/test_gate2_hotfix2_undo_algebra.py tests/test_gate2_hotfix4_reconciliation_evidence.py
======================= 66 passed, 2 warnings in 6.01s =======================
```

### Level 5: 全量回归测试（Entire Test Suite）
```text
pytest tests/
==================== 1106 passed, 18 warnings in 97.46s ====================
```

### 静态生产代码安全检查
- `grep -n "rmdir" app/execution/executor.py app/batch_utilities/empty_dir_quarantine.py`:
  仅在操作名判断字符串中出现，**零 `os.rmdir` 系统调用**。
- `grep -n "unlink" app/batch_utilities/empty_dir_quarantine.py`: **零调用**。
- `grep -n "rmtree" app/execution/executor.py app/batch_utilities/empty_dir_quarantine.py`: **零调用**。

---

## 6. 状态声明（Strict Declaration）

根据项目规范与角色约束，Implementation Agent 严格不越权自行裁定评审通过，最终状态声明如下：

```text
Gate5-E / E4-hotfix2 IMPLEMENTATION COMPLETE
READY FOR INDEPENDENT REVIEW
```
