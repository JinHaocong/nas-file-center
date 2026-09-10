# Gate5-E / E3-hotfix9 Walkthrough: Discovery-Time No-Follow Wrapper Authority

## 1. 任务背景与根本原因

在 E3-hotfix8 完成静态预解析路径语义统一后，独立评审发现了一个关键的文件系统时序竞态条件（TOCTOU race condition）：

- **故障场景**：
  1. 初始文件系统：
     ```
     root/
     ├── A/
     │   ├── B/
     │   ├── W/
     │   │   └── before.txt
     │   └── Real/
     │       └── secret.txt
     └── link -> A/B
     ```
  2. 输入 Wrapper 路径：`root/link/../W/`。
  3. 执行 `validate_wrappers_preflight()` 时，`root/A/W` 是一个普通真实目录，预检顺利通过（PASS）。
  4. **在预检完成后、Discovery 执行前**，`root/A/W` 被外部并发操作替换为指向 `root/A/Real` 的符号链接（`root/A/W -> root/A/Real`）。
  5. **缺陷表现**：
     - `canonicalize_wrapper_path()` 发现叶子节点为符号链接时，此前代码直接返回了 `raw_leaf` 原始文本；
     - `discover_flatten_one_level()` 使用普通的 `os.scandir(w_path)`，在系统调用 `opendir()` 层面自动跟随了新的符号链接；
     - 符号链接目标目录下的 `secret.txt` 被扫描并作为候选项输出；
     - 尽管后续连续性检查最终报错了 `WRAPPER_IDENTITY_CHANGED`，但**在 Discovery 阶段已经实质性遍历并泄露了符号链接目标目录**，违背了「在任何时序下绝不遍历符号链接 Wrapper」的 E3 安全硬约束。

---

## 2. 核心架构修复与代码改动

### 2.1 全局安全不变式（Global Invariant）
目录枚举获取（Directory Acquisition）必须在真正打开目录的时刻具有物理 No-Follow 权威保证。先前的 `lstat`/预检无法跨越 TOCTOU 窗口。若 Wrapper 在获取前或获取时变为符号链接，必须直接失败关闭（`BATCH_UTILITY_SYMLINK_BLOCKED`），且必须保证 **0 符号链接目标项枚举**。

### 2.2 `app/batch_utilities/flatten.py`
- 引入 [`FdPath(int)`](file:///Users/Kerwin/MyProject/nas-file-center/app/batch_utilities/flatten.py)：封装文件描述符并在字符串化时保留原始路径名，既能在底层安全使用 `fdopendir`，又能保持对错误报告及测试 mock 的完整透明性。
- 重构 [`discover_flatten_one_level()`](file:///Users/Kerwin/MyProject/nas-file-center/app/batch_utilities/flatten.py)：
  - 使用原子标志位打开目录：`os.open(clean_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)`；
  - 若因为符号链接导致打开失败（`NotADirectoryError` 或 `ELOOP`），通过 `os.lstat` 判定为符号链接后立即抛出 [`BatchUtilitySymlinkBlockedError`](file:///Users/Kerwin/MyProject/nas-file-center/app/batch_utilities/errors.py)（HTTP 409 `BATCH_UTILITY_SYMLINK_BLOCKED`）；
  - 将安全的 `fd` 句柄包装为 `FdPath` 传递给 `os.scandir(dir_handle)`，确保通过原子打开的已验证目录描述符进行枚举；
  - 在 `finally` 块中可靠关闭 `fd`，防止文件描述符泄露。

### 2.3 `app/batch_utilities/digest.py`
- 审计并修复 [`canonicalize_wrapper_path()`](file:///Users/Kerwin/MyProject/nas-file-center/app/batch_utilities/digest.py)：
  - 移除 `if stat.S_ISLNK(st.st_mode): return raw_leaf` 的不安全回退；
  - 若在规范化时检测到叶子为符号链接，严格 Fail-Closed 抛出 `BatchUtilitySymlinkBlockedError`，防止符号链接路径流入后续 Discovery 流程。

### 2.4 `app/batch_utilities/compiler.py`
- 快照观测（Snapshot Observation）同步采用 `clean_w`、`os.open(..., O_NOFOLLOW)` 及 `FdPath` 模式，确保 Discovery 之后的快照扫描同样绝不跟随符号链接。

### 2.5 零生产范围外修改
- 严格遵循范围限制，仅修改 `app/batch_utilities/flatten.py`、`app/batch_utilities/digest.py`、`app/batch_utilities/compiler.py`。
- 未修改 `app/batch_utilities/graph.py`、`app/execution/executor.py`、`app/fs_ops.py`、`app/tasks/handlers.py`、`app/models.py`、`frontend/**`、`migrations/**`、`app/workflows/**`。
- 零 DB migration，零新 Worker，零新 Undo 引擎。

---

## 3. 测试验证

### 3.1 明确的 RED 失败与 GREEN 修复验证
在各层级测试套件中增加了强制触发 TOCTOU 竞态的回归测试：
1. **Discovery 单测**：[`test_discover_flatten_leaf_symlink_blocked`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_gate5e_e3_discovery.py)
   - RED：直接调用 `discover_flatten_one_level` 遇到叶子符号链接时静默枚举了 `secret.txt`，未抛出异常。
   - GREEN：原子打开拒绝符号链接，抛出 `BatchUtilitySymlinkBlockedError`，0 候选项。
2. **Compiler 回归**：[`test_compiler_preflight_to_discovery_symlink_swap_blocks_enumeration`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_gate5e_e3_compiler.py)
   - RED：预检通过后立即将 Wrapper 替换为符号链接，编译层输出了包含 `secret.txt` 的候选项。
   - GREEN：抛出 `BatchUtilitySymlinkBlockedError`，`discovered_candidates` 长度为 0，完全无 `secret.txt`。
3. **API Preview 回归**：[`test_preview_preflight_to_discovery_symlink_swap_blocks_enumeration`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_gate5e_e3_api.py)
   - RED：返回 HTTP 200，响应体内泄漏了 `secret.txt`。
   - GREEN：返回 HTTP 409 `BATCH_UTILITY_SYMLINK_BLOCKED`，响应内容中完全无 `secret.txt`。
4. **API Generate 回归**：[`test_generate_preflight_to_discovery_symlink_swap_blocks_enumeration`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_gate5e_e3_generate.py)
   - RED：Discovery 扫描了 `secret.txt` 后才由摘要不匹配报出 `PREVIEW_CHANGED`。
   - GREEN：Discovery 阶段即拦截并返回 HTTP 409 `BATCH_UTILITY_SYMLINK_BLOCKED`，0 discovery 候选项，0 `BatchPlan`，0 `BatchPlanItem`，无文件系统副作用。

### 3.2 自动化测试结果
- **针对性回归测试（4 tests）**：4 passed (100% PASS)
- **Hotfix8 A-G 回归测试（10 tests）**：10 passed (100% PASS)
- **E3 核心套件（`pytest tests/test_gate5e_e3_*.py`）**：99 passed (100% PASS)
- **E1 + E2 套件（`pytest tests/test_gate5e_e1_*.py tests/test_gate5e_e2_*.py`）**：77 passed (100% PASS)
- **全量后端测试套件（`pytest tests/`）**：993 passed, 0 failed (100% PASS)

---

## 4. 边界与约束遵守确认

- [x] 未开启 E4。
- [x] 未声明 E3 PASS / CLOSED。
- [x] 零生产范围外修改。
- [x] 零 DB migration，零新 Worker，零新 Undo 引擎。
- [x] 严格满足全局 No-Follow Wrapper 权威不变式。
