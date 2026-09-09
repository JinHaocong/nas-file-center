# Gate5-E / E3-hotfix8 Walkthrough: Unified Wrapper Path-Semantics Authority

## 1. 任务背景与根本原因

在 E3-hotfix7 完成 `canonicalize_wrapper_path()` 修复后，针对 E3 闭环的独立评审发现了另外两处违背「全局物理路径语义权威（Unified Wrapper Path-Semantics Authority）」的关键缺陷：

1. **尾随斜杠导致叶子符号链接被静默遍历（Trailing-Slash Leaf Symlink Traversal）**：
   - 此前在 `validate_wrappers_preflight()` 中：
     - 先对原始文本执行 `norm_lex = os.path.normpath(w_lex)`，将包含符号链接与 `..` 的复合路径提前折叠（例如 `root/link/../W/` 被折叠为 `root/W`，检查了错误的目录）；
     - 然后对 `w_lex` 执行 `os.lstat(w_lex)`。在 POSIX 语义中，当路径末尾带有斜杠 `/` 时，系统调用会将该末尾斜杠隐式解析为对该目录项的解引用遍历（dereference）。如果该叶子节点本身是符号链接（例如 `root/A/W -> root/A/Real`），`os.lstat(".../W/")` 返回的是目标目录的模式（`S_ISDIR` 为 True，`S_ISLNK` 为 False），导致叶子符号链接未能被安全拦截；
     - 后续 `discover_flatten_one_level()` 通过该符号链接扫描了目标内容，破坏了「禁止遍历符号链接 Wrapper」的安全硬约束。

2. **Schema 校验误杀物理相异 Wrapper（Schema False Duplicate Rejection）**：
   - 此前 `FlattenOneLevelAction.validate_wrapper_paths()` 在 Pydantic 校验层维护了 `seen_norm = set()` 并对每个输入执行 `os.path.normpath(item)`；
   - 具有相同文本规范化形式但在物理文件系统中实际指向不同目录的路径（例如：`p1 = root/link/../W -> root/A/W` 与 `p2 = root/W -> root/W`）被 Schema 误判为重复，抛出 HTTP 422 `ValidationError`；
   - Schema 层属于纯语法校验，不应也不可能在尚未遍历文件系统前推断物理身份。

3. **根目录等价性文本误判（Allowed-Root Equality False Positive）**：
   - 此前 `validate_wrappers_preflight()` 中存在 `norm_w = os.path.normpath(w_lex)` 并与 `norm_r = str(r)` 进行文本比对（`norm_w == norm_r`）；
   - 当输入为 `root/link/..` 时（物理实际指向 `root/A`，非 allowed root），文本 `normpath` 错误将其折叠为 `root`，导致合法 Wrapper 被误判为根目录本身并被拒绝（HTTP 422 `Wrapper cannot be an allowed root`）。

---

## 2. 核心架构修复与代码改动

### 2.1 全局 E3 路径语义不变式（Global Invariant）
对于已存在的 Wrapper 路径名，**必须以原始路径名在实际文件系统中的物理遍历语义**来确定所选定的物理目录。严禁在解析/验证实际文件系统对象之前使用 `os.path.normpath(path)` 作为物理权威。

### 2.2 `app/batch_utilities/schema.py`
- 在 `FlattenOneLevelAction.validate_wrapper_paths()` 中：
  - 移除 `seen_norm` 及 `os.path.normpath(item)` 逻辑；
  - 仅使用 `seen = set()` 检查精确原始文本重复（`item in seen`）；
  - 语法层仅确保非空列表、字符串类型、绝对路径以及无完全相同文本项；物理重复与重叠交由物理预检层（`check_wrapper_overlap`）与规范化层权威处理。

