# Gate5-E / E4-hotfix3 Walkthrough: No-Follow Quarantine Binding & FD-Anchored Rollback

## 1. 任务背景与授权基线

本任务为 NAS File Center Gate5-E / E4 阶段的受限实现修复（Bounded Implementation Hotfix）**hotfix3**。无需新的 Architecture Amendment，沿用现行权威 `docs/history/gate5e/gate5e-e4-hotfix2-architecture-freeze-amendment.md`。

- **远程仓库**：`https://github.com/JinHaocong/nas-file-center`
- **目标分支**：`v0.3.5-gate5c-hotfix4`
- **起始授权基线 HEAD (`PREVIOUS_HEAD`)**：`b0d093898cfc3603aa15fb5ca4b53ba3462724d1`
- **权威 Amendment 提交**：`9d8bfc2d8cee562ba2edec0b956fb89a502c5a40`
- **权威 hotfix2 审查 HEAD**：`b0d093898cfc3603aa15fb5ca4b53ba3462724d1`

---

## 2. 独立审查发现与修复方案

### Finding 1 (BLOCKER): QUARANTINE_ROOT symlink prohibition bypassed
- **根因**：`empty_dir_quarantine.py` 原代码在检查 `q_root.is_symlink()` 前先执行了 `Path(quarantine_root).resolve()`，导致若配置的隔离区根路径叶子为软链接，会被提前解引用，随后的检查观察到的是目标目录而非配置的软链接叶子本身。
- **修复**：
  - 提取 `acquire_safe_quarantine_root_fd(quarantine_root)` 工具函数。
  - 在解引用或打开前，首先对配置的词法叶子路径执行 `os.lstat()` / `Path.is_symlink()` 严格校验，发现软链接立即阻断抛错。
  - 校验为真实目录后，以 `os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW` 打开文件描述符，并通过 `os.fstat()` 绑定物理身份。
  - 后续所有隔离区内操作（包含状态检查、重命名迁移、目标验证）均基于该已绑定的描述符（`dir_fd=q_root_fd`）执行，严禁回退到基于解析路径的字符串操作。
  - 在 `app/execution/executor.py` 的 `restore_empty_dir` 分支中同样接入该安全打开机制。

### Finding 2 (BLOCKER): rmdir_empty crash reconciliation State C rollback is not FD-anchored
- **根因**：崩溃对账状态机 State C 原代码在回滚误迁入的不匹配对象时，直接通过 `os.open(str(src.parent), os.O_RDONLY | os.O_DIRECTORY)` 打开源父目录，既无 `os.O_NOFOLLOW` 标志，也未从受信任的 `ALLOWED_ROOT` 逐级校验打开。若崩溃窗口期祖先目录被恶意/并发替换为软链接，回滚重命名会顺着软链接将未知对象注入非授权目录。
- **修复**：
  - 提取 `safe_open_parent_fd(source, allowed_roots)` 上下文管理器。
  - 从匹配的授权根目录（`base_root`）起始，校验根目录不是软链接，校验 `source` 是严格后代而非根目录本身。
  - 沿路径逐级以 `os.open(comp, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=curr_fd)` 获取父目录描述符。
  - 只有在隔离区描述符与源父目录描述符均安全锚定且源叶子在父目录中确不存在时，才执行原子无覆写回滚 `rename_noreplace_at`。
  - 若任一级目录变为软链接、被删除、越界或无法安全打开，严禁回滚（DO NOT ROLLBACK），将未知对象完好保留在隔离区，标记 item 状态为 `failed`（附带 conflict 证据）。
  - 完全消除了 `app/tasks/handlers.py` 中所有直接路径 `os.open(str(src.parent))` 调用。

---

## 3. TDD 研发提交历程

开发全程严格遵循 TDD 规范与阶段递进，每步独立提交并推送到远程分支：

