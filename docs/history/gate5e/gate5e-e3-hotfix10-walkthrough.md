# Gate5-E / E3-hotfix10 Walkthrough: Wrapper Physical Identity Binding + Unified Enumeration Authority

## 1. 任务背景与根本原因

在 E3-hotfix9 完成了叶子节点符号链接的 fd 级别 No-Follow 拦截后，独立评审发现了深层的文件系统时序与权威漏洞：

### 1.1 普通目录物理身份替换（Ordinary Directory Identity Replacement）
- **故障场景**：
  1. 初始文件系统存在合法的 Wrapper 目录 `root/W`（物理身份 `inode_A`），内含 `before.txt`。
  2. 调用规范化与预检：`validate_wrappers_preflight()` 成功通过，但未将解析确立的 Wrapper 物理身份（`(st_dev, st_ino)`）传递并绑定到后续的 Discovery 获取阶段。
  3. **在 Preflight 完成后、Discovery 执行前**，`root/W` 被删除并重新创建为一个全新的普通真实目录（物理身份 `inode_B`），内含 `sneaky.txt`（或者上级中间路径被外部进程重新指向了另一个同名普通目录）。
  4. **缺陷表现**：
     - `discover_flatten_one_level()` 虽然使用了 `O_NOFOLLOW` 打开，但因为目标是普通目录而不是符号链接，打开操作顺利成功；
     - 由于 Discovery 获取阶段完全没有比对预期物理身份，直接对替换后的目录 `inode_B` 调用了 `os.scandir` 枚举；
     - 尽管后续连续性检查可能会发现物理身份变更，但**在 Discovery 阶段已经实质性枚举并泄露了替换目录的子项内容**。

### 1.2 连续性重扫身份竞态与路径基枚举（Continuity Rescan Identity Race & Path-based Enumeration）
- **故障场景**：
  - 在图连续性检查 `_validate_wrapper()` 中，历史实现仍保留了基于原始路径名的 `_scandir(w_lex)`。
  - 在检查物理身份（`os.lstat`）与实际执行 `_scandir` 之间存在 TOCTOU 竞态。若外部并发进程在此时替换目录，`_scandir` 将遍历非预期的目录内容。

---

## 2. 核心架构修复与代码改动

### 2.1 全局权威不变式（Global Authority Invariant）
> **在已打开的目录描述符 `fd` 经证实完全匹配预期的 Wrapper 物理身份（`st_dev, st_ino`）之前，绝对禁止枚举任何目录子项。**
> 若物理身份不匹配或 Wrapper 变为符号链接，必须立即失败关闭（Fail-Closed），且保证 **0 替换子项枚举**。

### 2.2 `app/batch_utilities/flatten.py`
- 引入统一安全获取上下文管理器 `acquire_wrapper_dir(path, expected_device=None, expected_inode=None, stage=None)`：
  1. **原子打开**：以 `os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW` 标志位打开目录，拒绝叶子符号链接；若为符号链接直接抛出 `BatchUtilitySymlinkBlockedError`；
  2. **物理身份强校验**：使用 `os.fstat(fd)` 验证描述符底层的实际设备号和 inode。若指定了 `expected_device` / `expected_inode` 且不匹配，立即抛出 `BatchUtilityInvalidConfigError(..., error="WRAPPER_IDENTITY_CHANGED")`。**在进入 `scandir` 之前彻底阻断枚举**；
  3. **句柄封装与资源回收**：将验证通过的描述符封装为 `FdPath` 供 `os.scandir` 枚举，并在 `finally` 中严格关闭描述符；
  4. **底层 I/O 错误传播**：对于真正的底层读取 `OSError`（如权限拒绝等），保留 hotfix6 的严格 Fail-Closed 策略向外抛出（附带 `stage` 标记）。
- 重构 `discover_flatten_one_level(wrapper_paths, expected_identities=None)`：
  - 支持可选的 `expected_identities` 映射字典 `{clean_path: (st_dev, st_ino)}`；
  - 统一通过 `acquire_wrapper_dir` 进行目录获取，全面受物理身份绑定保护。

### 2.3 `app/batch_utilities/flatten_graph.py`
- 重构 `validate_wrappers_preflight()`：
  - 在预检阶段收集所有合法 Wrapper 的已解析物理身份：`identities[w_clean] = (st.st_dev, st.st_ino)` 并作为第二元组项返回。