### 2.3 `app/batch_utilities/flatten_graph.py`
- 重构 `validate_wrappers_preflight()`：
  - **叶子节点无遍历 lstat 检查**：
    通过 `raw_leaf = w_lex.rstrip("/") or "/"` 剥除尾随斜杠，确保 `os.lstat(raw_leaf)` 检查的是叶子节点本身而非解引用后的目标对象。若 `stat.S_ISLNK(st_leaf.st_mode)`，立即抛出 `BatchUtilitySymlinkBlockedError`（HTTP 409 `BATCH_UTILITY_SYMLINK_BLOCKED`），彻底阻断后续 discovery；
  - **物理遍历严格解析**：
    调用 `w_phys = w_path.resolve(strict=True)`，若遭遇不存在或权限异常严格抛出对应结构化错误，严禁推测性文本回退；
  - **基于物理解析路径的安全边界与根目录比对**：
    - 使用 `w_phys` 校验隔离区（`is_reserved_quarantine_path`）与白名单根（`is_path_allowed`）；
    - 移除 `norm_w == norm_r` 文本比对，仅在物理级别比对 `w_phys == r_phys`（`r.resolve(strict=True)`）；
  - 调用 `check_wrapper_overlap()` 执行严格的物理重复与祖先-后代重叠检测。

### 2.4 零范围外修改
- 未修改 `app/batch_utilities/graph.py`、`app/execution/executor.py`、`app/fs_ops.py`、`app/tasks/handlers.py`、`app/models.py`、`frontend/**`、`migrations/**`、`app/workflows/**`。
- 零 DB migration，零新 Worker，零新 Undo 引擎。

---

## 3. 测试验证

### 3.1 针对性回归测试（Compiler + API + Generate）
在测试套件中补充了完整的端到端回归覆盖：
1. **A. 尾随斜杠叶子符号链接拦截（Trailing-Slash Leaf Symlink Blocked）**：
   - `test_preflight_symlink_sensitive_trailing_slash_leaf_symlink_blocked`
   - `test_preview_symlink_sensitive_trailing_slash_leaf_symlink_blocked`
   - `test_generate_symlink_sensitive_trailing_slash_leaf_symlink_blocked`
   - 验证：在 discovery 之前即被 preflight 拦截，HTTP 409 `BATCH_UTILITY_SYMLINK_BLOCKED`，0 discovery 扫描，0 draft 写入数据库。
2. **B. 相同 normpath 文本的物理不同 Wrapper 正常接受（Physically Distinct Accepted）**：
   - `test_compiler_physically_distinct_wrappers_same_normpath_accepted`
   - `test_preview_physically_distinct_wrappers_same_normpath_accepted`
   - `test_generate_physically_distinct_wrappers_same_normpath_accepted`
   - 验证：Schema 接受、Preview 接受、Generate 201 成功生成包含两个独立 Wrapper 候选项的草案。
3. **C. 符号链接 `..` 遍历的根目录比对正常接受（Root Equality Symlink Dotdot Accepted）**：
   - `test_preflight_allowed_root_equality_symlink_dotdot_accepted`
   - `test_preview_allowed_root_equality_symlink_dotdot_accepted`
   - 验证：`root/link/..` 物理指向 `root/A`，不再被文本误判为根目录，正常接受。
4. **D. 真实物理重复与重叠持续拦截**：
   - `test_compiler_true_physical_duplicate_rejected_overlap`
   - 验证：`root/X/../W` 与 `root/W` 物理一致时，依然被 `BatchUtilityScopeOverlapError`（422）拦截。
5. **E. Schema 精确文本重复拒绝**：
   - `test_schema_exact_duplicate_rejected`
   - 验证：完全相同字符串项仍被 Pydantic 拒绝。

### 3.2 自动化测试结果
- **针对性回归测试**：10 passed (100% PASS)
- **E3 核心套件（`pytest tests/test_gate5e_e3_*.py`）**：95 passed (100% PASS)
- **E1 + E2 套件（`pytest tests/test_gate5e_e1_*.py tests/test_gate5e_e2_*.py`）**：77 passed (100% PASS)
- **全量后端测试套件（`pytest tests/`）**：989 passed, 0 failed (100% PASS)

---

## 4. 边界与约束遵守确认

- [x] 未开启 E4。
- [x] 未声明 E3 PASS / CLOSED。
- [x] 零生产范围外修改：仅限 `app/batch_utilities/schema.py`、`app/batch_utilities/flatten_graph.py` 及测试文件。
- [x] 零 DB migration，零新 Worker，零新 Undo 引擎。
- [x] 完全遵守统一 Wrapper 物理路径语义权威规范。
