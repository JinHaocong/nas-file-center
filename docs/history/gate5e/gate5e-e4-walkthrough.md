# Gate5-E / E4 Walkthrough: Remove Empty Directories Implementation

## 1. 任务背景与基线定义

本任务为 NAS File Center Gate5-E 最终阶段 **E4**：实施 `remove_empty_dirs` 批量工具动作，安全删除指定作用域下真正为空的后代目录链。

- **唯一授权代码基线**：`nas-file-center-v0.3.5-gate5e-e3-hotfix11.zip`
- **基线 Commit HEAD**：`25e48289c4e6c8b754c9293ce05a23de4a64ee80`
- **实现依据**：
  1. `Gate5-E-E4-Architecture-Freeze-2026-09-10.md`
  2. `Gate5-E-E4-Implementation-Plan-2026-09-10.md`
  3. `Gate5-E-E4-Implementation-Agent-Prompt-2026-09-10.md`
  4. `HANDOFF.md`

---

## 2. 生产代码修改边界（Zero Scope Drift）

严格遵循架构冻结范围边界约束，所有变更仅限 8 个生产文件，无任何越界改动：
- `app/batch_utilities/schema.py`: 增加 `RemoveEmptyDirsAction`，注册 Action 联合体，定义 `REMOVE_EMPTY_DIR` 决策常量。
- `app/batch_utilities/digest.py`: 增加作用域与动作的规范化摘要计算。
- `app/batch_utilities/empty_dirs.py` (新增模块): 实现严格叶子预检、物理身份捕获与基于文件描述符（FD）的 POSIX 递归安全发现引擎。
- `app/batch_utilities/compiler.py`: 增加 `compile_remove_empty_dirs_preview` 与预览阶段分发。
- `app/batch_utilities/service.py`: 增加只读实时目录预览源标记。
- `app/service.py`: 增加 Draft Plan 生成、`rmdir_empty` / `mkdir_empty` 的 Freeze 物理捕获、Validate 目标有效性与链式校验、以及逆向 Undo Plan 生成。
- `app/execution/executor.py`: 实现单层原子 `os.rmdir()` 删除与单层 `os.mkdir()` 结构性恢复。
- `app/tasks/handlers.py`: 实现运行时隔离区/新鲜度门控、OperationJournal 记录、以及崩溃对账恢复（Reconciliation）。

**严正确认**：
- 零 DB migration（未新增表或列）。
- 零前端代码修改。
- 零新 Worker 进程或协议变更。
- 零新 Undo 引擎。
- 零 Copy 功能引入。
- 零 Gate5-F 特性进入。
- 零 E1/E2/E3 语义回退或既有行为破坏。
- 严禁且未对目录调用 `os.unlink` 或 `shutil.rmtree`；仅使用 `os.rmdir()` 删除空目录。

---

## 3. 核心安全机制与关键算法

### 3.1 基于文件描述符（FD）的安全发现（FD-Anchored Traversal）
- 遍历过程中打开目录描述符 `parent_fd`，后续枚举子项均使用 `os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY, dir_fd=parent_fd)` 并执行 `fstat(child_fd)`；
- 强行比对 `st_dev` 与 `st_ino`，确保打开的对象即为枚举时所见对象，免疫符号链接替换与 TOCTOU 竞争；
- 遭遇普通文件、特殊文件（FIFO/Socket/设备）、符号链接（哪怕是指向真实目录的符号链接）时，该目录及其所有父级祖先目录立即标记为非空。

### 3.2 虚拟树自底向上判定（Virtual Empty Tree Pruning）
- 采用后序遍历（Post-order traversal）：只有当子目录中的所有后代子目录均被判定为可删除空目录，且当前目录自身不含任何其他条目时，当前目录才判定为可删除；
- 排序规则：严格按深度倒序（deepest-first）、同深度按规范化路径升序排序，确保执行时从最深叶子目录逐层向上安全删除；
- 保护上限：单作用域最大收集 50,000 个目录，超限抛出 `BATCH_UTILITY_LIMIT_EXCEEDED`。

### 3.3 严格生命周期：Freeze -> Validate -> Execute
- **Freeze**：
  - `rmdir_empty`：捕获当前目录的 `device` 和 `inode`，记录快照，`size=0, mtime_ns=0`；
  - `mkdir_empty`：以源作用域 anchor 目录的身份进行锚定，`size=0, mtime_ns=0`。
- **Validate**：
  - `rmdir_empty`：验证设备号与 inode 一致，确认依然在允许根目录内且不在隔离区；
  - `mkdir_empty`：验证 anchor 存在且身份未变，target 不存在且不是符号链接，target 为 anchor 的严格后代，父目录存在或在当前 Plan 前序步骤中已规划创建（链式验证），且均在允许根目录内。
- **Execute**：
  - `rmdir_empty`：要求 `ALLOW_MUTATION=True` 与 `ALLOW_DELETE=True`，使用单层原子 `os.rmdir()`；
  - `mkdir_empty`：要求 `ALLOW_MUTATION=True`，使用单层 `os.mkdir()`（严禁 `parents=True` 或覆写）。

### 3.4 结构性 Undo 代数（Structural Undo Algebra）
- **逆映射规则**：
  - `rmdir_empty` 的逆操作为 `mkdir_empty`（anchor 为原始 `scope_root`，target 为被删目录）；
  - `mkdir_empty` 的逆操作为 `rmdir_empty`（source 为被创建目录）；