| 阶段 | Commit Hash | 提交信息 | 核心说明 |
| :--- | :--- | :--- | :--- |
| **Phase 1** | `66e0de3` | `docs(gate5e): record E4 hotfix2 independent review blockers` | 正式入库 hotfix2 独立审查结论与 blocker 分析 |
| **Phase 2** | `497abc7` | `test(gate5e): reproduce E4 hotfix2 review blockers` | 新增两个 RED 回归测试，精准复现 Finding 1 与 Finding 2 |
| **Phase 3** | `74f575e` | `fix(gate5e): enforce no-follow quarantine binding and fd-anchored rollback` | 实施最小生产修复，两项 RED 测试均转为 GREEN |
| **Phase 4** | `97fa502` | `docs(gate5e): correct hotfix2 provenance commit hashes` | 修正 hotfix2 walkthrough 中的权威 SHA 引用 |

---

## 4. 5 级回归测试套件验证结果

全部测试均在 Docker 容器（`nas-test-env:latest`, Python 3.12.14）中基于真实挂载运行：

### Level 1: hotfix2 / hotfix3 专项测试
```text
docker run --rm -e PYTHONPATH=. -v "$(pwd)":/app -w /app nas-test-env:latest pytest tests/test_gate5e_e4_hotfix2.py -v
============================== 28 passed in 1.01s ==============================
```

### Level 2: 全部 E4 套件
```text
docker run --rm -e PYTHONPATH=. -v "$(pwd)":/app -w /app nas-test-env:latest pytest tests/test_gate5e_e4_*.py
====================== 109 passed, 2 warnings in 3.64s =======================
```

### Level 3: Gate5-E 全阶段套件 (E1 + E2 + E3 + E4)
```text
docker run --rm -e PYTHONPATH=. -v "$(pwd)":/app -w /app nas-test-env:latest pytest tests/test_gate5e_e1_*.py tests/test_gate5e_e2_*.py tests/test_gate5e_e3_*.py tests/test_gate5e_e4_*.py
====================== 291 passed, 2 warnings in 13.33s ======================
```

### Level 4: 核心架构回归套件
```text
docker run --rm -e PYTHONPATH=. -v "$(pwd)":/app -w /app nas-test-env:latest pytest tests/test_planning.py tests/test_gate3*.py tests/test_execution.py tests/test_gate2_hotfix2_undo_algebra.py tests/test_gate2_hotfix4_reconciliation_evidence.py
======================= 66 passed, 2 warnings in 5.62s =======================
```

### Level 5: 全量回归套件 (Entire Test Suite)
```text
docker run --rm -e PYTHONPATH=. -v "$(pwd)":/app -w /app nas-test-env:latest pytest tests/
==================== 1108 passed, 18 warnings in 98.37s (0:01:38) ====================
```

---

## 5. 严格范围控制（Zero Scope Drift）

- **代码修改清单**：
  - `app/batch_utilities/empty_dir_quarantine.py`: 增加 `acquire_safe_quarantine_root_fd`、`safe_open_parent_fd`，增强 `relocate_empty_dir_to_quarantine`。
  - `app/execution/executor.py`: `restore_empty_dir` 接入 `acquire_safe_quarantine_root_fd`。
  - `app/tasks/handlers.py`: State C 回滚使用描述符链安全对账。
  - `tests/test_gate5e_e4_hotfix2.py`: 增加两项审查 blocker 复现回归用例。
  - `docs/history/gate5e/gate5e-e4-hotfix2-independent-review.md`: 新增审查结论归档。
  - `docs/history/gate5e/gate5e-e4-hotfix2-walkthrough.md`: 修正 SHA 引用。
- **零破坏性降级**：无 `os.rename` fallback，无 `shutil.move`，无 `copy+delete`，无 `rmdir`，无 `unlink`，无 `rmtree`。
- **零数据库迁移**：无任何 Alembic 迁移脚本或数据表结构变动。
- **零前端改动**：无任何前端代码或接口变更。
- **零 Gate5-F**：绝无任何后续 Gate 特性提前引入。
- **零非安全直接路径调用**：`app/tasks/handlers.py` 中 `os.open(str(src.parent))` 已完全清除（0 matches）。

---

## 6. 状态声明（Strict Declaration）

```text
Gate5-E / E4-hotfix3 IMPLEMENTATION COMPLETE
READY FOR INDEPENDENT REVIEW
```