- 重构 `_validate_wrapper()`：
  - 废弃未绑定的路径名扫描 `_scandir(w_lex)`；
  - 接入 `acquire_wrapper_dir(w_lex, expected_device=expected_dev, expected_inode=expected_ino, stage="CONTINUITY")`；
  - 当捕获到 `error="WRAPPER_IDENTITY_CHANGED"` 或符号链接拦截时，标记当前 Wrapper 失效并记录 `WRAPPER_IDENTITY_CHANGED` 图冲突，确保 0 替换子项枚举；
  - 底层 I/O 错误严格向外重新抛出。

### 2.4 `app/batch_utilities/compiler.py`
- 更新 `compile_flatten_one_level_preview()`：
  - 接收并校验预检返回的 `expected_identities`；
  - 将确立的预期物理身份传递给 `discover_flatten_one_level(canonical_wrappers, expected_identities=expected_identities)`（附带对旧测试 mock 的入参兼容处理）；
  - 快照观测（Snapshot Observation）扫描全面接入 `acquire_wrapper_dir(clean_w, expected_device=exp_dev, expected_inode=exp_ino, stage="SNAPSHOT")`，身份不符或符号链接均标记为 `scan_status: "FAILED"` 且 0 子项枚举。

### 2.5 零生产范围外修改
- 生产代码仅修改：`app/batch_utilities/compiler.py`、`app/batch_utilities/flatten.py`、`app/batch_utilities/flatten_graph.py`。
- 测试代码仅修改：`tests/test_gate5e_e3_compiler.py`、`tests/test_gate5e_e3_discovery.py`、`tests/test_gate5e_e3_graph.py`。
- 零 DB migration，零新 Worker，零新 Undo 引擎。

---

## 3. 测试验证

### 3.1 明确的 RED 失败与 GREEN 修复验证
1. **普通目录替换阻断测试**：[`test_compiler_wrapper_ordinary_dir_replacement_fails_closed_before_discovery`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_gate5e_e3_compiler.py)
   - RED：预检完成后替换为普通目录 `inode_B`，Discovery 阶段枚举了 `sneaky.txt`。
   - GREEN：在进入 Discovery 枚举前抛出 `BatchUtilityInvalidConfigError(error="WRAPPER_IDENTITY_CHANGED")`，0 候选项枚举。
2. **中间路径普通目录替换阻断测试**：[`test_compiler_wrapper_intermediate_path_replacement_fails_closed_before_discovery`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_gate5e_e3_compiler.py)
   - RED：中间路径被重指向新普通目录，Discovery 枚举了新目录下的文件。
   - GREEN：身份校验不符立即抛出 `WRAPPER_IDENTITY_CHANGED`，0 候选项枚举。
3. **连续性检查身份竞态测试**：[`test_continuity_wrapper_rescan_race_directory_replacement_blocks_child_acquisition`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_gate5e_e3_graph.py)
   - RED：`_scandir` 枚举了替换目录下的 `sneaky.txt`。
   - GREEN：`acquire_wrapper_dir` 在打开时刻拦截并上报 `WRAPPER_IDENTITY_CHANGED`，0 子项枚举。
4. **底层 Discovery 物理身份校验测试**：[`test_discover_flatten_wrapper_identity_mismatch_fails_closed`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_gate5e_e3_discovery.py)
   - RED：若传入预期物理身份与实际目录不符，仍然正常枚举了文件。
   - GREEN：打开并校验 `fstat` 后立即抛出 `WRAPPER_IDENTITY_CHANGED`，0 候选项枚举。

### 3.2 自动化测试结果
- **针对性回归测试（4 tests）**：4 passed (100% PASS)
- **E3 核心套件（`pytest tests/test_gate5e_e3_*.py`）**：103 passed (100% PASS)
- **E1 + E2 套件（`pytest tests/test_gate5e_e1_*.py tests/test_gate5e_e2_*.py`）**：77 passed (100% PASS)
- **全量后端测试套件（`pytest tests/`）**：997 passed, 0 failed (100% PASS)

---

## 4. 边界与约束遵守确认

- [x] 未开启 E4。
- [x] 未声明 E3 PASS / CLOSED。
- [x] 零生产范围外修改。
- [x] 零 DB migration，零新 Worker，零新 Undo 引擎。
- [x] 严格满足全局物理身份绑定与统一枚举权限不变式。