- **倒序执行**：
  - 原始删除顺序为 deepest-first（如 `scope/a/b` 然后 `scope/a`）；
  - 查询 Journal 逆序（`sequence DESC`）后，Undo Plan 自然呈现 shallowest-first（如 `mkdir scope/a` 然后 `mkdir scope/a/b`），确保先建父后建子；
- **局限性声明（Limitation Contract）**：
  - Undo 是**结构性**重建，仅按原层级重新创建空目录；
  - **不承诺且不恢复**原 inode、原 ctime/mtime、所有者权限、ACL 或扩展属性（xattr）。

### 3.5 崩溃对账幂等性（Crash Reconciliation）
- 在 `_reconcile_executing_item()` 中：
  - `rmdir_empty`：若崩溃前已完成删除（目标已不存在），对账标记为 `completed` 并补录缺失的 OperationJournal（若已存在则不重复写入）；若目录依然存在且身份完好，退回 `planned`；若身份变更或被替换为文件/符号链接，标记为 `failed` 冲突。
  - `mkdir_empty`：若目标目录已成功创建且为空目录、anchor 完好，标记为 `completed` 并补录 Journal；若目标不存在且 anchor 完好，退回 `planned`；若目标为非空目录、文件、符号链接或越界，标记为 `failed` 冲突。

---

## 4. TDD 执行轨迹与提交记录

| 任务 | 提交 Hash | 提交信息 | 核心改动内容 |
| :--- | :--- | :--- | :--- |
| **Task 1** | `f101871` | `feat(batch-utilities): add remove-empty-dirs action contract` | Schema 结构、规范化路径与动作摘要校验 |
| **Task 2** | `32dd568` | `feat(batch-utilities): add race-safe empty-directory discovery` | 严格作用域预检与 FD 安全树发现引擎 |
| **Task 3** | `032d8e8` | `feat(batch-utilities): compile remove-empty-dirs previews` | 编译器预览接入、Operation 枚举扩充 |
| **Task 4** | `81a280e` | `feat(batch-utilities): generate remove-empty-dirs drafts` | 服务层 Plan 生成、Phase B 事务集成 |
| **Task 5** | `f1c6601` | `feat(planning): validate empty-directory lifecycle semantics` | Freeze / Validate 生命周期与链式校验 |
| **Task 6** | `fbd2587` | `feat(execution): add fail-closed empty-directory operations` | Executor / Worker 权限校验与原子系统调用 |
| **Task 7** | `cf6dea5` | `feat(undo): add structural empty-directory inverses` | OperationJournal 序列化与结构性 Undo 逆向代数 |
| **Task 8** | `35eaac1` | `feat(tasks): reconcile empty-directory operations` | 崩溃对账恢复逻辑与幂等性保证 |

---

## 5. 测试验证与回归结果

### 5.1 E4 专属测试套件（Focused E4 Suite）
运行命令：`pytest tests/test_gate5e_e4_*.py -q`
- `tests/test_gate5e_e4_schema.py`: 13 passed
- `tests/test_gate5e_e4_preflight.py`: 10 passed
- `tests/test_gate5e_e4_discovery.py`: 9 passed
- `tests/test_gate5e_e4_compiler.py`: 8 passed
- `tests/test_gate5e_e4_api.py`: 4 passed
- `tests/test_gate5e_e4_generate.py`: 4 passed
- `tests/test_gate5e_e4_lifecycle.py`: 13 passed
- `tests/test_gate5e_e4_undo.py`: 3 passed
- `tests/test_gate5e_e4_recovery.py`: 6 passed
- **合计**：**70 passed, 0 failed (100% PASS)**

### 5.2 全量 Gate5-E 回归（E1 + E2 + E3 + E4）
运行命令：`pytest tests/test_gate5e_e1_*.py tests/test_gate5e_e2_*.py tests/test_gate5e_e3_*.py tests/test_gate5e_e4_*.py -q`
- E1 ~ E3 历史用例：182 passed
- E4 新增用例：70 passed
- **合计**：**252 passed, 0 failed (100% PASS)**

### 5.3 核心状态机与回归套件
运行命令：`pytest tests/test_planning.py tests/test_gate3*.py tests/test_execution.py tests/test_gate2_hotfix2_undo_algebra.py tests/test_gate2_hotfix4_reconciliation_evidence.py -q`
- **合计**：**66 passed, 0 failed (100% PASS)**

### 5.4 后端全量测试套件（Full Backend Test Suite）
运行命令：`pytest tests/ -q`
- **总计收集并运行**：**1069 passed, 0 failed (100% PASS)**
- **运行警告**：18 warnings（均为 FastAPI/Starlette testclient 与 Python 3.12 sqlite3 datetime 弃用提示，零代码异常）

---

## 6. 最终交付产物与 Provenance

- **代码基线 HEAD**：`25e48289c4e6c8b754c9293ce05a23de4a64ee80`
- **交付包文件**：`nas-file-center-v0.3.5-gate5e-e4.zip`
- **Git 真实实现提交 HEAD**：`84bce003787a40bd9c8e75559b775eef19330b5a`
- **归档包 SHA256 校验和**：`4b4089d20cc3134e9c777c20af5cea28bb90d24c87dfc1406ed273a7bbbf5a3b`
- **ZIP 注释（Comment）**：`84bce003787a40bd9c8e75559b775eef19330b5a`

---

## 7. 结论与状态声明

根据 Gate5-E / E4 规范与 Superpowers 工作流要求：
- 严格完成所有 TDD 任务，测试全量 GREEN，零回归；
- 零生产越界改动，严守架构冻结契约。

**声明状态**：
```text
Gate5-E / E4 IMPLEMENTATION COMPLETE
READY FOR INDEPENDENT REVIEW
```
